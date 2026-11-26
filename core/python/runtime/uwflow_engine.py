"""UWflow underwriting orchestration decision, affordability and pricing.

UWflow consumes application data, hard-gate results, bureau assessment and the
single AIDflow complex-customer-profile score. It owns the final underwriting
decision; AIDflow owns only scoring / inference.
"""
from __future__ import annotations

import hashlib
from typing import Any

from common import (
    DEMO_MODE, POLICY_VERSION, SUPPORTED_CURRENCY, MIN_RESIDUAL_INCOME,
    MIN_OFFER_AMOUNT, MAX_OFFER_AMOUNT, utc_now,
)

UWFLOW_VERSION = "UWFLOW-UNDERWRITING-1.2-EUR"
RISK_TIERS = (
    (780, "A_PRIME", 8.9),
    (720, "B_STANDARD", 10.9),
    (660, "C_NEAR_PRIME", 14.9),
    (620, "D_SUBPRIME", 18.9),
)


def monthly_payment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    if principal <= 0 or term_months <= 0:
        return 0.0
    monthly_rate = annual_rate_pct / 100.0 / 12.0
    if monthly_rate == 0:
        return principal / term_months
    factor = (1.0 + monthly_rate) ** term_months
    return principal * (monthly_rate * factor) / (factor - 1.0)


def principal_from_payment(payment: float, annual_rate_pct: float, term_months: int) -> float:
    if payment <= 0 or term_months <= 0:
        return 0.0
    monthly_rate = annual_rate_pct / 100.0 / 12.0
    if monthly_rate == 0:
        return payment * term_months
    return payment * (1.0 - (1.0 + monthly_rate) ** (-term_months)) / monthly_rate


def _decision_ref(applicant_id: str) -> str:
    digest = hashlib.sha256(f"{applicant_id}:{UWFLOW_VERSION}".encode("utf-8")).hexdigest()[:12].upper()
    return f"UWF-{digest}"


def _tier_for_score(score: int) -> tuple[str, float]:
    for minimum, tier, apr in RISK_TIERS:
        if score >= minimum:
            return tier, apr
    return "BELOW_POLICY", 0.0


def _base_result(
    application: dict[str, Any], hard_gates: dict[str, Any], bureau: dict[str, Any],
    aidflow_result: dict[str, Any], runtime_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "engine": "UWflow Underwriting Engine",
        "engine_version": UWFLOW_VERSION,
        "policy_version": POLICY_VERSION,
        "decision_reference": _decision_ref(str(application.get("applicant_id", "UNKNOWN"))),
        "application_id": application.get("applicant_id"),
        "applicant_display_name": application.get("applicant_name"),
        "decision_timestamp": utc_now(),
        "run_mode": DEMO_MODE,
        "currency": application.get("currency", SUPPORTED_CURRENCY),
        "hard_gates": hard_gates,
        "bureau_assessment": bureau,
        "aidflow_scoring": aidflow_result,
        "runtime_provenance": runtime_provenance or {},
    }


def _finalize(base: dict[str, Any], decision: str, reason_codes: list[str], **extra: Any) -> dict[str, Any]:
    return {
        **base,
        "decision": decision,
        "decision_status": "FINAL" if decision in {"APPROVED", "COUNTEROFFER", "DECLINED"} else "PENDING_MANUAL_REVIEW",
        "reason_codes": list(dict.fromkeys(reason_codes)),
        **extra,
    }


