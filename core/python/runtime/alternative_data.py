"""Synthetic adapters for the ten UWflow alternative-data connectors.

Every adapter returns one normalized 0-100 profile_input_score for the
AIDflow customer-profile inference step. These are synthetic demonstration
signals, not validated credit-risk features.
"""
from __future__ import annotations

from typing import Any

from common import DEMO_MODE, stable_rng, utc_now

SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "telco_stability": {
        "name": "Telecom payment history",
        "provider": "SYNTHETIC_TELCO_ADAPTER",
        "role": "CREDIT_SIGNAL",
    },
    "utility_reliability": {
        "name": "Utility payment history",
        "provider": "SYNTHETIC_UTILITY_ADAPTER",
        "role": "CREDIT_SIGNAL",
    },
    "open_banking_cashflow": {
        "name": "Consented open-banking cash flow",
        "provider": "SYNTHETIC_OPEN_BANKING_ADAPTER",
        "role": "CREDIT_SIGNAL",
    },
    "device_fingerprint": {
        "name": "Device integrity check",
        "provider": "SYNTHETIC_DEVICE_INTELLIGENCE_ADAPTER",
        "role": "FRAUD_CONTROL",
    },
    "geo_mobility": {
        "name": "Session continuity check",
        "provider": "SYNTHETIC_SESSION_CONTINUITY_ADAPTER",
        "role": "IDENTITY_CONTROL",
    },
    "ecommerce_behavior": {
        "name": "Transaction integrity indicators",
        "provider": "SYNTHETIC_TRANSACTION_INTEGRITY_ADAPTER",
        "role": "FRAUD_CONTROL",
    },
    "digital_identity_age": {
        "name": "Digital identity verification",
        "provider": "SYNTHETIC_IDENTITY_ADAPTER",
        "role": "IDENTITY_CONTROL",
    },
    "income_velocity": {
        "name": "Income consistency and regularity",
        "provider": "SYNTHETIC_INCOME_ANALYTICS_ADAPTER",
        "role": "CREDIT_SIGNAL",
    },
    "microloan_history": {
        "name": "Small-ticket repayment history",
        "provider": "SYNTHETIC_MICROCREDIT_ADAPTER",
        "role": "CREDIT_SIGNAL",
    },
    "merchant_affinity": {
        "name": "Merchant concentration context",
        "provider": "SYNTHETIC_MERCHANT_CONTEXT_ADAPTER",
        "role": "INFORMATIONAL_ONLY",
    },
}

SOURCE_IDS = list(SOURCE_CATALOG)


def _credit_signal(source_id: str, rng: Any, application: dict[str, Any]) -> dict[str, Any]:
    income = float(application["monthly_income"])
    if source_id == "telco_stability":
        on_time = rng.randint(9, 12)
        score = round(55 + (on_time / 12) * 43 + rng.uniform(-3, 3), 1)
        metrics = {"months_observed": 12, "on_time_payments": on_time, "late_payments": 12 - on_time}
    elif source_id == "utility_reliability":
        on_time = rng.randint(9, 12)
        score = round(53 + (on_time / 12) * 45 + rng.uniform(-3, 3), 1)
        metrics = {"months_observed": 12, "on_time_payments": on_time, "late_payments": 12 - on_time}
    elif source_id == "open_banking_cashflow":
        volatility = round(rng.uniform(0.06, 0.28), 3)
        regular_inflows = rng.randint(5, 6)
        inflow = round(income * rng.uniform(0.94, 1.14), 2)
        score = round(96 - volatility * 105 + (regular_inflows - 5) * 4 + rng.uniform(-2, 2), 1)
        metrics = {
            "months_observed": 6,
            "regular_income_inflows": regular_inflows,
            "average_monthly_income_inflow": inflow,
            "income_volatility_coefficient": volatility,
            "returned_debits_6m": rng.choices([0, 1, 2], weights=[0.78, 0.18, 0.04], k=1)[0],
        }
    elif source_id == "income_velocity":
        observed = rng.randint(5, 6)
        volatility = round(rng.uniform(0.04, 0.25), 3)
        score = round(97 - volatility * 100 + (observed - 5) * 2 + rng.uniform(-2, 2), 1)
        metrics = {"months_observed": observed, "income_volatility_coefficient": volatility, "income_trend_6m_pct": round(rng.uniform(-0.04, 0.11), 3)}
    elif source_id == "microloan_history":
        total = rng.randint(2, 8)
        on_time = rng.randint(max(1, total - 1), total)
        score = round(48 + (on_time / total) * 50 + rng.uniform(-2, 2), 1)
        metrics = {"facilities_observed": total, "repaid_on_time": on_time, "currently_overdue": 0}
    else:  # Defensive guard if the catalogue and adapter drift apart.
        raise ValueError(f"Unsupported credit signal source: {source_id}")

    return {"signal_score": round(max(0.0, min(100.0, score)), 1), "metrics": metrics}


