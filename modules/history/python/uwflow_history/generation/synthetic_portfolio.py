"""Deterministic synthetic underwriting portfolio with point-in-time snapshots.

All provider snapshots are explicitly synthetic fixtures. They are generated
independently of a candidate's decision so baseline and candidate policies can
be evaluated on the same fixed evidence set. Real historical connectors must
store only observations that were actually collected and available at decision
time.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import math
import random
from typing import Iterator

from uwflow_history.contracts import DatasetManifest, HistoricalCase

GENERATOR_NAME = "uwflow-synthetic-portfolio"
GENERATOR_VERSION = "0.4.0"
SUPPORTED_TERMS = (12, 24, 36, 48, 60, 72, 84)
EMPLOYMENT_WEIGHTS = (
    ("FULL_TIME", 0.56),
    ("PART_TIME", 0.14),
    ("SELF_EMPLOYED", 0.15),
    ("FIXED_TERM", 0.10),
    ("UNEMPLOYED", 0.05),
)


def _rng(seed: int, index: int, namespace: str) -> random.Random:
    raw = f"{GENERATOR_NAME}|{GENERATOR_VERSION}|{seed}|{index}|{namespace}".encode()
    stable_seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(stable_seed)


def _application_id(seed: int, index: int) -> str:
    # IDs are deterministic, opaque to real identities, and lexically ordered
    # by row index. The stable order keeps content hashes identical across the
    # PostgreSQL and Parquet adapters without materializing the portfolio.
    seed_token = hashlib.sha256(str(seed).encode("ascii")).hexdigest()[:10].upper()
    return f"SYN-{seed_token}-{index:012d}"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _weighted_choice(rng: random.Random, values: tuple[tuple[str, float], ...]) -> str:
    draw = rng.random()
    cumulative = 0.0
    for value, weight in values:
        cumulative += weight
        if draw <= cumulative:
            return value
    return values[-1][0]


def _income_for(rng: random.Random, employment: str) -> float:
    median = {
        "FULL_TIME": 2450.0,
        "PART_TIME": 1420.0,
        "SELF_EMPLOYED": 2750.0,
        "FIXED_TERM": 2050.0,
        "UNEMPLOYED": 520.0,
    }[employment]
    sigma = 0.42 if employment == "SELF_EMPLOYED" else 0.32
    return round(max(250.0, min(12_000.0, rng.lognormvariate(math.log(median), sigma))), 2)


def _make_application(seed: int, index: int) -> tuple[dict, str]:
    rng = _rng(seed, index, "application")
    applicant_id = _application_id(seed, index)
    employment = _weighted_choice(rng, EMPLOYMENT_WEIGHTS)
    income = _income_for(rng, employment)
    age = max(18, min(75, round(rng.gauss(39, 11))))
    existing_debt = round(income * rng.uniform(0.02, 0.48), 2)
    housing = round(income * rng.uniform(0.16, 0.42), 2)
    requested = round(max(900.0, min(45_000.0, income * rng.uniform(2.2, 8.2))), 2)
    term = rng.choice(SUPPORTED_TERMS)
    consent = rng.random() < 0.88
    scenario = "GENERAL"

    # Deliberately include precise boundary cases for the current demo gates.
    # This is a test design feature, not a claim about a real portfolio mix.
    boundary_values = {
        1: ("AGE_BELOW_MINIMUM", {"applicant_age": 17}),
        2: ("AGE_AT_MINIMUM", {"applicant_age": 18}),
        3: ("AGE_AT_MAXIMUM", {"applicant_age": 75}),
        4: ("AGE_ABOVE_MAXIMUM", {"applicant_age": 76}),
        5: ("INCOME_BELOW_FLOOR", {"monthly_income": 655.53}),
        6: ("INCOME_AT_FLOOR", {"monthly_income": 655.54}),
        7: ("REQUEST_BELOW_FLOOR", {"requested_amount": 1229.12}),
        8: ("REQUEST_AT_FLOOR", {"requested_amount": 1229.13}),
        9: ("REQUEST_AT_CEILING", {"requested_amount": 40971.00}),
        10: ("REQUEST_ABOVE_CEILING", {"requested_amount": 40971.01}),
        11: ("TERM_BELOW_SET", {"loan_term_months": 11}),
        12: ("TERM_AT_MINIMUM", {"loan_term_months": 12}),
        13: ("TERM_AT_MAXIMUM", {"loan_term_months": 84}),
        14: ("TERM_ABOVE_SET", {"loan_term_months": 85}),
        15: ("UNEMPLOYED_STATUS", {"employment_status": "UNEMPLOYED"}),
    }
    boundary = boundary_values.get(index % 64)
    if boundary:
        scenario, overrides = boundary
        for field, value in overrides.items():
            if field == "employment_status":
                employment = value
            elif field == "monthly_income":
                income = value
            elif field == "requested_amount":
                requested = value
            elif field == "applicant_age":
                age = value
            elif field == "loan_term_months":
                term = value

    application = {
        "applicant_id": applicant_id,
        "applicant_name": f"Synthetic Applicant {index:07d}",
        "applicant_age": age,
        "monthly_income": income,
        "requested_amount": requested,
        "employment_status": employment,
        "existing_monthly_debt_payments": existing_debt,
        "monthly_housing_cost": housing,
        "loan_term_months": term,
        "data_sharing_consent": consent,
        "currency": "EUR",
    }
    return application, scenario


def _segment(value: float, cuts: tuple[float, ...], labels: tuple[str, ...]) -> str:
    for cut, label in zip(cuts, labels):
        if value < cut:
            return label
    return labels[-1]


def _latent_credit_risk(application: dict, seed: int, index: int) -> float:
    """Create a shared latent credit-risk propensity for correlated fixtures.

    This latent variable is used only by the synthetic data generator. It is
    never passed to UWflow/AIDflow as an application feature.
    """
    rng = _rng(seed, index, "latent-credit-risk")
    income = max(1.0, float(application["monthly_income"]))
    dti = float(application["existing_monthly_debt_payments"]) / income
    housing_ratio = float(application["monthly_housing_cost"]) / income
    employment_penalty = {
        "FULL_TIME": 0.0,
        "PART_TIME": 0.18,
        "SELF_EMPLOYED": 0.22,
        "FIXED_TERM": 0.34,
        "UNEMPLOYED": 0.65,
    }.get(str(application["employment_status"]), 0.25)
    linear = (
        -0.75
        + 2.15 * ((dti - 0.25) / 0.23)
        + 0.55 * ((housing_ratio - 0.28) / 0.14)
        + employment_penalty
        + rng.gauss(0.0, 0.48)
    )
    return 1.0 / (1.0 + math.exp(-max(-8.0, min(8.0, linear))))


def _correlate_bureau_snapshot(
    bureau: dict,
    application: dict,
    risk: float,
    seed: int,
    index: int,
) -> dict:
    """Shape the synthetic bureau profile around the shared latent risk."""
    rng = _rng(seed, index, "correlated-bureau")
    score = int(round(820.0 - 225.0 * risk + rng.gauss(0.0, 27.0)))
    score = max(350, min(850, score))

    draw = rng.random()
    p_two_or_more = 0.004 + 0.085 * risk
    p_one = 0.025 + 0.235 * risk
    if draw < p_two_or_more:
        delinquencies = 2 + int(rng.random() < 0.22 * risk)
    elif draw < p_two_or_more + p_one:
        delinquencies = 1
    else:
        delinquencies = 0

    public_records = int(rng.random() < (0.002 + 0.045 * risk))
    historical_defaults = 0
    default_draw = rng.random()
    if default_draw < 0.015 + 0.075 * risk:
        historical_defaults = 2 if rng.random() < 0.12 + 0.30 * risk else 1
    historical_delinquencies = min(6, max(0, int(round(rng.gauss(0.15 + 3.0 * risk, 0.8)))))
    utilization = round(max(0.02, min(0.98, 0.12 + 0.68 * risk + rng.gauss(0.0, 0.09))), 3)
    inquiries = max(0, min(8, int(round(rng.gauss(0.7 + 4.3 * risk, 1.05)))))
    open_loans = max(1, min(14, int(round(1.5 + 7.0 * risk + rng.gauss(0.0, 1.5)))))
    total_accounts = max(2, min(18, open_loans + rng.randint(1, 7)))
    accounts_good = max(
        0,
        min(
            total_accounts, int(round(total_accounts * (0.94 - 0.44 * risk + rng.gauss(0.0, 0.06))))
        ),
    )
    oldest_months = max(3, min(240, int(round(180 - 115 * risk + rng.gauss(0.0, 28)))))
    reported_debt = round(
        max(0.0, float(application["existing_monthly_debt_payments"]) * rng.uniform(0.96, 1.12)), 2
    )

    reasons: list[str] = []
    if public_records > 0:
        decision_status = "DECLINE"
        reasons.append("BUREAU_PUBLIC_RECORD")
    elif delinquencies >= 2 or historical_defaults >= 2 or score < 520:
        decision_status = "DECLINE"
        if delinquencies >= 2:
            reasons.append("MULTIPLE_ACTIVE_DELINQUENCIES")
        if historical_defaults >= 2:
            reasons.append("MULTIPLE_HISTORICAL_DEFAULTS")
        if score < 520:
            reasons.append("BUREAU_SCORE_BELOW_MINIMUM")
    elif (
        score < 640
        or delinquencies == 1
        or historical_defaults == 1
        or historical_delinquencies >= 3
        or utilization >= 0.88
        or inquiries >= 6
        or total_accounts < 4
    ):
        decision_status = "REFER"
        if score < 640:
            reasons.append("BUREAU_SCORE_REVIEW_BAND")
        if delinquencies == 1:
            reasons.append("ACTIVE_DELINQUENCY_REVIEW")
        if historical_defaults == 1:
            reasons.append("HISTORICAL_DEFAULT_REVIEW")
        if historical_delinquencies >= 3:
            reasons.append("HISTORICAL_DELINQUENCY_REVIEW")
        if utilization >= 0.88:
            reasons.append("HIGH_REVOLVING_UTILIZATION")
        if inquiries >= 6:
            reasons.append("HIGH_RECENT_CREDIT_SEEKING")
        if total_accounts < 4:
            reasons.append("THIN_CREDIT_FILE_REVIEW")
    else:
        decision_status = "PASS"
        reasons.append("BUREAU_WITHIN_DEMO_POLICY")

    return {
        **bureau,
        "decision_status": decision_status,
        "passed": decision_status == "PASS",
        "bureau_score": score,
        "active_delinquencies": delinquencies,
        "public_records": public_records,
        "revolving_utilization": utilization,
        "recent_inquiries_6m": inquiries,
        "oldest_account_months": oldest_months,
        "accounts_in_good_standing": accounts_good,
        "total_open_accounts": total_accounts,
        "open_loans": open_loans,
        "historical_defaults_5y": historical_defaults,
        "historical_delinquencies_24m": historical_delinquencies,
        "reported_monthly_debt_payments": reported_debt,
        "reason_codes": reasons,
        "synthetic_profile_semantics": "CORRELATED_LATENT_CREDIT_RISK_FIXTURE",
    }


def _correlate_source_snapshot(
    snapshot: dict,
    risk: float,
    fraud_risk: float,
    seed: int,
    index: int,
) -> dict:
    """Make each synthetic source informative and correlated by role."""
    source_id = str(snapshot["source_id"])
    rng = _rng(seed, index, f"correlated-source:{source_id}")
    credit_signal = 0.0
    metrics = dict(snapshot.get("metrics") or {})

    if source_id in {"telco_stability", "utility_reliability"}:
        on_time = max(2, min(12, int(round(12 - 7.0 * risk + rng.gauss(0.0, 1.15)))))
        metrics.update(
            {
                "months_observed": 12,
                "on_time_payments": on_time,
                "late_payments": 12 - on_time,
            }
        )
        credit_signal = 48.0 + (on_time / 12.0) * 52.0
    elif source_id == "open_banking_cashflow":
        volatility = max(0.025, min(0.55, 0.035 + 0.27 * risk + rng.gauss(0.0, 0.035)))
        returned_debits = min(5, max(0, int(round(rng.gauss(0.1 + 2.0 * risk, 0.65)))))
        regular_inflows = max(2, min(6, int(round(6 - 3.0 * risk + rng.gauss(0.0, 0.65)))))
        income = float(snapshot.get("metrics", {}).get("average_monthly_income_inflow", 0.0))
        metrics.update(
            {
                "months_observed": 6,
                "regular_income_inflows": regular_inflows,
                "average_monthly_income_inflow": round(income * (1.02 - 0.18 * risk), 2),
                "income_volatility_coefficient": round(volatility, 3),
                "returned_debits_6m": returned_debits,
            }
        )
        credit_signal = (
            98.0 - volatility * 125.0 - returned_debits * 4.5 + (regular_inflows - 5) * 2.0
        )
    elif source_id == "income_velocity":
        volatility = max(0.02, min(0.5, 0.025 + 0.28 * risk + rng.gauss(0.0, 0.035)))
        trend = max(-0.35, min(0.18, 0.08 - 0.34 * risk + rng.gauss(0.0, 0.045)))
        observed = max(2, min(6, int(round(6 - 2.8 * risk + rng.gauss(0.0, 0.6)))))
        metrics.update(
            {
                "months_observed": observed,
                "income_volatility_coefficient": round(volatility, 3),
                "income_trend_6m_pct": round(trend, 3),
            }
        )
        credit_signal = 98.0 - volatility * 110.0 + trend * 32.0 + (observed - 5) * 1.5
    elif source_id == "microloan_history":
        total = max(1, min(12, int(round(2 + 7 * risk + rng.gauss(0.0, 1.5)))))
        on_time_ratio = max(0.35, min(1.0, 0.99 - 0.42 * risk + rng.gauss(0.0, 0.07)))
        on_time = max(0, min(total, int(round(total * on_time_ratio))))
        overdue = int(rng.random() < (0.015 + 0.34 * risk))
        metrics.update(
            {
                "facilities_observed": total,
                "repaid_on_time": on_time,
                "currently_overdue": overdue,
                "historical_defaults": int(rng.random() < (0.01 + 0.16 * risk)),
            }
        )
        credit_signal = 45.0 + 55.0 * (on_time / total) - 18.0 * overdue
    elif source_id == "merchant_affinity":
        concentration = max(0.08, min(0.95, 0.16 + 0.62 * risk + rng.gauss(0.0, 0.09)))
        metrics.update(
            {
                "merchant_concentration_index": round(concentration, 3),
                "data_purpose": "SYNTHETIC_BEHAVIOURAL_CONTEXT_SIGNAL_CONSUMED_BY_AIDFLOW",
            }
        )
        credit_signal = 99.0 - concentration * 58.0
    elif source_id in {
        "device_fingerprint",
        "geo_mobility",
        "ecommerce_behavior",
        "digital_identity_age",
    }:
        adjusted_fraud = max(0.0, min(1.0, fraud_risk + rng.gauss(0.0, 0.08)))
        if source_id == "device_fingerprint":
            probabilities = [
                1.0 - 0.30 * adjusted_fraud,
                0.25 * adjusted_fraud,
                0.05 * adjusted_fraud,
            ]
            risk_level = rng.choices(["CLEAR", "REVIEW", "ALERT"], weights=probabilities, k=1)[0]
            metrics.update(
                {
                    "device_reputation": "KNOWN_GOOD" if risk_level == "CLEAR" else "NEW_DEVICE",
                    "emulator_detected": risk_level == "ALERT" and rng.random() < 0.35,
                    "ip_proxy_indicator": risk_level == "ALERT" and rng.random() < 0.45,
                }
            )
        elif source_id == "geo_mobility":
            risk_level = rng.choices(
                ["CLEAR", "REVIEW"],
                weights=[1.0 - 0.30 * adjusted_fraud, 0.30 * adjusted_fraud],
                k=1,
            )[0]
            metrics.update(
                {
                    "session_continuity": "CONSISTENT" if risk_level == "CLEAR" else "INCONSISTENT",
                    "impossible_travel_flag": False,
                }
            )
        elif source_id == "ecommerce_behavior":
            risk_level = rng.choices(
                ["CLEAR", "REVIEW"],
                weights=[1.0 - 0.28 * adjusted_fraud, 0.28 * adjusted_fraud],
                k=1,
            )[0]
            metrics.update(
                {
                    "payment_dispute_pattern": "NORMAL"
                    if risk_level == "CLEAR"
                    else "REVIEW_REQUIRED",
                    "account_takeover_indicator": False,
                }
            )
        else:
            risk_level = rng.choices(
                ["CLEAR", "REVIEW"],
                weights=[1.0 - 0.22 * adjusted_fraud, 0.22 * adjusted_fraud],
                k=1,
            )[0]
            metrics.update(
                {
                    "identity_status": "VERIFIED" if risk_level == "CLEAR" else "REVIEW",
                    "document_verification": "PASSED"
                    if risk_level == "CLEAR"
                    else "MANUAL_CHECK_REQUIRED",
                    "liveness_check": "PASSED" if risk_level == "CLEAR" else "REVIEW",
                }
            )
        credit_signal = {"CLEAR": 96.0, "REVIEW": 52.0, "ALERT": 12.0}[risk_level]
        snapshot["risk_level"] = risk_level
        snapshot["reason_codes"] = [f"{source_id.upper()}_{risk_level}"]
    else:
        raise ValueError(f"No correlated synthetic generator for source {source_id}")

    score = round(max(0.0, min(100.0, credit_signal + rng.gauss(0.0, 2.0))), 1)
    snapshot["profile_input_score"] = score
    snapshot["profile_input_scale"] = "0-100_HIGHER_IS_STRONGER"
    if "signal_score" in snapshot:
        snapshot["signal_score"] = score
    snapshot["metrics"] = metrics
    snapshot["synthetic_signal_semantics"] = "CORRELATED_LATENT_CREDIT_AND_FRAUD_RISK_FIXTURE"
    return snapshot


def _outcome_snapshot(
    application: dict,
    bureau: dict,
    decision_timestamp: datetime,
    as_of: datetime,
    seed: int,
    index: int,
    latent_risk: float,
) -> dict:
    rng = _rng(seed, index, "fstpd30-outcome")
    income = max(1.0, float(application["monthly_income"]))
    dti = float(application["existing_monthly_debt_payments"]) / income
    historical_defaults = float(bureau.get("historical_defaults_5y") or 0)
    historical_delinquencies = float(bureau.get("historical_delinquencies_24m") or 0)
    # A deliberately transparent, illustrative hazard model. The target is
    # generated from shared latent risk plus observable affordability and bureau
    # history; it is not a calibrated PD model or observed booked-loan outcome.
    logit = (
        -4.05
        + 4.65 * latent_risk
        + 0.30 * historical_defaults
        + 0.055 * historical_delinquencies
        + 0.55 * max(0.0, (dti - 0.30) / 0.18)
    )
    fstpd30_probability = 1.0 / (1.0 + math.exp(-max(-12.0, min(12.0, logit))))
    fstpd30_probability = max(0.002, min(0.65, fstpd30_probability))

    months_on_book = max(0, int((as_of - decision_timestamp).days // 30.4375))
    # Third instalment plus a 30-day delinquency window must have elapsed.
    matured = months_on_book >= 4
    payment_dpd: list[int | None] = [None, None, None]
    fstpd30: int | None = None
    if matured:
        monthly_hazard = 1.0 - (1.0 - fstpd30_probability) ** (1.0 / 3.0)
        for payment_index in range(3):
            if rng.random() < monthly_hazard:
                payment_dpd[payment_index] = rng.choice([30, 35, 45, 60, 90])
            else:
                payment_dpd[payment_index] = rng.choices(
                    [0, 1, 7, 15, 29], weights=[0.70, 0.06, 0.10, 0.08, 0.06], k=1
                )[0]
        fstpd30 = int(any(value is not None and value >= 30 for value in payment_dpd))

    withdrawal_rng = _rng(seed, index, "application-withdrawal")
    withdrawal_probability = 0.012 + 0.035 * latent_risk
    withdrawal_stage = None
    if withdrawal_rng.random() < withdrawal_probability:
        withdrawal_stage = withdrawal_rng.choices(
            [
                "STAGE_2_BUREAU",
                "STAGE_3_SOURCE_PLAN",
                "STAGE_4_DATA_COLLECTION",
                "STAGE_5_AIDFLOW",
                "STAGE_6_UWFLOW",
            ],
            weights=[0.18, 0.24, 0.27, 0.16, 0.15],
            k=1,
        )[0]

    return {
        "outcome_id": f"SYN-OUT-{application['applicant_id']}-FSTPD30",
        "outcome_definition": "FSTPD30: 1 if any of the first, second or third scheduled instalments reaches 30+ days past due; otherwise 0",
        "target_name": "FSTPD30",
        "FSTPD30": fstpd30,
        "first_payment_days_past_due": payment_dpd[0],
        "second_payment_days_past_due": payment_dpd[1],
        "third_payment_days_past_due": payment_dpd[2],
        "fstpd30_event_payment_number": (
            next(
                (i + 1 for i, value in enumerate(payment_dpd) if value is not None and value >= 30),
                None,
            )
        ),
        "fstpd30_probability_for_simulation": round(fstpd30_probability, 6),
        "label_type": "SYNTHETIC_COUNTERFACTUAL_FSTPD30_NOT_BOOKED_LOAN_PERFORMANCE",
        "observed_at": _iso(as_of),
        "months_on_book": months_on_book,
        "observation_window_months": 4,
        "maturity_rule": "Third scheduled instalment plus 30-day delinquency observation window",
        "outcome_status": "MATURED" if matured else "IMMATURE",
        "synthetic_withdrawal_stage": withdrawal_stage,
        "synthetic_only": True,
    }


def generate_cases(
    *,
    count: int,
    seed: int,
    as_of_date: date,
    history_months: int = 36,
) -> Iterator[HistoricalCase]:
    """Yield a stable synthetic portfolio in application-ID order."""
    if count < 1:
        raise ValueError("count must be at least 1")
    if history_months < 12:
        raise ValueError("history_months must be at least 12 to include matured outcomes")

    # Runtime imports are local so this package remains a separate connector
    # layer and does not acquire hidden coupling at importtime.
    from alternative_data import SOURCE_IDS, get_alternative_data
    from bureau_client import get_bureau_data

    as_of = datetime.combine(as_of_date, time(23, 59, 59), tzinfo=timezone.utc)
    earliest = as_of - timedelta(days=int(history_months * 30.4375))
    latest_application = as_of - timedelta(minutes=90)
    span_seconds = max(1, int((latest_application - earliest).total_seconds()))

    for index in range(1, count + 1):
        application, scenario = _make_application(seed, index)
        rng = _rng(seed, index, "timestamps")
        application_ts = earliest + timedelta(seconds=rng.randrange(span_seconds))
        decision_ts = application_ts + timedelta(minutes=rng.randint(5, 90))
        application_ts_text = _iso(application_ts)
        decision_ts_text = _iso(decision_ts)

        # Generate a complete synthetic provider fixture independently of the
        # baseline's original route. A policy candidate can then be compared on
        # the same consented fixture. Real connectors must not invent missing
        # snapshots: they return only observations actually collected.
        latent_risk = _latent_credit_risk(application, seed, index)
        fraud_risk = max(
            0.0,
            min(
                1.0,
                0.12 + 0.38 * latent_risk + _rng(seed, index, "fraud-propensity").gauss(0.0, 0.12),
            ),
        )
        bureau = get_bureau_data(
            application["applicant_id"],
            application["existing_monthly_debt_payments"],
            {"passed": True},
        )
        bureau = _correlate_bureau_snapshot(bureau, application, latent_risk, seed, index)
        bureau["retrieved_at"] = decision_ts_text
        bureau["snapshot_id"] = f"BUR-{application['applicant_id']}"
        bureau["fixture_semantics"] = "SYNTHETIC_FIXTURE_AVAILABLE_AT_DECISION"

        source_snapshots: list[dict] = []
        if application["data_sharing_consent"]:
            for source_id in SOURCE_IDS:
                snapshot = get_alternative_data(source_id, application["applicant_id"], application)
                snapshot = _correlate_source_snapshot(
                    snapshot, latent_risk, fraud_risk, seed, index
                )
                snapshot["retrieved_at"] = decision_ts_text
                snapshot["snapshot_id"] = f"SRC-{source_id}-{application['applicant_id']}"
                snapshot["fixture_semantics"] = "SYNTHETIC_CONSENTED_FIXTURE_AVAILABILITY"
                source_snapshots.append(snapshot)

        outcome = _outcome_snapshot(
            application, bureau, decision_ts, as_of, seed, index, latent_risk
        )
        income = float(application["monthly_income"])
        bureau_score = float(bureau.get("bureau_score") or 0)
        month_label = application_ts.strftime("%Y-%m")
        segments = {
            "income_band": _segment(
                income, (1000, 2000, 3500), ("LT_1000", "1000_1999", "2000_3499", "GE_3500")
            ),
            "age_band": _segment(
                float(application["applicant_age"]),
                (25, 35, 50),
                ("18_24", "25_34", "35_49", "50_PLUS"),
            ),
            "employment_status": str(application["employment_status"]),
            "bureau_band": _segment(
                bureau_score, (600, 640, 700), ("LT_600", "600_639", "640_699", "GE_700")
            ),
            "bureau_historical_defaults": str(bureau.get("historical_defaults_5y", 0)),
            "bureau_historical_delinquencies": _segment(
                float(bureau.get("historical_delinquencies_24m", 0)),
                (1, 3, 5),
                ("NONE", "LOW", "MODERATE", "HIGH"),
            ),
            "open_loan_band": _segment(
                float(bureau.get("open_loans", 0)), (3, 6, 9), ("1_2", "3_5", "6_8", "9_PLUS")
            ),
            "application_vintage": month_label[:4]
            + "Q"
            + str((int(month_label[5:7]) - 1) // 3 + 1),
            "boundary_scenario": scenario,
        }
        yield HistoricalCase(
            application_id=str(application["applicant_id"]),
            application_snapshot_id=f"APP-{application['applicant_id']}-V1",
            application_timestamp=application_ts_text,
            decision_timestamp=decision_ts_text,
            application=application,
            bureau_snapshot=bureau,
            alternative_data_snapshots=tuple(source_snapshots),
            outcome_snapshot=outcome,
            segments=segments,
        )


def build_manifest(
    *,
    dataset_id: str,
    count: int,
    seed: int,
    as_of_date: date,
    history_months: int = 36,
) -> DatasetManifest:
    """Build the reproducible manifest describing a generated synthetic portfolio."""
    as_of = datetime.combine(as_of_date, time(23, 59, 59), tzinfo=timezone.utc)
    start = as_of - timedelta(days=int(history_months * 30.4375))
    return DatasetManifest(
        dataset_id=dataset_id,
        display_name=f"Synthetic EUR underwriting portfolio ({count:,} applications)",
        case_count=count,
        created_at=_iso(datetime.now(timezone.utc)),
        as_of_timestamp=_iso(as_of),
        history_start=_iso(start),
        history_end=_iso(as_of),
        synthetic=True,
        source_snapshot_semantics="SYNTHETIC_CONSENTED_FIXTURE_AVAILABILITY",
        outcome_definition=(
            "FSTPD30: binary 1 if any first/second/third scheduled instalment reaches 30+ DPD; "
            "0 otherwise; null until the third instalment plus 30-day observation window matures. "
            "Synthetic counterfactual label, not observed performance on a booked loan."
        ),
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        seed=seed,
        metadata={
            "currency": "EUR",
            "history_months": history_months,
            "application_generator": "correlated demo distribution; deterministic per seed and row",
            "target_name": "FSTPD30",
            "target_definition": "1 if any of the first three scheduled instalments reaches 30+ days past due; 0 otherwise; null before maturity",
            "target_maturity_months": 4,
            "provider_fixtures": "synthetic bureau plus up to ten consented alternative-data source fixtures correlated through a shared latent credit-risk propensity",
            "source_snapshot_semantics": (
                "Fixtures are created independently of baseline routing for controlled policy sensitivity tests. "
                "They are not representations of data actually collected in a real historical portfolio."
            ),
            "outcome_model": (
                "Illustrative synthetic FSTPD30 payment-level outcome generated from a shared latent credit-risk "
                "propensity, affordability, bureau historical defaults and delinquencies. The first three payment "
                "DPD values are retained; target matures after the third instalment plus 30 days. Not calibrated "
                "and not observed performance on loans actually booked."
            ),
            "correlation_design": (
                "A shared latent credit-risk propensity drives bureau score, active/historical delinquency, "
                "historical defaults, open-loan counts, utilization and six alternative-data credit signals. "
                "Identity/fraud signals use a related but separate propensity. Higher adverse bureau history "
                "is intentionally associated with higher FSTPD30 incidence."
            ),
            "boundary_scenarios": "Targeted cases around the current demo hard-gate boundaries are interleaved.",
            "contains_personal_data": False,
            "outcomes_are_counterfactual": True,
            "workflow_cancellations": "Small, deterministic synthetic withdrawal events are recorded before stages 2-6 for funnel reporting; not a credit-risk label.",
            "outcome_warning": (
                "Synthetic labels are generated for all applicants, including applicants not offered or booked. "
                "They are suitable for software-path demonstrations only, not portfolio performance estimates."
            ),
        },
    )


def default_dataset_id(*, count: int, seed: int, as_of_date: date) -> str:
    """Return the deterministic dataset identifier for the configured synthetic portfolio."""
    return f"synthetic-eur-v4-fstpd30-seed-{seed}-n-{count}-asof-{as_of_date:%Y%m%d}"
