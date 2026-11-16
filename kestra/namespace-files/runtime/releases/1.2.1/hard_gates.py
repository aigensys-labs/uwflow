"""Application validation and non-scorecard eligibility rules."""
from __future__ import annotations

from typing import Any

from common import (
    DEMO_MODE, POLICY_VERSION, SUPPORTED_CURRENCY,
    MIN_MONTHLY_INCOME, MIN_REQUEST_AMOUNT, MAX_REQUEST_AMOUNT,
    safe_float, safe_int, as_bool,
)

ALLOWED_EMPLOYMENT = {"FULL_TIME", "PART_TIME", "SELF_EMPLOYED", "FIXED_TERM", "UNEMPLOYED"}
ALLOWED_TERMS = {12, 24, 36, 48, 60, 72, 84}


def evaluate_hard_gates(application: dict[str, Any]) -> dict[str, Any]:
    """Validate application data and apply transparent demo eligibility gates."""
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

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

    def add_check(check_id: str, passed: bool, reason_code: str, description: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "reason_code": None if passed else reason_code,
            "description": description,
        })

    add_check("APPLICATION_DATA_VALID", not errors, "INVALID_APPLICATION_DATA", "Required fields, numeric ranges and supported product parameters are valid")
    add_check("MINIMUM_AGE", 18 <= age <= 75, "AGE_OUT_OF_POLICY", "Applicant age must be between 18 and 75 inclusive")
    add_check(
        "MINIMUM_INCOME",
        income >= MIN_MONTHLY_INCOME,
        "INCOME_BELOW_POLICY_FLOOR",
        f"Verified gross monthly income must be at least {SUPPORTED_CURRENCY} {MIN_MONTHLY_INCOME:,.2f}",
    )
    add_check("EMPLOYMENT_STATUS", employment != "UNEMPLOYED", "UNEMPLOYED_STATUS", "Unemployed applicants do not meet this demo product's eligibility policy")
    add_check(
        "REQUEST_AMOUNT",
        MIN_REQUEST_AMOUNT <= requested <= MAX_REQUEST_AMOUNT,
        "REQUEST_AMOUNT_OUT_OF_RANGE",
        f"Requested principal must be between {SUPPORTED_CURRENCY} {MIN_REQUEST_AMOUNT:,.2f} and {SUPPORTED_CURRENCY} {MAX_REQUEST_AMOUNT:,.2f}",
    )
    add_check("LOAN_TERM", term in ALLOWED_TERMS, "UNSUPPORTED_LOAN_TERM", "Requested term must be one of 12, 24, 36, 48, 60, 72 or 84 months")

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
