"""AIDflow customer-profile scoring / inference component.

AIDflow receives normalized scores from the ten UWflow data connectors and
returns one customer-profile score plus model diagnostics. It does not perform
eligibility checks, bureau policy, affordability, pricing, or final decisions.

This implementation is synthetic demonstration logic, not a validated lending
model. Do not use it for real credit decisions.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from common import DEMO_MODE, utc_now

# Demonstration weights: all ten source scores are consumed. The weights are
# configuration, not empirically calibrated model parameters.
PROFILE_INPUT_WEIGHTS: dict[str, float] = {
    "telco_stability": 0.10,
    "utility_reliability": 0.10,
    "open_banking_cashflow": 0.16,
    "device_fingerprint": 0.08,
    "geo_mobility": 0.06,
    "ecommerce_behavior": 0.08,
    "digital_identity_age": 0.08,
    "income_velocity": 0.12,
    "microloan_history": 0.12,
    "merchant_affinity": 0.10,
}

PROFILE_SCORE_VERSION = "AIDFLOW-CUSTOMER-PROFILE-1.0"
PROFILE_SCORE_MIN = 300
PROFILE_SCORE_MAX = 900


def _profile_band(score: int) -> str:
    if score >= 780:
        return "A_STRONG_PROFILE"
    if score >= 720:
        return "B_POSITIVE_PROFILE"
    if score >= 660:
        return "C_MODERATE_PROFILE"
    if score >= 620:
        return "D_WATCH_PROFILE"
    if score >= 570:
        return "E_WEAK_PROFILE"
    return "BELOW_PROFILE_THRESHOLD"


def score_customer_profile(source_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer one 300-900 customer profile score from all ten source scores.

    A complete inference requires one successful, finite 0-100 score from each
    configured source. No imputation or renormalization is performed: incomplete
    input returns INCOMPLETE and a null score.
    """
    by_id: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for result in source_results:
        source_id = str(result.get("source_id", ""))
        if source_id in by_id:
            duplicates.append(source_id)
        by_id[source_id] = result

    missing: list[str] = []
    invalid: list[str] = []
    rows: list[dict[str, Any]] = []
    weighted_total = 0.0

    for source_id, weight in PROFILE_INPUT_WEIGHTS.items():
        result = by_id.get(source_id)
        if result is None or result.get("status") != "SUCCESS":
            missing.append(source_id)
            continue

        raw_score = result.get("profile_input_score")
        try:
            score = float(raw_score)
            if not isfinite(score) or score < 0.0 or score > 100.0:
                raise ValueError
        except (TypeError, ValueError):
            invalid.append(source_id)
            continue

        contribution = score * weight
        weighted_total += contribution
        rows.append({
            "source_id": source_id,
            "source_name": result.get("source_name", source_id),
            "input_score_0_100": round(score, 2),
            "weight": weight,
            "weighted_contribution": round(contribution, 4),
            "source_role": result.get("source_role"),
            "status": "USED",
        })

    expected = len(PROFILE_INPUT_WEIGHTS)
    complete = len(rows) == expected and not duplicates and not missing and not invalid
    common = {
        "engine": "AIDflow Scoring & Inference Engine",
        "engine_version": PROFILE_SCORE_VERSION,
        "stage": "CUSTOMER_PROFILE_INFERENCE",
        "inference_timestamp": utc_now(),
        "run_mode": DEMO_MODE,
        "scoring_status": "SCORED" if complete else "INCOMPLETE",
        "input_score_count": len(rows),
        "expected_input_count": expected,
        "input_coverage": round(len(rows) / expected, 3),
        "missing_source_ids": missing,
        "invalid_source_ids": invalid,
        "duplicate_source_ids": sorted(set(duplicates)),
        "input_scores": rows,
        "weight_configuration": PROFILE_INPUT_WEIGHTS,
        "score_scale": {"minimum": PROFILE_SCORE_MIN, "maximum": PROFILE_SCORE_MAX},
        "model_note": (
            "Synthetic customer-profile inference over ten normalized source scores. "
            "Not an independently validated creditworthiness score."
        ),
    }

    if not complete:
        return {
            **common,
            "complex_customer_profile_score": None,
            "profile_band": "NOT_SCORED",
            "reason_codes": ["AIDFLOW_INPUT_COVERAGE_INCOMPLETE"],
        }

    # Map the weighted 0-100 profile signal onto the demo's 300-900 scale.
    profile_score = int(round(PROFILE_SCORE_MIN + weighted_total * 6.0))
    profile_score = max(PROFILE_SCORE_MIN, min(PROFILE_SCORE_MAX, profile_score))
    return {
        **common,
        "complex_customer_profile_score": profile_score,
        "weighted_profile_signal_0_100": round(weighted_total, 3),
        "profile_band": _profile_band(profile_score),
        "reason_codes": ["ALL_TEN_PROFILE_INPUTS_CONSUMED"],
    }
