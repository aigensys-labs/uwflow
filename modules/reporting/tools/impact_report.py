"""Champion-versus-challenger portfolio impact metrics and analyst reports.

The module is presentation and aggregation only. It does not modify underwriting
policy, recalculate applicant scores, or infer outcomes that are not present in
the immutable historical snapshot.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from reportlab.lib.enums import TA_LEFT
from statistics import mean
from typing import Any

SOURCE_IDS: tuple[str, ...] = (
    "telco_stability",
    "utility_reliability",
    "open_banking_cashflow",
    "device_fingerprint",
    "geo_mobility",
    "ecommerce_behavior",
    "digital_identity_age",
    "income_velocity",
    "microloan_history",
    "merchant_affinity",
)

STAGE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "stage1_hard_gates",
        "name": "Stage 1 - Input validation & hard gates",
        "positive": ("PASSED",),
        "outcomes": ("PASSED", "REJECTED", "REFERRED", "CANCELLED", "NOT_REACHED"),
        "rate_label": "Gate clearance rate",
        "risk_label": "FSTPD30 among gate-cleared cases",
        "description": "Application completeness, product eligibility and non-scorecard hard rules.",
    },
    {
        "id": "stage2_bureau",
        "name": "Stage 2 - Credit bureau policy",
        "positive": ("PASSED",),
        "outcomes": ("PASSED", "REJECTED", "REFERRED", "CANCELLED", "NOT_REACHED"),
        "rate_label": "Bureau clearance rate",
        "risk_label": "FSTPD30 among bureau-cleared cases",
        "description": "Current bureau decision, historical defaults, delinquencies and credit-file profile.",
    },
    {
        "id": "stage3_source_plan",
        "name": "Stage 3 - Consent & source plan",
        "positive": ("ROUTED_TO_COLLECTION",),
        "outcomes": ("ROUTED_TO_COLLECTION", "SKIPPED_NO_CONSENT", "CANCELLED", "NOT_REACHED"),
        "rate_label": "Source-collection routing rate",
        "risk_label": "FSTPD30 among source-routed cases",
        "description": "Determines whether the ten consented alternative-data sources may be collected.",
    },
    {
        "id": "stage4_data_collection",
        "name": "Stage 4 - Big-data source collection",
        "positive": ("COMPLETE",),
        "outcomes": (
            "COMPLETE",
            "PARTIAL",
            "FAILED",
            "SKIPPED_NO_CONSENT",
            "CANCELLED",
            "NOT_REACHED",
        ),
        "rate_label": "Ten-source completion rate",
        "risk_label": "FSTPD30 among complete-source cases",
        "description": "Collection coverage across all ten source adapters; partial and missing sources remain visible.",
    },
    {
        "id": "stage5_aidflow",
        "name": "Stage 5 - AIDflow profile inference",
        "positive": ("SCORED",),
        "outcomes": ("SCORED", "INCOMPLETE", "CANCELLED", "NOT_REACHED"),
        "rate_label": "Complete AIDflow scoring rate",
        "risk_label": "FSTPD30 among scored cases",
        "description": "One customer-profile score inferred from the ten normalized source inputs.",
    },
    {
        "id": "stage6_uwflow",
        "name": "Stage 6 - UWflow decision, affordability & pricing",
        "positive": ("APPROVED", "COUNTEROFFER"),
        "outcomes": (
            "APPROVED",
            "COUNTEROFFER",
            "REFERRED",
            "REJECTED",
            "CANCELLED",
            "NOT_REACHED",
        ),
        "rate_label": "Offer rate (approved + counteroffer)",
        "risk_label": "FSTPD30 among approved cases",
        "description": "Final credit decision, affordability checks, pricing and approved amount.",
    },
)


def _target_value(row: dict[str, Any]) -> int | None:
    outcome = row.get("outcome") or {}
    if outcome.get("outcome_status") != "MATURED":
        return None
    value = outcome.get("FSTPD30")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    return None


def _decision(row: dict[str, Any]) -> str:
    value = str(row.get("decision") or "NO_DECISION").upper()
    return {"REFERRED": "REFER", "REJECTED": "DECLINED"}.get(value, value)


def _stage_status(row: dict[str, Any], stage_id: str) -> tuple[str, bool]:
    entry = (row.get("stage_results") or {}).get(stage_id) or {}
    outcome = str(entry.get("outcome") or "NOT_REACHED")
    reached = bool(entry.get("reached", outcome != "NOT_REACHED"))
    return outcome, reached


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _stage_metrics(rows: list[dict[str, Any]], definition: dict[str, Any]) -> dict[str, Any]:
    total = len(rows)
    counts: Counter[str] = Counter()
    reached = 0
    entered_rows: list[dict[str, Any]] = []
    positive_rows: list[dict[str, Any]] = []
    for row in rows:
        status, was_reached = _stage_status(row, definition["id"])
        counts[status] += 1
        reached += int(was_reached)
        if was_reached:
            entered_rows.append(row)
        if status in definition["positive"]:
            positive_rows.append(row)

    # Include every defined status, even when the count is zero. CRO readers can
    # distinguish a genuine zero from an outcome that was accidentally omitted.
    ordered_counts = {status: counts.get(status, 0) for status in definition["outcomes"]}
    distribution = {status: _rate(count, total) for status, count in ordered_counts.items()}
    is_final_decision_stage = definition["id"] == "stage6_uwflow"
    # For the final credit-decision stage, risk must use the same strict
    # APPROVED-only population as the headline approval rate. Counteroffers
    # remain in the separate offer-risk metric at portfolio level.
    risk_rows = (
        [row for row in rows if _stage_status(row, definition["id"])[0] == "APPROVED"]
        if is_final_decision_stage
        else positive_rows
    )
    matured = [row for row in risk_rows if _target_value(row) is not None]
    events = sum(_target_value(row) or 0 for row in matured)
    approvals = counts.get("APPROVED", 0)
    final_approved_entrants = sum(1 for row in entered_rows if _decision(row) == "APPROVED")
    return {
        "cohort_count": total,
        "entered_count": reached,
        "not_reached_count": counts.get("NOT_REACHED", 0),
        "positive_outcome": list(definition["positive"]),
        "positive_count": len(positive_rows),
        "progression_rate": _rate(len(positive_rows), reached),
        "final_approval_count_of_entrants": final_approved_entrants,
        "final_approval_rate_of_entrants": _rate(final_approved_entrants, reached),
        "strict_approval_count": approvals if is_final_decision_stage else None,
        "strict_approval_rate": _rate(approvals, reached) if is_final_decision_stage else None,
        "progression_rate_numerator": len(positive_rows),
        "progression_rate_denominator": reached,
        "outcome_counts": ordered_counts,
        # Population share uses the full original cohort, including cases not
        # reaching a stage. Entry distribution conditions only on stage entrants.
        "outcome_distribution": distribution,
        "outcome_distribution_of_entered": {
            status: (_rate(count, reached) if status != "NOT_REACHED" else None)
            for status, count in ordered_counts.items()
        },
        "FSTPD30_risk_population": "APPROVED_ONLY"
        if is_final_decision_stage
        else "STAGE_POSITIVE_OUTCOMES",
        "FSTPD30_events": events,
        "FSTPD30_labelled_positive_cases": len(matured),
        "FSTPD30_risk_population_count": len(risk_rows),
        "FSTPD30_unmatured_risk_cases": len(risk_rows) - len(matured),
        "FSTPD30_rate": _rate(events, len(matured)),
        "FSTPD30_coverage": _rate(len(matured), len(risk_rows)),
    }


def _portfolio_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    decisions = Counter(_decision(row) for row in rows)
    approved = decisions.get("APPROVED", 0)
    counteroffers = decisions.get("COUNTEROFFER", 0)
    approved_rows = [row for row in rows if _decision(row) == "APPROVED"]
    offered_rows = [row for row in rows if _decision(row) in {"APPROVED", "COUNTEROFFER"}]
    matured_approved = [row for row in approved_rows if _target_value(row) is not None]
    approved_events = sum(_target_value(row) or 0 for row in matured_approved)
    matured_offers = [row for row in offered_rows if _target_value(row) is not None]
    fstpd30_events = sum(_target_value(row) or 0 for row in matured_offers)
    matured_all = [row for row in rows if _target_value(row) is not None]
    fstpd30_all = sum(_target_value(row) or 0 for row in matured_all)
    amounts = [float(row.get("approved_amount") or 0.0) for row in offered_rows]
    return {
        "application_count": total,
        "decision_counts": {
            "APPROVED": approved,
            "COUNTEROFFER": counteroffers,
            "REFERRED": decisions.get("REFER", 0),
            "REJECTED": decisions.get("DECLINED", 0),
            "CANCELLED": decisions.get("CANCELLED", 0),
            "OTHER": total
            - sum(
                decisions.get(key, 0)
                for key in ("APPROVED", "COUNTEROFFER", "REFER", "DECLINED", "CANCELLED")
            ),
        },
        "strict_approval_count": approved,
        "strict_approval_rate": _rate(approved, total),
        "FSTPD30_events_on_approved": approved_events,
        "FSTPD30_labelled_approved": len(matured_approved),
        "FSTPD30_unmatured_approved": len(approved_rows) - len(matured_approved),
        "FSTPD30_rate_on_approved": _rate(approved_events, len(matured_approved)),
        "FSTPD30_approved_label_coverage": _rate(len(matured_approved), len(approved_rows)),
        "offer_count": len(offered_rows),
        "offer_rate": _rate(len(offered_rows), total),
        "counteroffer_rate": _rate(counteroffers, total),
        "referral_rate": _rate(decisions.get("REFER", 0), total),
        "rejection_rate": _rate(decisions.get("DECLINED", 0), total),
        "cancellation_rate": _rate(decisions.get("CANCELLED", 0), total),
        "FSTPD30_events_on_offers": fstpd30_events,
        "FSTPD30_labelled_offers": len(matured_offers),
        "FSTPD30_unmatured_offers": len(offered_rows) - len(matured_offers),
        "FSTPD30_rate_on_offers": _rate(fstpd30_events, len(matured_offers)),
        "FSTPD30_offer_label_coverage": _rate(len(matured_offers), len(offered_rows)),
        "FSTPD30_all_matured_events": fstpd30_all,
        "FSTPD30_all_matured_cases": len(matured_all),
        "FSTPD30_all_matured_rate": _rate(fstpd30_all, len(matured_all)),
        "FSTPD30_cohort_maturity_coverage": _rate(len(matured_all), total),
        "total_offered_amount": round(sum(amounts), 2),
        "mean_offered_amount": round(mean(amounts), 2) if amounts else None,
    }


def _score_deciles(rows: list[dict[str, Any]], policy_name: str) -> list[dict[str, Any]]:
    scored = [row for row in rows if isinstance(row.get("profile_score"), (int, float))]
    scored.sort(key=lambda row: (float(row["profile_score"]), str(row.get("application_id"))))
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    count = len(scored)
    for index, row in enumerate(scored):
        decile = min(10, (index * 10 // max(1, count)) + 1)
        groups[decile].append(row)

    result: list[dict[str, Any]] = []
    for decile in range(1, 11):
        group = groups.get(decile, [])
        targets = [_target_value(row) for row in group]
        labelled = [value for value in targets if value is not None]
        approved = [row for row in group if _decision(row) == "APPROVED"]
        offered = [row for row in group if _decision(row) in {"APPROVED", "COUNTEROFFER"}]
        approved_targets = [_target_value(row) for row in approved]
        approved_labelled = [value for value in approved_targets if value is not None]
        offered_targets = [_target_value(row) for row in offered]
        offered_labelled = [value for value in offered_targets if value is not None]
        result.append(
            {
                "policy": policy_name,
                "decile": decile,
                "interpretation": "Lowest AIDflow profile scores"
                if decile == 1
                else "Highest AIDflow profile scores"
                if decile == 10
                else "Intermediate AIDflow profile scores",
                "case_count": len(group),
                "score_min": min((float(row["profile_score"]) for row in group), default=None),
                "score_max": max((float(row["profile_score"]) for row in group), default=None),
                "approval_count": len(approved),
                "approval_rate": _rate(len(approved), len(group)),
                "offer_count": len(offered),
                "offer_rate": _rate(len(offered), len(group)),
                "FSTPD30_events_all": sum(labelled),
                "FSTPD30_labelled_all": len(labelled),
                "FSTPD30_rate_all": _rate(sum(labelled), len(labelled)),
                "FSTPD30_events_approved": sum(approved_labelled),
                "FSTPD30_labelled_approved": len(approved_labelled),
                "FSTPD30_rate_approved": _rate(sum(approved_labelled), len(approved_labelled)),
                "FSTPD30_events_offered": sum(offered_labelled),
                "FSTPD30_labelled_offered": len(offered_labelled),
                "FSTPD30_rate_offered": _rate(sum(offered_labelled), len(offered_labelled)),
            }
        )
    return result


def _segment_analysis(rows: list[dict[str, Any]], policy_name: str) -> list[dict[str, Any]]:
    segment_keys = (
        "bureau_band",
        "bureau_historical_defaults",
        "bureau_historical_delinquencies",
        "open_loan_band",
        "income_band",
        "employment_status",
        "age_band",
    )
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for key in segment_keys:
            value = (row.get("segments") or {}).get(key)
            if value is not None:
                groups[(key, str(value))].append(row)
    result: list[dict[str, Any]] = []
    for (key, value), group in sorted(groups.items()):
        approved = [row for row in group if _decision(row) == "APPROVED"]
        offered = [row for row in group if _decision(row) in {"APPROVED", "COUNTEROFFER"}]
        approved_targets = [_target_value(row) for row in approved]
        approved_labelled = [target for target in approved_targets if target is not None]
        offered_targets = [_target_value(row) for row in offered]
        offered_labelled = [target for target in offered_targets if target is not None]
        result.append(
            {
                "policy": policy_name,
                "segment": key,
                "value": value,
                "case_count": len(group),
                "approval_count": len(approved),
                "approval_rate": _rate(len(approved), len(group)),
                "offer_count": len(offered),
                "offer_rate": _rate(len(offered), len(group)),
                "FSTPD30_events_approved": sum(approved_labelled),
                "FSTPD30_labelled_approved": len(approved_labelled),
                "FSTPD30_rate_on_approved": _rate(sum(approved_labelled), len(approved_labelled)),
                "FSTPD30_events_offered": sum(offered_labelled),
                "FSTPD30_labelled_offers": len(offered_labelled),
                "FSTPD30_rate_on_offers": _rate(sum(offered_labelled), len(offered_labelled)),
            }
        )
    return result


def _source_coverage(rows: list[dict[str, Any]], policy_name: str) -> list[dict[str, Any]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    eligible = 0
    for row in rows:
        stage3, _ = _stage_status(row, "stage3_source_plan")
        if stage3 != "ROUTED_TO_COLLECTION":
            continue
        eligible += 1
        stage4, _ = _stage_status(row, "stage4_data_collection")
        source_outcomes = (
            (row.get("stage_results") or {}).get("stage4_data_collection") or {}
        ).get("source_outcomes") or {}
        for source_id in SOURCE_IDS:
            if source_id in source_outcomes:
                counts[source_id][str(source_outcomes[source_id])] += 1
            elif stage4 == "CANCELLED" or stage4 == "NOT_REACHED":
                counts[source_id]["NOT_ATTEMPTED"] += 1
            else:
                counts[source_id]["MISSING"] += 1
    return [
        {
            "policy": policy_name,
            "source_id": source_id,
            "eligible_cases": eligible,
            "successful": counts[source_id].get("SUCCESS", 0),
            "failed": counts[source_id].get("FAILED", 0),
            "missing": counts[source_id].get("MISSING", 0),
            "not_attempted": counts[source_id].get("NOT_ATTEMPTED", 0),
            "coverage_rate": _rate(counts[source_id].get("SUCCESS", 0), eligible),
        }
        for source_id in SOURCE_IDS
    ]


def build_impact_analysis(
    baseline_rows: list[dict[str, Any]],
    challenger_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build full funnel, approval, FSTPD30 and segment comparison metrics."""
    champion = _portfolio_metrics(baseline_rows)
    challenger = _portfolio_metrics(challenger_rows)
    delta = {
        "strict_approval_rate_pp": _pp_delta(
            challenger["strict_approval_rate"], champion["strict_approval_rate"]
        ),
        "offer_rate_pp": _pp_delta(challenger["offer_rate"], champion["offer_rate"]),
        "FSTPD30_rate_on_offers_pp": _pp_delta(
            challenger["FSTPD30_rate_on_offers"], champion["FSTPD30_rate_on_offers"]
        ),
        "FSTPD30_rate_on_approved_pp": _pp_delta(
            challenger["FSTPD30_rate_on_approved"], champion["FSTPD30_rate_on_approved"]
        ),
        "FSTPD30_all_matured_rate_pp": _pp_delta(
            challenger["FSTPD30_all_matured_rate"], champion["FSTPD30_all_matured_rate"]
        ),
        "total_offered_amount": round(
            challenger["total_offered_amount"] - champion["total_offered_amount"], 2
        ),
    }
    if (
        champion["FSTPD30_rate_on_approved"] is None
        or challenger["FSTPD30_rate_on_approved"] is None
    ):
        assessment = "INSUFFICIENT_MATURED_APPROVED_LABELS"
    else:
        # Keep the primary AR/DR comparison denominator-consistent: APPROVED-only
        # approvals against FSTPD30 incidence among those same approved cases.
        # COUNTEROFFER and its risk remain visible as a separate commercial funnel view.
        ar_delta = delta["strict_approval_rate_pp"]
        dr_delta = delta["FSTPD30_rate_on_approved_pp"]
        if ar_delta is not None and dr_delta is not None and ar_delta > 0 and dr_delta < 0:
            assessment = "HIGHER_APPROVAL_LOWER_FSTPD30"
        elif ar_delta is not None and dr_delta is not None and ar_delta < 0 and dr_delta > 0:
            assessment = "LOWER_APPROVAL_HIGHER_FSTPD30"
        elif ar_delta is not None and dr_delta is not None and ar_delta > 0 and dr_delta > 0:
            assessment = "APPROVAL_RISK_TRADE_OFF"
        elif ar_delta is not None and dr_delta is not None and ar_delta < 0 and dr_delta < 0:
            assessment = "LOWER_APPROVAL_LOWER_FSTPD30_TRADE_OFF"
        elif ar_delta == 0 and dr_delta < 0:
            assessment = "UNCHANGED_APPROVAL_LOWER_FSTPD30"
        elif ar_delta == 0 and dr_delta > 0:
            assessment = "UNCHANGED_APPROVAL_HIGHER_FSTPD30"
        elif ar_delta == 0 and dr_delta == 0:
            assessment = "NO_MEASURED_CHANGE"
        else:
            assessment = "MIXED_OR_NEAR_ZERO_CHANGE"

    stage_analysis: dict[str, Any] = {}
    stage_comparison_rows: list[dict[str, Any]] = []
    for definition in STAGE_DEFINITIONS:
        old = _stage_metrics(baseline_rows, definition)
        new = _stage_metrics(challenger_rows, definition)
        stage_analysis[definition["id"]] = {
            "name": definition["name"],
            "description": definition["description"],
            "rate_label": definition["rate_label"],
            "risk_label": definition["risk_label"],
            "positive_outcomes": list(definition["positive"]),
            "champion": old,
            "challenger": new,
            "delta": {
                "progression_rate_pp": _pp_delta(new["progression_rate"], old["progression_rate"]),
                "final_approval_rate_of_entrants_pp": _pp_delta(
                    new["final_approval_rate_of_entrants"], old["final_approval_rate_of_entrants"]
                ),
                "FSTPD30_rate_pp": _pp_delta(new["FSTPD30_rate"], old["FSTPD30_rate"]),
                "positive_count": new["positive_count"] - old["positive_count"],
            },
        }
        for status in definition["outcomes"]:
            stage_comparison_rows.append(
                {
                    "stage_id": definition["id"],
                    "stage_name": definition["name"],
                    "outcome": status,
                    "champion_count": old["outcome_counts"].get(status, 0),
                    "champion_share_of_cohort": old["outcome_distribution"].get(status),
                    "champion_share_of_stage_entrants": old["outcome_distribution_of_entered"].get(
                        status
                    ),
                    "challenger_count": new["outcome_counts"].get(status, 0),
                    "challenger_share_of_cohort": new["outcome_distribution"].get(status),
                    "challenger_share_of_stage_entrants": new[
                        "outcome_distribution_of_entered"
                    ].get(status),
                    "champion_final_approval_count_of_entrants": old[
                        "final_approval_count_of_entrants"
                    ],
                    "champion_final_approval_rate_of_entrants": old[
                        "final_approval_rate_of_entrants"
                    ],
                    "challenger_final_approval_count_of_entrants": new[
                        "final_approval_count_of_entrants"
                    ],
                    "challenger_final_approval_rate_of_entrants": new[
                        "final_approval_rate_of_entrants"
                    ],
                    "delta_count": new["outcome_counts"].get(status, 0)
                    - old["outcome_counts"].get(status, 0),
                }
            )

    return {
        "target": {
            "name": "FSTPD30",
            "definition": "1 if any of the first, second or third scheduled instalments reaches 30+ days past due; 0 otherwise.",
            "maturity_rule": "The third scheduled instalment plus a 30-day delinquency observation window must have elapsed (four months on book in this synthetic cohort).",
            "interpretation": "Synthetic counterfactual risk proxy only. It is not observed performance on booked loans and is not a calibrated probability of default.",
            "generation_model": "Shared latent risk drives affordability, bureau score/history, six alternative-data credit signals and a related identity/fraud propensity; payment-level DPD outcomes are generated from the same latent risk and bureau history.",
        },
        "champion": champion,
        "challenger": challenger,
        "delta": delta,
        "assessment": assessment,
        "stage_analysis": stage_analysis,
        "stage_comparison_rows": stage_comparison_rows,
        "score_deciles": _score_deciles(baseline_rows, "Champion")
        + _score_deciles(challenger_rows, "Challenger"),
        "segment_analysis": _segment_analysis(baseline_rows, "Champion")
        + _segment_analysis(challenger_rows, "Challenger"),
        "source_coverage": _source_coverage(baseline_rows, "Champion")
        + _source_coverage(challenger_rows, "Challenger"),
        "interpretation": (
            "Strict approval rate counts APPROVED only. Offer rate counts APPROVED plus COUNTEROFFER and is shown separately. "
            "The primary assessment compares strict approval-rate movement with FSTPD30 incidence among APPROVED-only cases; "
            "FSTPD30 among all offers (APPROVED plus COUNTEROFFER) is a separate sensitivity metric. "
            "FSTPD30 is calculated only on matured labels; earlier stages use their stage-positive population and the final decision stage uses APPROVED-only cases. "
            "All FSTPD30 labels in this generator are synthetic counterfactuals, including cases that would not be booked. "
            "Consequently this report is suitable for policy-path and sensitivity testing only, not for claiming real portfolio "
            "default performance or production policy superiority. Real performance analysis requires observed outcomes for "
            "booked loans, take-up data, vintage maturity, censoring controls and independently validated target construction."
        ),
    }


