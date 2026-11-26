"""Application validation and non-scorecard eligibility rules."""
from __future__ import annotations

from typing import Any

from common import (
    DEMO_MODE, POLICY_VERSION, SUPPORTED_CURRENCY,
    safe_float, safe_int, as_bool,
)
from policy_generated import evaluate_stage1_hard_gates

ALLOWED_EMPLOYMENT = {"FULL_TIME", "PART_TIME", "SELF_EMPLOYED", "FIXED_TERM", "UNEMPLOYED"}
ALLOWED_TERMS = {12, 24, 36, 48, 60, 72, 84}


def evaluate_hard_gates(application: dict[str, Any]) -> dict[str, Any]:
    """Validate application data and apply transparent demo eligibility gates."""
    errors: list[str] = []

    try:
        age = safe_int(application.get("applicant_age"), "applicant_age", minimum=0)
        income = safe_float(application.get("monthly_income"), "monthly_income", minimum=0)
        requested = safe_float(application.get("requested_amount"), "requested_amount", minimum=0)
        debt = safe_float(application.get("existing_monthly_debt_payments", 0), "existing_monthly_debt_payments", minimum=0)
        housing = safe_float(application.get("monthly_housing_cost", 0), "monthly_housing_cost", minimum=0)
        term = safe_int(application.get("loan_term_months"), "loan_term_months", minimum=1)
    except ValueError as exc:
        errors.append(str(exc))
        age = 0
        income = requested = debt = housing = 0.0
        term = 0

    employment = str(application.get("employment_status", "")).strip().upper()
    consent = as_bool(application.get("data_sharing_consent"), default=False)
    applicant_id = str(application.get("applicant_id", "")).strip()
    applicant_name = str(application.get("applicant_name", "")).strip()
    currency = str(application.get("currency", SUPPORTED_CURRENCY)).strip().upper()

    if not applicant_id:
        errors.append("applicant_id is required")
    if not applicant_name:
        errors.append("applicant_name is required")
    if employment not in ALLOWED_EMPLOYMENT:
        errors.append("employment_status is not an allowed value")
    if term and term not in ALLOWED_TERMS:
        errors.append(f"loan_term_months must be one of {sorted(ALLOWED_TERMS)}")
    if currency != SUPPORTED_CURRENCY:
        errors.append(f"This demonstration policy currently supports {SUPPORTED_CURRENCY} only")

    policy_result = evaluate_stage1_hard_gates(
        {
            "validation_error_count": len(errors),
            "applicant_age": age,
            "monthly_income": income,
            "employment_status": employment,
            "requested_amount": requested,
            "loan_term_months": term,
        }
    )
    checks = policy_result["checks"]
    policy_trace = policy_result["trace"]

    failed = [item for item in checks if item["status"] == "FAIL"]
    reason_codes = [item["reason_code"] for item in failed if item["reason_code"]]
    # Avoid duplicate codes when malformed input triggers more than one dependent check.
    reason_codes = list(dict.fromkeys(reason_codes))

    return {
        "stage": "HARD_GATES",
        "status": "PASS" if not failed else "FAIL",
        "passed": not failed,
        "applicant_id": applicant_id,
        "policy_version": POLICY_VERSION,
        "demo_mode": DEMO_MODE,
        "checks": checks,
        "policy_trace": policy_trace,
        "reason_codes": reason_codes,
        "validation_errors": errors,
        "validated_profile": {
            "age": age,
            "monthly_income": round(income, 2),
            "requested_amount": round(requested, 2),
            "existing_monthly_debt_payments": round(debt, 2),
            "monthly_housing_cost": round(housing, 2),
            "loan_term_months": term,
            "employment_status": employment,
            "data_sharing_consent": consent,
            "currency": currency,
        },
    }
