"""Deterministic synthetic credit-bureau adapter for local demonstrations."""
from __future__ import annotations

from typing import Any

from common import DEMO_MODE, POLICY_VERSION, stable_rng, utc_now


def get_bureau_data(
    applicant_id: str,
    declared_monthly_debt_payments: float,
    hard_gates: dict[str, Any],
) -> dict[str, Any]:
    """Return a realistic-shaped synthetic bureau response.

    Replace this adapter with a licensed bureau integration in a real deployment.
    The deterministic seed makes the same demo applicant reproducible.
    """
    if not hard_gates.get("passed", False):
        return {
            "stage": "CREDIT_BUREAU",
            "status": "SKIPPED",
            "decision_status": "NOT_ASSESSED",
            "passed": False,
            "applicant_id": applicant_id,
            "reason_codes": ["SKIPPED_AFTER_HARD_GATE_FAILURE"],
            "demo_mode": DEMO_MODE,
        }

    rng = stable_rng("bureau-v1", applicant_id)
    bureau_score = rng.randint(625, 805)
    active_delinquencies = rng.choices([0, 1, 2], weights=[0.86, 0.12, 0.02], k=1)[0]
    public_records = rng.choices([0, 1], weights=[0.985, 0.015], k=1)[0]
    utilization = round(rng.uniform(0.12, 0.82), 3)
    inquiries_6m = rng.choices([0, 1, 2, 3, 4, 5, 6], weights=[0.18, 0.22, 0.22, 0.18, 0.11, 0.06, 0.03], k=1)[0]
    oldest_account_months = rng.randint(14, 180)
    reported_debt = round(max(0.0, declared_monthly_debt_payments * rng.uniform(0.90, 1.16)), 2)
    accounts_in_good_standing = rng.randint(2, 12)
    total_open_accounts = max(accounts_in_good_standing, rng.randint(3, 15))

    reasons: list[str] = []
    if public_records > 0:
        decision_status = "DECLINE"
        reasons.append("BUREAU_PUBLIC_RECORD")
    elif active_delinquencies >= 2:
        decision_status = "DECLINE"
        reasons.append("MULTIPLE_ACTIVE_DELINQUENCIES")
    elif bureau_score < 520:
        decision_status = "DECLINE"
        reasons.append("BUREAU_SCORE_BELOW_MINIMUM")
    elif bureau_score < 640 or active_delinquencies == 1 or utilization >= 0.90 or inquiries_6m >= 6 or total_open_accounts < 4:
        decision_status = "REFER"
        if bureau_score < 640:
            reasons.append("BUREAU_SCORE_REVIEW_BAND")
        if active_delinquencies == 1:
            reasons.append("ACTIVE_DELINQUENCY_REVIEW")
        if utilization >= 0.90:
            reasons.append("HIGH_REVOLVING_UTILIZATION")
        if inquiries_6m >= 6:
            reasons.append("HIGH_RECENT_CREDIT_SEEKING")
        if total_open_accounts < 4:
            reasons.append("THIN_CREDIT_FILE_REVIEW")
    else:
        decision_status = "PASS"
        reasons.append("BUREAU_WITHIN_DEMO_POLICY")

    return {
        "stage": "CREDIT_BUREAU",
        "status": "SUCCESS",
        "decision_status": decision_status,
        "passed": decision_status == "PASS",
        "applicant_id": applicant_id,
        "provider": "SYNTHETIC_BUREAU_ADAPTER",
        "provider_reference": f"BR-{stable_rng(applicant_id, 'bureau-ref').randint(10000000, 99999999)}",
        "retrieved_at": utc_now(),
        "bureau_score": bureau_score,
        "active_delinquencies": active_delinquencies,
        "public_records": public_records,
        "revolving_utilization": utilization,
        "recent_inquiries_6m": inquiries_6m,
        "oldest_account_months": oldest_account_months,
        "accounts_in_good_standing": accounts_in_good_standing,
        "total_open_accounts": total_open_accounts,
        "reported_monthly_debt_payments": reported_debt,
        "reason_codes": reasons,
        "policy_version": POLICY_VERSION,
        "demo_mode": DEMO_MODE,
        "data_quality": {
            "score_available": True,
            "tradeline_count": total_open_accounts,
            "file_status": "THICK_FILE" if total_open_accounts >= 5 else "THIN_FILE",
        },
    }