def _pp_delta(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    return round((new - old) * 100.0, 2)


def _pct(value: float | int | None, decimals: int = 1) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.{decimals}f}%"


def _pp(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f} pp"


def render_html_report(summary: dict[str, Any], output_path: Path) -> Path:
    """Write a self-contained HTML portfolio impact report."""
    impact = summary["portfolio_impact"]
    champion = impact["champion"]
    challenger = impact["challenger"]
    delta = impact["delta"]

    def kpi_card(
        label: str,
        old: float | None,
        new: float | None,
        change: float | None,
        *,
        lower_is_better: bool = False,
    ) -> str:
        """Render one comparative KPI card with values and direction-aware change status."""
        if change is None or change == 0:
            colour = "neutral"
        else:
            favourable = change < 0 if lower_is_better else change > 0
            colour = "good" if favourable else "bad"
        return (
            f'<article class="kpi"><div class="muted">{escape(label)}</div>'
            f'<div class="pair"><span><small>Champion</small><b>{_pct(old)}</b></span>'
            f"<span><small>Challenger</small><b>{_pct(new)}</b></span></div>"
            f'<div class="delta {colour}">{_pp(change)}</div></article>'
        )

    stage_sections: list[str] = []
    for stage_id, stage in impact["stage_analysis"].items():
        old = stage["champion"]
        new = stage["challenger"]
        outcome_rows = []
        for status in old["outcome_counts"]:
            old_count = old["outcome_counts"][status]
            new_count = new["outcome_counts"].get(status, 0)
            old_share = old["outcome_distribution"].get(status)
            new_share = new["outcome_distribution"].get(status)
            outcome_rows.append(
                "<tr>"
                f"<td>{escape(status.replace('_', ' ').title())}</td>"
                f"<td>{old_count:,}</td>"
                f"<td>{_pct(old_share)}</td>"
                f"<td>{_pct(old['outcome_distribution_of_entered'].get(status))}</td>"
                f"<td>{new_count:,}</td>"
                f"<td>{_pct(new_share)}</td>"
                f"<td>{_pct(new['outcome_distribution_of_entered'].get(status))}</td>"
                f"<td>{new_count - old_count:+,}</td>"
                "</tr>"
            )
        final_approval_kpi = (
            "<span>Final approval rate among stage entrants (APPROVED only): "
            f"<b>{_pct(old['final_approval_rate_of_entrants'])}</b> champion / "
            f"<b>{_pct(new['final_approval_rate_of_entrants'])}</b> challenger "
            f"(<b>{_pp(stage['delta']['final_approval_rate_of_entrants_pp'])}</b>)</span>"
        )
        stage_sections.append(
            f'<section class="stage"><h3>{escape(stage["name"])}</h3>'
            f'<p class="muted">{escape(stage["description"])}</p>'
            f'<div class="stage-kpis"><span>{escape(stage["rate_label"])}: '
            f"<b>{_pct(old['progression_rate'])}</b> champion / <b>{_pct(new['progression_rate'])}</b> challenger "
            f"(<b>{_pp(stage['delta']['progression_rate_pp'])}</b>)</span>"
            f"{final_approval_kpi}"
            f"<span>{escape(stage['risk_label'])}: "
            f"<b>{_pct(old['FSTPD30_rate'])}</b> champion / <b>{_pct(new['FSTPD30_rate'])}</b> challenger "
            f"(<b>{_pp(stage['delta']['FSTPD30_rate_pp'])}</b>)</span></div>"
            "<table><thead><tr><th>Outcome</th><th>Champion n</th><th>Champion % cohort</th><th>Champion % entrants</th>"
            "<th>Challenger n</th><th>Challenger % cohort</th><th>Challenger % entrants</th><th>Delta n</th></tr></thead>"
            f"<tbody>{''.join(outcome_rows)}</tbody></table>"
            f'<p class="muted tiny">Progression denominator: {old["progression_rate_denominator"]:,} champion / {new["progression_rate_denominator"]:,} challenger stage entrants. '
            f"Outcome percentages show both share of the full cohort and share of stage entrants. "
            f"FSTPD30 risk population: {escape(old['FSTPD30_risk_population'])}. Events / matured labels: "
            f"{old['FSTPD30_events']:,}/{old['FSTPD30_labelled_positive_cases']:,} champion / "
            f"{new['FSTPD30_events']:,}/{new['FSTPD30_labelled_positive_cases']:,} challenger. "
            f"Label coverage: {_pct(old['FSTPD30_coverage'])} / {_pct(new['FSTPD30_coverage'])}.</p></section>"
        )

    decile_rows = []
    for row in impact["score_deciles"]:
        decile_rows.append(
            "<tr>"
            f"<td>{escape(row['policy'])}</td><td>{row['decile']}</td><td>{row['case_count']:,}</td>"
            f"<td>{row['score_min'] if row['score_min'] is not None else 'n/a'} - {row['score_max'] if row['score_max'] is not None else 'n/a'}</td>"
            f"<td>{_pct(row['approval_rate'])}</td><td>{_pct(row['offer_rate'])}</td>"
            f"<td>{row['FSTPD30_events_approved']:,}/{row['FSTPD30_labelled_approved']:,}</td><td>{_pct(row['FSTPD30_rate_approved'])}</td>"
            f"<td>{row['FSTPD30_events_offered']:,}/{row['FSTPD30_labelled_offered']:,}</td>"
            f"<td>{_pct(row['FSTPD30_rate_offered'])}</td></tr>"
        )

    source_rows = []
    for policy in ("Champion", "Challenger"):
        rows = [row for row in impact["source_coverage"] if row["policy"] == policy]
        for row in rows:
            source_rows.append(
                f"<tr><td>{escape(policy)}</td><td>{escape(row['source_id'])}</td><td>{row['eligible_cases']:,}</td>"
                f"<td>{row['successful']:,}</td><td>{row['failed']:,}</td><td>{row['missing']:,}</td>"
                f"<td>{row['not_attempted']:,}</td><td>{_pct(row['coverage_rate'])}</td></tr>"
            )

    migration = summary.get("decision_migration_matrix", {})
    migration_rows = []
    all_decisions = sorted({key for row in migration.values() for key in row} | set(migration))
    for baseline_decision in all_decisions:
        cells = "".join(
            f"<td>{migration.get(baseline_decision, {}).get(candidate_decision, 0):,}</td>"
            for candidate_decision in all_decisions
        )
        migration_rows.append(f"<tr><th>{escape(baseline_decision)}</th>{cells}</tr>")

    assessment = escape(impact["assessment"].replace("_", " ").title())
    title = "UWflow Champion vs Challenger - Portfolio Impact"
    dataset = escape(str(summary.get("dataset_id", "unknown")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--ink:#172334;--muted:#64748b;--line:#dce3eb;--paper:#f4f7fa;--blue:#1e4e79;--teal:#167b70;--amber:#996515;--red:#a43a43}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 Inter,Segoe UI,Arial,sans-serif}}
main{{max-width:1180px;margin:28px auto;padding:0 22px 48px}}header{{background:linear-gradient(115deg,#183b5b,#245c70);color:white;padding:30px 34px;border-radius:16px}}
header h1{{font-size:26px;margin:0 0 6px}}header p{{margin:0;color:#d8e6ef}}.meta{{display:flex;gap:24px;flex-wrap:wrap;margin-top:18px;font-size:12px;color:#d8e6ef}}
h2{{font-size:19px;margin:30px 0 12px}}h3{{font-size:16px;margin:0 0 4px}}.muted{{color:var(--muted)}}.tiny{{font-size:11px}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}}.kpi,.panel,.stage{{background:white;border:1px solid var(--line);border-radius:12px;padding:16px}}
.kpi small{{display:block;color:var(--muted);font-size:11px}}.pair{{display:flex;justify-content:space-between;gap:14px;margin-top:8px}}.pair b{{font-size:23px;display:block}}.delta{{font-weight:700;margin-top:8px}}.delta.good{{color:var(--teal)}}.delta.bad{{color:var(--red)}}.delta.neutral{{color:var(--muted)}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.stage{{margin:14px 0}}.stage-kpis{{display:flex;gap:24px;flex-wrap:wrap;margin:12px 0;font-size:12px}}
table{{width:100%;border-collapse:collapse;margin:10px 0 6px;font-size:12px}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:7px 9px;vertical-align:top}}thead th{{background:#f0f4f8;color:#34465a;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}tbody tr:last-child td{{border-bottom:0}}
.callout{{padding:14px 16px;border-left:4px solid var(--teal);background:#eaf5f3;border-radius:8px}}.warning{{padding:14px 16px;border-left:4px solid var(--amber);background:#fff6e7;border-radius:8px;margin-top:18px}}
@media(max-width:800px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}main{{padding:0 12px 30px}}}}@media print{{body{{background:white}}main{{margin:0;max-width:none;padding:0}}header{{border-radius:0}}.stage,.panel,.kpi{{break-inside:avoid}}}}
</style></head><body><main>
<header><h1>{title}</h1><p>Underwriting strategy impact assessment for risk, approval and funnel migration.</p>
<div class="meta"><span>Dataset: {dataset}</span><span>Applications: {champion["application_count"]:,}</span>
<span>Champion: {escape(str(summary.get("baseline_runtime_release")))}</span><span>Challenger: {escape(str(summary.get("candidate_runtime_release")))}</span>
<span>Dataset SHA-256: {escape(str(summary.get("dataset_sha256"))[:16])}...</span></div></header>
<h2>Executive assessment</h2><div class="callout"><b>{assessment}</b><br>{escape(impact["interpretation"])}</div>
<div class="kpis">
{kpi_card("Approval rate (APPROVED only)", champion["strict_approval_rate"], challenger["strict_approval_rate"], delta["strict_approval_rate_pp"])}
{kpi_card("FSTPD30 rate among approved cases", champion["FSTPD30_rate_on_approved"], challenger["FSTPD30_rate_on_approved"], delta["FSTPD30_rate_on_approved_pp"], lower_is_better=True)}
{kpi_card("Offer rate (APPROVED + COUNTEROFFER)", champion["offer_rate"], challenger["offer_rate"], delta["offer_rate_pp"])}
{kpi_card("FSTPD30 rate among offered cases", champion["FSTPD30_rate_on_offers"], challenger["FSTPD30_rate_on_offers"], delta["FSTPD30_rate_on_offers_pp"], lower_is_better=True)}
</div><p class="muted tiny">FSTPD30 events / matured labels: approved {_pct(champion["FSTPD30_rate_on_approved"])} ({champion["FSTPD30_events_on_approved"]:,}/{champion["FSTPD30_labelled_approved"]:,}) champion / {_pct(challenger["FSTPD30_rate_on_approved"])} ({challenger["FSTPD30_events_on_approved"]:,}/{challenger["FSTPD30_labelled_approved"]:,}) challenger; offers {_pct(champion["FSTPD30_rate_on_offers"])} ({champion["FSTPD30_events_on_offers"]:,}/{champion["FSTPD30_labelled_offers"]:,}) champion / {_pct(challenger["FSTPD30_rate_on_offers"])} ({challenger["FSTPD30_events_on_offers"]:,}/{challenger["FSTPD30_labelled_offers"]:,}) challenger. Label coverage: approved {_pct(champion["FSTPD30_approved_label_coverage"])} / {_pct(challenger["FSTPD30_approved_label_coverage"])}; offers {_pct(champion["FSTPD30_offer_label_coverage"])} / {_pct(challenger["FSTPD30_offer_label_coverage"])}. Immature cases are excluded from risk-rate denominators.</p>
<div class="grid2"><section class="panel"><h3>Champion final outcomes</h3><table><tbody>{"".join(f"<tr><td>{escape(k)}</td><td>{v:,}</td></tr>" for k, v in champion["decision_counts"].items())}</tbody></table></section>
<section class="panel"><h3>Challenger final outcomes</h3><table><tbody>{"".join(f"<tr><td>{escape(k)}</td><td>{v:,}</td></tr>" for k, v in challenger["decision_counts"].items())}</tbody></table></section></div>
<h2>Stage-by-stage funnel and risk analysis</h2><p class="muted">Outcome distributions include zero-count categories and NOT REACHED cases. Each stage shows both share of the full cohort and share of stage entrants. Stage risk uses matured FSTPD30 labels among that stage's positive population; for the final credit-decision stage it is APPROVED-only, so it matches the strict approval cohort.</p>
{"".join(stage_sections)}
<h2>Decision migration: champion to challenger</h2><p class="muted">Rows are champion outcomes; columns are challenger outcomes.</p><table><thead><tr><th>Champion \\ Challenger</th>{"".join(f"<th>{escape(item)}</th>" for item in all_decisions)}</tr></thead><tbody>{"".join(migration_rows)}</tbody></table>
<h2>AIDflow profile score deciles</h2><p class="muted">Decile 1 is the lowest score; decile 10 is the highest. Approved-only and broader offer FSTPD30 rates use matured labels and separate denominators.</p>
<table><thead><tr><th>Policy</th><th>Decile</th><th>Cases</th><th>Score range</th><th>Approval rate</th><th>Offer rate</th><th>FSTPD30 approved events / labels</th><th>Approved risk</th><th>FSTPD30 offer events / labels</th><th>Offer risk</th></tr></thead><tbody>{"".join(decile_rows)}</tbody></table>
<h2>Ten-source collection coverage</h2><table><thead><tr><th>Policy</th><th>Source</th><th>Eligible cases</th><th>Successful</th><th>Failed</th><th>Missing</th><th>Not attempted</th><th>Coverage</th></tr></thead><tbody>{"".join(source_rows)}</tbody></table>
<h2>Risk and approval by portfolio segment</h2><table><thead><tr><th>Policy</th><th>Segment</th><th>Value</th><th>Cases</th><th>Approvals</th><th>Approval rate</th><th>Offers</th><th>Offer rate</th><th>FSTPD30 on approved</th><th>FSTPD30 on offers</th></tr></thead><tbody>{"".join(f"<tr><td>{escape(r['policy'])}</td><td>{escape(r['segment'])}</td><td>{escape(r['value'])}</td><td>{r['case_count']:,}</td><td>{r['approval_count']:,}</td><td>{_pct(r['approval_rate'])}</td><td>{r['offer_count']:,}</td><td>{_pct(r['offer_rate'])}</td><td>{r['FSTPD30_events_approved']:,}/{r['FSTPD30_labelled_approved']:,} ({_pct(r['FSTPD30_rate_on_approved'])})</td><td>{r['FSTPD30_events_offered']:,}/{r['FSTPD30_labelled_offers']:,} ({_pct(r['FSTPD30_rate_on_offers'])})</td></tr>" for r in impact["segment_analysis"])}</tbody></table>
<div class="warning"><b>Critical interpretation limitation</b><br>{escape(impact["target"]["interpretation"])} {escape(impact["target"]["definition"])} {escape(impact["target"]["maturity_rule"])}</div>
<h2>Reproducibility and provenance</h2><table><tbody>
<tr><td>Baseline runtime manifest SHA-256</td><td>{escape(str(summary.get("baseline_runtime_manifest_sha256")))}</td></tr>
<tr><td>Candidate runtime manifest SHA-256</td><td>{escape(str(summary.get("candidate_runtime_manifest_sha256")))}</td></tr>
<tr><td>Dataset SHA-256</td><td>{escape(str(summary.get("dataset_sha256")))}</td></tr>
<tr><td>Replay case count</td><td>{champion["application_count"]:,}</td></tr>
<tr><td>Target</td><td>FSTPD30</td></tr></tbody></table>
<p class="muted tiny">Generated by UWflow historical replay comparison. Approval includes counteroffers in offer rate; straight-through approval is separately reported. No LGD, expected-loss or profitability estimate is inferred from FSTPD30.</p>
</main></body></html>"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def render_pdf_report(summary: dict[str, Any], output_path: Path) -> Path:
    """Write a CRO-friendly A4 landscape PDF using the task image's ReportLab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
            PageBreak,
            KeepTogether,
        )
        from xml.sax.saxutils import escape as xml_escape
    except ImportError as exc:  # pragma: no cover - runtime image pins reportlab
        raise RuntimeError(
            "The comparison PDF requires ReportLab from core/docker/requirements.txt"
        ) from exc

    impact = summary["portfolio_impact"]
    champion, challenger, delta = impact["champion"], impact["challenger"], impact["delta"]
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="UWTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=25,
            textColor=colors.HexColor("#173B5A"),
            alignment=TA_LEFT,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="UWSub",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#526176"),
            spaceAfter=9,
        )
    )
    styles.add(
        ParagraphStyle(
            name="UWSection",
            parent=styles["Heading2"],
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#173B5A"),
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="UWSmall",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#526176"),
        )
    )
    styles.add(ParagraphStyle(name="UWCell", parent=styles["Normal"], fontSize=7.5, leading=9))
    styles.add(
        ParagraphStyle(
            name="UWCellHead",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=colors.white,
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        rightMargin=13 * mm,
        leftMargin=13 * mm,
        topMargin=12 * mm,
        bottomMargin=13 * mm,
        title="UWflow Champion vs Challenger Portfolio Impact",
        author="UWflow",
    )
    story: list[Any] = [
        Paragraph("UWflow | Champion vs Challenger", styles["UWTitle"]),
        Paragraph(
            f"Portfolio impact assessment | Dataset: {xml_escape(str(summary.get('dataset_id')))} | "
            f"Applications: {champion['application_count']:,} | "
            f"Champion: {xml_escape(str(summary.get('baseline_runtime_release')))} | "
            f"Challenger: {xml_escape(str(summary.get('candidate_runtime_release')))}",
            styles["UWSub"],
        ),
    ]
    kpi_data = [
        [
            Paragraph("<b>METRIC</b>", styles["UWCellHead"]),
            Paragraph("<b>CHAMPION</b>", styles["UWCellHead"]),
            Paragraph("<b>CHALLENGER</b>", styles["UWCellHead"]),
            Paragraph("<b>DELTA</b>", styles["UWCellHead"]),
        ]
    ]

    def risk_cell(rate: float | None, events: int, labelled: int) -> str:
        """Format a risk-rate cell with event and maturity denominators."""
        return f"{_pct(rate)} ({events:,}/{labelled:,})"

    for label, old_value, new_value, old_display, new_display, diff in (
        (
            "Approval rate (APPROVED only)",
            champion["strict_approval_rate"],
            challenger["strict_approval_rate"],
            None,
            None,
            delta["strict_approval_rate_pp"],
        ),
        (
            "FSTPD30 among approved (events / labels)",
            champion["FSTPD30_rate_on_approved"],
            challenger["FSTPD30_rate_on_approved"],
            risk_cell(
                champion["FSTPD30_rate_on_approved"],
                champion["FSTPD30_events_on_approved"],
                champion["FSTPD30_labelled_approved"],
            ),
            risk_cell(
                challenger["FSTPD30_rate_on_approved"],
                challenger["FSTPD30_events_on_approved"],
                challenger["FSTPD30_labelled_approved"],
            ),
            delta["FSTPD30_rate_on_approved_pp"],
        ),
        (
            "Offer rate (APPROVED + COUNTEROFFER)",
            champion["offer_rate"],
            challenger["offer_rate"],
            None,
            None,
            delta["offer_rate_pp"],
        ),
        (
            "FSTPD30 among offers (events / labels)",
            champion["FSTPD30_rate_on_offers"],
            challenger["FSTPD30_rate_on_offers"],
            risk_cell(
                champion["FSTPD30_rate_on_offers"],
                champion["FSTPD30_events_on_offers"],
                champion["FSTPD30_labelled_offers"],
            ),
            risk_cell(
                challenger["FSTPD30_rate_on_offers"],
                challenger["FSTPD30_events_on_offers"],
                challenger["FSTPD30_labelled_offers"],
            ),
            delta["FSTPD30_rate_on_offers_pp"],
        ),
        (
            "FSTPD30 approved label coverage",
            champion["FSTPD30_approved_label_coverage"],
            challenger["FSTPD30_approved_label_coverage"],
            None,
            None,
            _pp_delta(
                challenger["FSTPD30_approved_label_coverage"],
                champion["FSTPD30_approved_label_coverage"],
            ),
        ),
        (
            "FSTPD30 offer label coverage",
            champion["FSTPD30_offer_label_coverage"],
            challenger["FSTPD30_offer_label_coverage"],
            None,
            None,
            _pp_delta(
                challenger["FSTPD30_offer_label_coverage"], champion["FSTPD30_offer_label_coverage"]
            ),
        ),
    ):
        kpi_data.append(
            [label, old_display or _pct(old_value), new_display or _pct(new_value), _pp(diff)]
        )
    kpi_table = Table(kpi_data, colWidths=[85 * mm, 45 * mm, 45 * mm, 45 * mm], repeatRows=1)
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173B5A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F2F6F9")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E0E8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            kpi_table,
            Spacer(1, 7),
            Paragraph(
                f"Assessment: <b>{xml_escape(impact['assessment'].replace('_', ' ').title())}</b>",
                styles["UWSub"],
            ),
        ]
    )
    story.append(Paragraph("Final decision distribution", styles["UWSection"]))
    decisions = [["Outcome", "Champion", "Challenger", "Delta"]]
    for key in ("APPROVED", "COUNTEROFFER", "REFERRED", "REJECTED", "CANCELLED", "OTHER"):
        old = champion["decision_counts"].get(key, 0)
        new = challenger["decision_counts"].get(key, 0)
        decisions.append([key, f"{old:,}", f"{new:,}", f"{new - old:+,}"])
    t = Table(decisions, colWidths=[65 * mm, 45 * mm, 45 * mm, 45 * mm], repeatRows=1)
    t.setStyle(_table_style(colors))
    story.append(t)

    for stage_index, stage in enumerate(impact["stage_analysis"].values()):
        old, new = stage["champion"], stage["challenger"]
        final_approval_text = (
            f"Final approval among stage entrants: {_pct(old['final_approval_rate_of_entrants'])} champion / "
            f"{_pct(new['final_approval_rate_of_entrants'])} challenger "
            f"({_pp(stage['delta']['final_approval_rate_of_entrants_pp'])}); "
        )
        metric_summary = Paragraph(
            f"{xml_escape(stage['rate_label'])}: {_pct(old['progression_rate'])} champion / {_pct(new['progression_rate'])} challenger "
            f"({_pp(stage['delta']['progression_rate_pp'])}); "
            f"{final_approval_text}"
            f"{xml_escape(stage['risk_label'])}: {_pct(old['FSTPD30_rate'])} champion "
            f"({old['FSTPD30_events']:,}/{old['FSTPD30_labelled_positive_cases']:,} events/labels) / "
            f"{_pct(new['FSTPD30_rate'])} challenger "
            f"({new['FSTPD30_events']:,}/{new['FSTPD30_labelled_positive_cases']:,} events/labels) "
            f"({_pp(stage['delta']['FSTPD30_rate_pp'])}).",
            styles["UWSmall"],
        )
        data = [
            [
                "Outcome",
                "Champion n",
                "Champ % cohort",
                "Champ % entrants",
                "Challenger n",
                "Chall % cohort",
                "Chall % entrants",
                "Delta n",
            ]
        ]
        for status in old["outcome_counts"]:
            a = old["outcome_counts"][status]
            b = new["outcome_counts"].get(status, 0)
            data.append(
                [
                    status.replace("_", " ").title(),
                    f"{a:,}",
                    _pct(old["outcome_distribution"].get(status)),
                    _pct(old["outcome_distribution_of_entered"].get(status)),
                    f"{b:,}",
                    _pct(new["outcome_distribution"].get(status)),
                    _pct(new["outcome_distribution_of_entered"].get(status)),
                    f"{b - a:+,}",
                ]
            )
        table = Table(
            data,
            colWidths=[44 * mm, 20 * mm, 27 * mm, 27 * mm, 22 * mm, 27 * mm, 27 * mm, 18 * mm],
            repeatRows=1,
        )
        table.setStyle(_table_style(colors))
        stage_content = [
            Paragraph("Stage-by-stage outcome distribution and FSTPD30", styles["UWSection"]),
            Paragraph(xml_escape(stage["name"]), styles["Heading3"]),
            metric_summary,
            table,
            Spacer(1, 5),
        ]
        if stage_index == 0:
            story.append(KeepTogether(stage_content))
        else:
            story.append(KeepTogether(stage_content[1:]))

    story.append(PageBreak())
    story.append(Paragraph("AIDflow score deciles", styles["UWSection"]))
    deciles = [
        [
            "Policy",
            "Decile",
            "Cases",
            "Score range",
            "Approval rate",
            "Offer rate",
            "FSTPD30 approved n/labels",
            "Approved risk",
            "FSTPD30 offer n/labels",
            "Offer risk",
        ]
    ]
    for row in impact["score_deciles"]:
        score_range = (
            "n/a" if row["score_min"] is None else f"{row['score_min']:.0f}-{row['score_max']:.0f}"
        )
        deciles.append(
            [
                row["policy"],
                str(row["decile"]),
                f"{row['case_count']:,}",
                score_range,
                _pct(row["approval_rate"]),
                _pct(row["offer_rate"]),
                f"{row['FSTPD30_events_approved']}/{row['FSTPD30_labelled_approved']}",
                _pct(row["FSTPD30_rate_approved"]),
                f"{row['FSTPD30_events_offered']}/{row['FSTPD30_labelled_offered']}",
                _pct(row["FSTPD30_rate_offered"]),
            ]
        )
    table = Table(
        deciles,
        colWidths=[
            20 * mm,
            12 * mm,
            17 * mm,
            22 * mm,
            20 * mm,
            20 * mm,
            34 * mm,
            19 * mm,
            34 * mm,
            19 * mm,
        ],
        repeatRows=1,
    )
    table.setStyle(_table_style(colors))
    story.extend([table, Paragraph("Ten-source collection coverage", styles["UWSection"])])

    sources = [
        [
            "Policy",
            "Source",
            "Eligible",
            "Success",
            "Failed",
            "Missing",
            "Not attempted",
            "Coverage",
        ]
    ]
    for row in impact["source_coverage"]:
        sources.append(
            [
                row["policy"],
                row["source_id"],
                f"{row['eligible_cases']:,}",
                f"{row['successful']:,}",
                f"{row['failed']:,}",
                f"{row['missing']:,}",
                f"{row['not_attempted']:,}",
                _pct(row["coverage_rate"]),
            ]
        )
    table = Table(
        sources,
        colWidths=[22 * mm, 54 * mm, 22 * mm, 22 * mm, 20 * mm, 20 * mm, 26 * mm, 23 * mm],
        repeatRows=1,
    )
    table.setStyle(_table_style(colors))
    story.extend([table, Paragraph("Segment analysis", styles["UWSection"])])

    segments = [
        [
            "Policy",
            "Segment",
            "Value",
            "Cases",
            "Approvals",
            "Approval rate",
            "Offers",
            "Offer rate",
            "FSTPD30 approved",
            "FSTPD30 offers",
        ]
    ]
    for row in impact["segment_analysis"]:
        segments.append(
            [
                row["policy"],
                row["segment"],
                row["value"],
                f"{row['case_count']:,}",
                f"{row['approval_count']:,}",
                _pct(row["approval_rate"]),
                f"{row['offer_count']:,}",
                _pct(row["offer_rate"]),
                f"{row['FSTPD30_events_approved']}/{row['FSTPD30_labelled_approved']} ({_pct(row['FSTPD30_rate_on_approved'])})",
                f"{row['FSTPD30_events_offered']}/{row['FSTPD30_labelled_offers']} ({_pct(row['FSTPD30_rate_on_offers'])})",
            ]
        )
    table = Table(
        segments,
        colWidths=[
            18 * mm,
            25 * mm,
            23 * mm,
            15 * mm,
            17 * mm,
            18 * mm,
            15 * mm,
            18 * mm,
            55 * mm,
            55 * mm,
        ],
        repeatRows=1,
    )
    table.setStyle(_table_style(colors))
    story.extend(
        [
            table,
            Paragraph("Interpretation and governance limitations", styles["UWSection"]),
            Paragraph(xml_escape(impact["target"]["definition"]), styles["UWSmall"]),
            Paragraph(xml_escape(impact["target"]["maturity_rule"]), styles["UWSmall"]),
            Paragraph(xml_escape(impact["target"]["interpretation"]), styles["UWSmall"]),
            Paragraph(xml_escape(impact["interpretation"]), styles["UWSmall"]),
        ]
    )

    def short_digest(value: Any) -> str:
        """Return a shortened digest for compact report provenance display."""
        text = str(value or "")
        return f"{text[:16]}..." if len(text) > 20 else (text or "n/a")

    provenance = [
        [
            "Dataset",
            str(summary.get("dataset_id")),
            "Dataset SHA-256",
            short_digest(summary.get("dataset_sha256")),
        ],
        [
            "Champion",
            str(summary.get("baseline_runtime_release")),
            "Manifest SHA-256",
            short_digest(summary.get("baseline_runtime_manifest_sha256")),
        ],
        [
            "Challenger",
            str(summary.get("candidate_runtime_release")),
            "Manifest SHA-256",
            short_digest(summary.get("candidate_runtime_manifest_sha256")),
        ],
    ]
    table = Table(provenance, colWidths=[28 * mm, 75 * mm, 34 * mm, 91 * mm])
    table.setStyle(_table_style(colors, small=True))
    # Provenance sits on the opening page with the headline comparison rather
    # than becoming an almost-empty appendix page in smaller smoke reports.
    story.insert(
        story.index(t) + 1,
        KeepTogether(
            [
                Paragraph(
                    "Replay provenance (SHA-256 prefixes; full digests in JSON/HTML)",
                    styles["UWSmall"],
                ),
                table,
                Spacer(1, 5),
            ]
        ),
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return output_path


def _table_style(colors: Any, *, small: bool = False) -> Any:
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173B5A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 6.2 if small else 7),
            ("LEADING", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F9")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7E0E8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _page_footer(canvas: Any, doc: Any) -> None:
    from reportlab.lib import colors

    canvas.saveState()
    width, _ = doc.pagesize
    canvas.setStrokeColor(colors.HexColor("#D7E0E8"))
    canvas.line(doc.leftMargin, 9 * 6, width - doc.rightMargin, 9 * 6)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(
        doc.leftMargin,
        9 * 3,
        "UWflow | Synthetic champion-challenger analysis | Not for lending decisions",
    )
    canvas.drawRightString(width - doc.rightMargin, 9 * 3, f"Page {doc.page}")
    canvas.restoreState()