def _control_signal(source_id: str, rng: Any) -> dict[str, Any]:
    if source_id == "device_fingerprint":
        risk = rng.choices(["CLEAR", "REVIEW", "ALERT"], weights=[0.92, 0.07, 0.01], k=1)[0]
        return {
            "risk_level": risk,
            "metrics": {
                "device_reputation": rng.choice(["KNOWN_GOOD", "NEUTRAL", "NEW_DEVICE"]),
                "emulator_detected": False if risk != "ALERT" else rng.choice([True, False]),
                "ip_proxy_indicator": False if risk != "ALERT" else rng.choice([True, False]),
            },
        }
    if source_id == "geo_mobility":
        risk = rng.choices(["CLEAR", "REVIEW"], weights=[0.95, 0.05], k=1)[0]
        return {
            "risk_level": risk,
            "metrics": {
                "session_continuity": "CONSISTENT" if risk == "CLEAR" else "INCONSISTENT",
                "impossible_travel_flag": False,
            },
        }
    if source_id == "digital_identity_age":
        status = rng.choices(["VERIFIED", "REVIEW"], weights=[0.97, 0.03], k=1)[0]
        return {
            "risk_level": "CLEAR" if status == "VERIFIED" else "REVIEW",
            "metrics": {
                "identity_status": status,
                "document_verification": "PASSED" if status == "VERIFIED" else "MANUAL_CHECK_REQUIRED",
                "liveness_check": "PASSED" if status == "VERIFIED" else "REVIEW",
            },
        }
    if source_id == "ecommerce_behavior":
        risk = rng.choices(["CLEAR", "REVIEW"], weights=[0.96, 0.04], k=1)[0]
        return {
            "risk_level": risk,
            "metrics": {
                "payment_dispute_pattern": "NORMAL" if risk == "CLEAR" else "REVIEW_REQUIRED",
                "account_takeover_indicator": False,
            },
        }
    raise ValueError(f"Unsupported control source: {source_id}")


def get_alternative_data(source_id: str, applicant_id: str, application: dict[str, Any]) -> dict[str, Any]:
    """Return a provider-shaped synthetic result for one source."""
    if source_id not in SOURCE_CATALOG:
        raise ValueError(f"Unknown alternative-data source: {source_id}")

    meta = SOURCE_CATALOG[source_id]
    rng = stable_rng("alternative-data-v1", applicant_id, source_id)

    if meta["role"] == "CREDIT_SIGNAL":
        payload = _credit_signal(source_id, rng, application)
        reason_codes = ["SYNTHETIC_CREDIT_SIGNAL_AVAILABLE"]
    elif meta["role"] in {"FRAUD_CONTROL", "IDENTITY_CONTROL"}:
        payload = _control_signal(source_id, rng)
        reason_codes = [f"{source_id.upper()}_{payload['risk_level']}"]
    else:
        payload = {
            "metrics": {
                "merchant_concentration_index": round(rng.uniform(0.15, 0.75), 3),
                "data_purpose": "INFORMATIONAL_ONLY_NOT_USED_IN_CREDIT_DECISION",
            }
        }
        reason_codes = ["INFORMATIONAL_ONLY"]

    # AIDflow consumes one normalized score from each of the ten connectors.
    # Higher always means a stronger / clearer / more consistent profile input.
    if meta["role"] == "CREDIT_SIGNAL":
        profile_input_score = float(payload["signal_score"])
    elif meta["role"] in {"FRAUD_CONTROL", "IDENTITY_CONTROL"}:
        profile_input_score = {"CLEAR": 96.0, "REVIEW": 52.0, "ALERT": 12.0}[payload["risk_level"]]
    else:
        concentration = float(payload["metrics"]["merchant_concentration_index"])
        profile_input_score = round(100.0 - concentration * 25.0, 1)

    return {
        "source_id": source_id,
        "source_name": meta["name"],
        "provider": meta["provider"],
        "source_role": meta["role"],
        "profile_input_score": round(profile_input_score, 1),
        "profile_input_scale": "0-100_HIGHER_IS_STRONGER",
        "status": "SUCCESS",
        "coverage": "FULL",
        "retrieved_at": utc_now(),
        "freshness_days": rng.randint(0, 3),
        "latency_ms": rng.randint(75, 420),
        "applicant_id": applicant_id,
        "demo_mode": DEMO_MODE,
        "reason_codes": reason_codes,
        **payload,
    }