def run_uwflow_decision(
    application: dict[str, Any],
    hard_gates: dict[str, Any],
    bureau: dict[str, Any],
    aidflow_result: dict[str, Any],
    source_results: list[dict[str, Any]],
    runtime_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply UWflow underwriting policy using the single AIDflow profile score."""
    base = _base_result(application, hard_gates, bureau, aidflow_result, runtime_provenance)
    events: list[dict[str, Any]] = [
        {"event": "APPLICATION_RECEIVED", "status": "COMPLETE", "timestamp": utc_now()},
        {"event": "HARD_GATES_EVALUATED", "status": hard_gates.get("status"), "timestamp": utc_now()},
    ]
    if runtime_provenance:
        events.append({
            "event": "RUNTIME_SOURCE_VERIFIED",
            "status": f"{runtime_provenance.get('runtime_release')}:{runtime_provenance.get('integrity_status')}",
            "timestamp": utc_now(),
        })
    source_by_id = {str(item.get("source_id")): item for item in source_results if item.get("source_id")}

    if not hard_gates.get("passed", False):
        events.append({"event": "UNDERWRITING_STOPPED", "status": "HARD_GATE_FAILURE", "timestamp": utc_now()})
        return _finalize(
            base, "DECLINED", hard_gates.get("reason_codes", ["HARD_GATE_FAILURE"]),
            complex_customer_profile_score=None, profile_band="NOT_SCORED", risk_tier="NOT_SCORED",
            approved_amount=0.0, offered_apr_percent=None, monthly_installment=None,
            principal_decision_factors=[c["description"] for c in hard_gates.get("checks", []) if c.get("status") == "FAIL"],
            policy_checks=hard_gates.get("checks", []), source_results=source_results,
            audit_events=events,
        )

    if bureau.get("decision_status") == "DECLINE":
        events.append({"event": "BUREAU_ASSESSED", "status": "DECLINE", "timestamp": utc_now()})
        return _finalize(
            base, "DECLINED", bureau.get("reason_codes", ["BUREAU_POLICY_DECLINE"]),
            complex_customer_profile_score=None, profile_band="NOT_SCORED", risk_tier="NOT_SCORED",
            approved_amount=0.0, offered_apr_percent=None, monthly_installment=None,
            principal_decision_factors=bureau.get("reason_codes", []),
            policy_checks=[{"check_id": "BUREAU_POLICY", "status": "FAIL", "reason_codes": bureau.get("reason_codes", [])}],
            source_results=source_results,
            audit_events=events + [{"event": "UNDERWRITING_STOPPED", "status": "BUREAU_DECLINE", "timestamp": utc_now()}],
        )

    if not bureau.get("bureau_score"):
        return _finalize(
            base, "REFER", ["BUREAU_DATA_UNAVAILABLE"],
            complex_customer_profile_score=aidflow_result.get("complex_customer_profile_score"),
            profile_band=aidflow_result.get("profile_band", "NOT_SCORED"), risk_tier="PENDING_REVIEW",
            approved_amount=0.0,
            principal_decision_factors=["Credit bureau data was not available for automated assessment."],
            source_results=source_results, audit_events=events,
        )

    profile_score = aidflow_result.get("complex_customer_profile_score")
    if aidflow_result.get("scoring_status") != "SCORED" or profile_score is None:
        events.append({"event": "AIDFLOW_INFERENCE", "status": "INCOMPLETE", "timestamp": utc_now()})
        return _finalize(
            base, "REFER", ["AIDFLOW_PROFILE_SCORE_UNAVAILABLE", "MANUAL_UNDERWRITER_REVIEW_REQUIRED"],
            complex_customer_profile_score=None, profile_band="NOT_SCORED", risk_tier="PENDING_REVIEW",
            approved_amount=0.0,
            source_results=source_results,
            source_coverage={"successful_sources": len(source_results), "expected_profile_inputs": 10},
            principal_decision_factors=["AIDflow did not receive all ten valid source scores; manual review is required."],
            policy_checks=[{"check_id": "AIDFLOW_PROFILE_INPUT_COVERAGE", "status": "REFER", "received": aidflow_result.get("input_score_count", 0), "required": 10}],
            audit_events=events,
        )

    profile_score = int(profile_score)
    profile_band = str(aidflow_result.get("profile_band", "UNKNOWN"))
    identity_alerts = []
    for source_id in ("device_fingerprint", "geo_mobility", "digital_identity_age", "ecommerce_behavior"):
        record = source_by_id.get(source_id)
        if record and record.get("risk_level") in {"REVIEW", "ALERT"}:
            identity_alerts.append({
                "source_id": source_id,
                "risk_level": record["risk_level"],
                "reason_codes": record.get("reason_codes", []),
            })

    events.append({"event": "BUREAU_ASSESSED", "status": bureau.get("decision_status"), "timestamp": utc_now()})
    events.append({"event": "AIDFLOW_INFERENCE_COMPLETED", "status": str(profile_score), "timestamp": utc_now()})

    if bureau.get("decision_status") == "REFER" or identity_alerts:
        factors = []
        if bureau.get("decision_status") == "REFER":
            factors.append("The bureau response falls within the manual-review policy band.")
        if identity_alerts:
            factors.append("One or more identity or transaction-integrity controls require human review.")
        events.append({"event": "FINAL_DECISION", "status": "REFER", "timestamp": utc_now()})
        return _finalize(
            base, "REFER", ["MANUAL_UNDERWRITER_REVIEW_REQUIRED"] + bureau.get("reason_codes", []),
            complex_customer_profile_score=profile_score, profile_band=profile_band,
            risk_tier="PENDING_REVIEW", source_results=source_results,
            source_coverage={"successful_sources": len(source_results), "expected_profile_inputs": 10},
            identity_review_flags=identity_alerts, approved_amount=0.0,
            indicative_apr_percent=_tier_for_score(profile_score)[1],
            principal_decision_factors=factors,
            policy_checks=[
                {"check_id": "AIDFLOW_PROFILE_INPUT_COVERAGE", "status": "PASS", "received": 10, "required": 10},
                {"check_id": "IDENTITY_AND_FRAUD_CONTROLS", "status": "REFER" if identity_alerts else "PASS", "flags": identity_alerts},
                {"check_id": "BUREAU_POLICY", "status": bureau.get("decision_status")},
            ], audit_events=events,
        )

    tier, apr = _tier_for_score(profile_score)
    if profile_score < 570:
        return _finalize(
            base, "DECLINED", ["PROFILE_SCORE_BELOW_MINIMUM_POLICY_THRESHOLD"],
            complex_customer_profile_score=profile_score, profile_band=profile_band,
            risk_tier="BELOW_POLICY", source_results=source_results, approved_amount=0.0,
            principal_decision_factors=["AIDflow complex customer profile score is below the minimum demo policy threshold."],
            policy_checks=[{"check_id": "MINIMUM_PROFILE_SCORE", "status": "FAIL", "score": profile_score, "minimum": 570}],
            audit_events=events + [{"event": "FINAL_DECISION", "status": "DECLINED", "timestamp": utc_now()}],
        )
    if profile_score < 620:
        return _finalize(
            base, "REFER", ["PROFILE_SCORE_IN_MANUAL_REVIEW_BAND"],
            complex_customer_profile_score=profile_score, profile_band=profile_band,
            risk_tier="PENDING_REVIEW", source_results=source_results, approved_amount=0.0,
            indicative_apr_percent=apr,
            principal_decision_factors=["AIDflow complex customer profile score falls within the manual-review band."],
            policy_checks=[{"check_id": "MINIMUM_AUTOMATED_PROFILE_SCORE", "status": "REFER", "score": profile_score, "minimum": 620}],
            audit_events=events + [{"event": "FINAL_DECISION", "status": "REFER", "timestamp": utc_now()}],
        )

    monthly_income = float(application["monthly_income"])
    declared_debt = float(application.get("existing_monthly_debt_payments", 0))
    bureau_debt = float(bureau.get("reported_monthly_debt_payments", 0))
    existing_debt = max(declared_debt, bureau_debt)
    housing = float(application.get("monthly_housing_cost", 0))
    term = int(application["loan_term_months"])
    requested = float(application["requested_amount"])
    min_residual_income = max(MIN_RESIDUAL_INCOME, monthly_income * 0.20)

    max_payment_dti = max(0.0, monthly_income * 0.45 - existing_debt)
    max_payment_pti = monthly_income * 0.30
    max_payment_residual = max(0.0, monthly_income - existing_debt - housing - min_residual_income)
    max_affordable_payment = min(max_payment_dti, max_payment_pti, max_payment_residual)
    max_affordable_principal = principal_from_payment(max_affordable_payment, apr, term)
    approved_cap = min(MAX_OFFER_AMOUNT, max_affordable_principal)
    approved_amount = round(min(requested, approved_cap), 2)

    affordability_checks = [
        {"check_id": "MAX_DTI", "status": "PASS" if max_payment_dti > 0 else "FAIL", "limit": 0.45, "existing_monthly_debt": round(existing_debt, 2)},
        {"check_id": "MAX_PAYMENT_TO_INCOME", "status": "PASS" if max_payment_pti > 0 else "FAIL", "limit": 0.30},
        {"check_id": "MINIMUM_RESIDUAL_INCOME", "status": "PASS" if max_payment_residual > 0 else "FAIL", "minimum_residual_income": round(min_residual_income, 2)},
        {"check_id": "MINIMUM_OFFER_AMOUNT", "status": "PASS" if approved_amount >= MIN_OFFER_AMOUNT else "FAIL", "minimum": MIN_OFFER_AMOUNT, "calculated_cap": round(approved_cap, 2)},
    ]

    if approved_amount < MIN_OFFER_AMOUNT:
        return _finalize(
            base, "DECLINED", ["INSUFFICIENT_AFFORDABILITY_CAPACITY"],
            complex_customer_profile_score=profile_score, profile_band=profile_band, risk_tier=tier,
            source_results=source_results,
            affordability={
                "existing_monthly_debt_payments_used": round(existing_debt, 2),
                "max_affordable_monthly_payment": round(max_affordable_payment, 2),
                "max_affordable_principal": round(approved_cap, 2),
                "minimum_residual_income": round(min_residual_income, 2),
                "checks": affordability_checks,
            },
            approved_amount=0.0, offered_apr_percent=None,
            principal_decision_factors=["Verified income and existing obligations do not support the minimum product amount under the demo affordability limits."],
            policy_checks=affordability_checks,
            audit_events=events + [{"event": "AFFORDABILITY_ASSESSED", "status": "FAIL", "timestamp": utc_now()}, {"event": "FINAL_DECISION", "status": "DECLINED", "timestamp": utc_now()}],
        )

    installment = monthly_payment(approved_amount, apr, term)
    post_offer_dti = (existing_debt + installment) / monthly_income
    post_offer_pti = installment / monthly_income
    residual_income = monthly_income - existing_debt - housing - installment
    decision = "APPROVED" if approved_amount >= requested else "COUNTEROFFER"
    decision_reasons = ["PROFILE_AND_AFFORDABILITY_WITHIN_UWFLOW_POLICY"]
    if decision == "COUNTEROFFER":
        decision_reasons.append("REQUEST_REDUCED_TO_AFFORDABLE_AMOUNT")

    affordability = {
        "monthly_income_used": round(monthly_income, 2),
        "existing_monthly_debt_payments_used": round(existing_debt, 2),
        "monthly_housing_cost": round(housing, 2),
        "proposed_monthly_installment": round(installment, 2),
        "post_offer_dti": round(post_offer_dti, 4),
        "post_offer_pti": round(post_offer_pti, 4),
        "residual_income_after_debt_housing_and_offer": round(residual_income, 2),
        "maximum_dti": 0.45,
        "maximum_pti": 0.30,
        "minimum_residual_income": round(min_residual_income, 2),
        "maximum_affordable_monthly_payment": round(max_affordable_payment, 2),
        "maximum_affordable_principal": round(approved_cap, 2),
        "checks": affordability_checks,
    }

    events.extend([
        {"event": "AFFORDABILITY_ASSESSED", "status": "PASS", "timestamp": utc_now()},
        {"event": "PRICING_CALCULATED", "status": tier, "timestamp": utc_now()},
        {"event": "FINAL_DECISION", "status": decision, "timestamp": utc_now()},
    ])
    return _finalize(
        base, decision, decision_reasons,
        complex_customer_profile_score=profile_score, profile_band=profile_band, risk_tier=tier,
        source_results=source_results,
        source_coverage={"successful_sources": len(source_results), "expected_profile_inputs": 10},
        identity_review_flags=identity_alerts,
        requested_amount=round(requested, 2), approved_amount=round(approved_amount, 2),
        currency=application.get("currency", SUPPORTED_CURRENCY), loan_term_months=term,
        offered_apr_percent=apr, monthly_installment=round(installment, 2),
        total_repayment=round(installment * term, 2),
        total_interest=round(installment * term - approved_amount, 2), affordability=affordability,
        principal_decision_factors=(
            ["AIDflow complex customer profile score meets the automated underwriting threshold."]
            + (["Requested amount was reduced to fit affordability limits."] if decision == "COUNTEROFFER" else [])
        ),
        policy_checks=[
            {"check_id": "MINIMUM_AUTOMATED_PROFILE_SCORE", "status": "PASS", "score": profile_score, "minimum": 620},
            {"check_id": "BUREAU_POLICY", "status": bureau.get("decision_status")},
            {"check_id": "AIDFLOW_PROFILE_INPUT_COVERAGE", "status": "PASS", "received": 10, "required": 10},
            *affordability_checks,
        ],
        model_governance={
            "scoring_engine": "AIDflow",
            "underwriting_engine": "UWflow",
            "score_used_for_underwriting": True,
            "score_definition": "One complex customer-profile score inferred from all ten normalized big-data source scores.",
            "bureau_score_is_separate": True,
            "synthetic_demo_only": True,
            "production_caution": "Validate legal basis, consent, data minimization, feature suitability, proxy risk, fairness, calibration and explainability before any real lending use.",
        },
        audit_events=events,
    )
