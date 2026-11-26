"""Compare paired baseline/candidate historical replay batch artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
from typing import Any

try:  # Source checkout and repository tests.
    from modules.reporting.tools.impact_report import (
        build_impact_analysis,
        render_html_report,
        render_pdf_report,
    )
except ModuleNotFoundError:  # pragma: no cover - flat immutable Kestra bundle.
    from impact_report import build_impact_analysis, render_html_report, render_pdf_report

DECISION_ORDER = ("APPROVED", "COUNTEROFFER", "REFER", "DECLINED", "CANCELLED", "OTHER")


class HistoryComparisonError(RuntimeError):
    """Raised when replay artifacts do not describe the same dataset cohort."""


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HistoryComparisonError(f"Invalid JSON in {path}, line {line_number}") from exc
            application_id = row.get("application_id")
            if not isinstance(application_id, str) or not application_id:
                raise HistoryComparisonError(
                    f"Missing application_id in {path}, line {line_number}"
                )
            if application_id in rows:
                raise HistoryComparisonError(f"Duplicate application_id {application_id} in {path}")
            rows[application_id] = row
    return rows


def _decision(value: Any) -> str:
    label = str(value or "NO_DECISION")
    return label if label in DECISION_ORDER[:-1] else "OTHER"


def _rate(defaults: int, observed: int) -> float | None:
    return round(defaults / observed, 6) if observed else None


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {key: 0 for key in DECISION_ORDER}
    outcome_groups: dict[str, dict[str, int]] = {}
    changed = 0
    for row in rows:
        counts[_decision(row.get("candidate_decision"))] += 1
        changed += int(bool(row.get("decision_changed")))
        outcome = row.get("outcome") or {}
        if outcome.get("outcome_status") == "MATURED" and isinstance(
            outcome.get("default_12m"), bool
        ):
            label_type = str(outcome.get("label_type") or "UNSPECIFIED_LABEL_TYPE")
            metrics = outcome_groups.setdefault(
                label_type, {"labelled_cases": 0, "default_events": 0}
            )
            metrics["labelled_cases"] += 1
            metrics["default_events"] += int(outcome["default_12m"])
    return {
        "case_count": len(rows),
        "decision_changes": changed,
        "candidate_decisions": counts,
        "outcome_metrics_by_label_type": {
            label_type: {
                **metrics,
                "default_rate": _rate(metrics["default_events"], metrics["labelled_cases"]),
            }
            for label_type, metrics in sorted(outcome_groups.items())
        },
    }


def compare_batches(baseline_path: Path, candidate_path: Path, output_dir: Path) -> dict[str, Any]:
    """Compare baseline and candidate batch outputs and write portfolio impact evidence."""
    baseline = _read_jsonl(baseline_path)
    candidate = _read_jsonl(candidate_path)
    if not baseline or not candidate:
        raise HistoryComparisonError("Both replay artifacts must contain at least one case")
    if set(baseline) != set(candidate):
        missing_candidate = sorted(set(baseline) - set(candidate))[:10]
        missing_baseline = sorted(set(candidate) - set(baseline))[:10]
        raise HistoryComparisonError(
            f"Replay cohorts differ; missing candidate={missing_candidate}, missing baseline={missing_baseline}"
        )

    ids = sorted(baseline)
    baseline_rows = [baseline[item] for item in ids]
    candidate_rows = [candidate[item] for item in ids]
    dataset_ids = {str(row.get("dataset_id")) for row in baseline_rows + candidate_rows}
    dataset_hashes = {str(row.get("dataset_sha256")) for row in baseline_rows + candidate_rows}
    baseline_runtime_hashes = {str(row.get("runtime_manifest_sha256")) for row in baseline_rows}
    candidate_runtime_hashes = {str(row.get("runtime_manifest_sha256")) for row in candidate_rows}
    if len(dataset_ids) != 1 or len(dataset_hashes) != 1:
        raise HistoryComparisonError(
            "Baseline and candidate artifacts do not share one immutable dataset snapshot"
        )
    dataset_sha256 = next(iter(dataset_hashes))
    if len(dataset_sha256) != 64 or any(char not in "0123456789abcdef" for char in dataset_sha256):
        raise HistoryComparisonError(
            "Replay artifacts do not contain a valid dataset SHA-256 checksum"
        )
    if len(baseline_runtime_hashes) != 1 or len(candidate_runtime_hashes) != 1:
        raise HistoryComparisonError("Runtime provenance changed within a replay batch")
    dataset_id = next(iter(dataset_ids))

    matrix: dict[str, dict[str, int]] = {}
    comparison_rows: list[dict[str, Any]] = []
    score_deltas: list[float] = []
    amount_deltas: list[float] = []
    source_plan_changed = 0
    hard_gate_changed = 0
    outcome_groups: dict[str, dict[str, int]] = {}
    fstpd30_groups: dict[str, dict[str, int]] = {}
    trace_hits: dict[str, int] = {}
    segment_rows: dict[str, list[dict[str, Any]]] = {}
    historical_decision_cases = 0
    baseline_historical_matches = 0
    candidate_historical_matches = 0
    historical_decision_versions: dict[str, int] = {}

    for application_id in ids:
        old = baseline[application_id]
        new = candidate[application_id]
        old_decision = _decision(old.get("decision"))
        new_decision = _decision(new.get("decision"))
        matrix.setdefault(old_decision, {}).setdefault(new_decision, 0)
        matrix[old_decision][new_decision] += 1
        changed = old_decision != new_decision
        old_score = old.get("profile_score")
        new_score = new.get("profile_score")
        score_delta = (
            float(new_score) - float(old_score)
            if isinstance(old_score, (int, float)) and isinstance(new_score, (int, float))
            else None
        )
        if score_delta is not None:
            score_deltas.append(score_delta)
        old_amount = float(old.get("approved_amount") or 0.0)
        new_amount = float(new.get("approved_amount") or 0.0)
        amount_delta = round(new_amount - old_amount, 2)
        amount_deltas.append(amount_delta)
        plan_changed = set(old.get("source_plan_ids") or []) != set(
            new.get("source_plan_ids") or []
        )
        gate_changed = bool(old.get("hard_gate_passed")) != bool(new.get("hard_gate_passed"))
        source_plan_changed += int(plan_changed)
        hard_gate_changed += int(gate_changed)

        old_outcome = old.get("outcome") or {}
        new_outcome = new.get("outcome") or {}
        if old_outcome != new_outcome:
            raise HistoryComparisonError(
                f"Outcome snapshot differs between baseline and candidate for {application_id}"
            )
        outcome = new_outcome or old_outcome
        recorded_decision = old.get("recorded_decision_snapshot")
        if recorded_decision != new.get("recorded_decision_snapshot"):
            raise HistoryComparisonError(
                f"Recorded historical decision snapshot differs between baseline and candidate for {application_id}"
            )
        recorded_decision_label = None
        baseline_matches_recorded = None
        candidate_matches_recorded = None
        if recorded_decision is not None:
            recorded_decision_label = str(recorded_decision.get("decision"))
            baseline_matches_recorded = old_decision == _decision(recorded_decision_label)
            candidate_matches_recorded = new_decision == _decision(recorded_decision_label)
            historical_decision_cases += 1
            baseline_historical_matches += int(baseline_matches_recorded)
            candidate_historical_matches += int(candidate_matches_recorded)
            recorded_policy = str(
                recorded_decision.get("policy_version") or "UNSPECIFIED_POLICY_VERSION"
            )
            historical_decision_versions[recorded_policy] = (
                historical_decision_versions.get(recorded_policy, 0) + 1
            )
        outcome_label_type = str(outcome.get("label_type") or "UNSPECIFIED_LABEL_TYPE")
        if outcome.get("outcome_status") == "MATURED" and isinstance(
            outcome.get("default_12m"), bool
        ):
            metrics = outcome_groups.setdefault(
                outcome_label_type,
                {
                    "labelled_cases": 0,
                    "default_events": 0,
                    "baseline_offer_labelled_cases": 0,
                    "baseline_offer_default_events": 0,
                    "candidate_offer_labelled_cases": 0,
                    "candidate_offer_default_events": 0,
                },
            )
            is_default = int(bool(outcome["default_12m"]))
            metrics["labelled_cases"] += 1
            metrics["default_events"] += is_default
            if old_decision in {"APPROVED", "COUNTEROFFER"}:
                metrics["baseline_offer_labelled_cases"] += 1
                metrics["baseline_offer_default_events"] += is_default
            if new_decision in {"APPROVED", "COUNTEROFFER"}:
                metrics["candidate_offer_labelled_cases"] += 1
                metrics["candidate_offer_default_events"] += is_default

        if outcome.get("outcome_status") == "MATURED" and outcome.get("target_name") == "FSTPD30":
            target_value = outcome.get("FSTPD30")
            if not isinstance(target_value, (bool, int)) or int(target_value) not in (0, 1):
                raise HistoryComparisonError(
                    f"Matured FSTPD30 outcome is missing a binary target value for {application_id}"
                )
            event = int(target_value)
            metrics = fstpd30_groups.setdefault(
                outcome_label_type,
                {
                    "labelled_cases": 0,
                    "event_count": 0,
                    "baseline_approved_labelled_cases": 0,
                    "baseline_approved_events": 0,
                    "challenger_approved_labelled_cases": 0,
                    "challenger_approved_events": 0,
                    "baseline_offer_labelled_cases": 0,
                    "baseline_offer_events": 0,
                    "challenger_offer_labelled_cases": 0,
                    "challenger_offer_events": 0,
                },
            )
            metrics["labelled_cases"] += 1
            metrics["event_count"] += event
            if old_decision == "APPROVED":
                metrics["baseline_approved_labelled_cases"] += 1
                metrics["baseline_approved_events"] += event
            if new_decision == "APPROVED":
                metrics["challenger_approved_labelled_cases"] += 1
                metrics["challenger_approved_events"] += event
            if old_decision in {"APPROVED", "COUNTEROFFER"}:
                metrics["baseline_offer_labelled_cases"] += 1
                metrics["baseline_offer_events"] += event
            if new_decision in {"APPROVED", "COUNTEROFFER"}:
                metrics["challenger_offer_labelled_cases"] += 1
                metrics["challenger_offer_events"] += event

        for trace_id in list(new.get("hard_gate_trace") or []) + list(
            new.get("source_plan_trace") or []
        ):
            trace_hits[str(trace_id)] = trace_hits.get(str(trace_id), 0) + 1
        segments = new.get("segments") or old.get("segments") or {}
        for key, value in segments.items():
            segment_rows.setdefault(f"{key}={value}", []).append(
                {
                    "candidate_decision": new_decision,
                    "decision_changed": changed,
                    "outcome": outcome,
                }
            )
        comparison_rows.append(
            {
                "application_id": application_id,
                "baseline_decision": old_decision,
                "candidate_decision": new_decision,
                "recorded_historical_decision": recorded_decision_label,
                "baseline_matches_recorded_decision": baseline_matches_recorded,
                "candidate_matches_recorded_decision": candidate_matches_recorded,
                "decision_changed": changed,
                "baseline_profile_score": old_score,
                "candidate_profile_score": new_score,
                "profile_score_delta": score_delta,
                "baseline_approved_amount": old_amount,
                "candidate_approved_amount": new_amount,
                "approved_amount_delta": amount_delta,
                "baseline_hard_gate_passed": old.get("hard_gate_passed"),
                "candidate_hard_gate_passed": new.get("hard_gate_passed"),
                "source_plan_changed": plan_changed,
                "baseline_source_count": len(old.get("source_plan_ids") or []),
                "candidate_source_count": len(new.get("source_plan_ids") or []),
                "outcome_status": outcome.get("outcome_status"),
                "outcome_label_type": outcome_label_type,
                "default_12m": outcome.get("default_12m"),
                "FSTPD30": outcome.get("FSTPD30"),
                "FSTPD30_outcome_status": outcome.get("outcome_status"),
                "first_payment_days_past_due": outcome.get("first_payment_days_past_due"),
                "second_payment_days_past_due": outcome.get("second_payment_days_past_due"),
                "third_payment_days_past_due": outcome.get("third_payment_days_past_due"),
                **{
                    f"baseline_{stage_id}_outcome": (old.get("stage_results") or {})
                    .get(stage_id, {})
                    .get("outcome", "NOT_REACHED")
                    for stage_id in (
                        "stage1_hard_gates",
                        "stage2_bureau",
                        "stage3_source_plan",
                        "stage4_data_collection",
                        "stage5_aidflow",
                        "stage6_uwflow",
                    )
                },
                **{
                    f"challenger_{stage_id}_outcome": (new.get("stage_results") or {})
                    .get(stage_id, {})
                    .get("outcome", "NOT_REACHED")
                    for stage_id in (
                        "stage1_hard_gates",
                        "stage2_bureau",
                        "stage3_source_plan",
                        "stage4_data_collection",
                        "stage5_aidflow",
                        "stage6_uwflow",
                    )
                },
            }
        )

    mean_score_delta = statistics.fmean(score_deltas) if score_deltas else None
    mean_amount_delta = statistics.fmean(amount_deltas) if amount_deltas else None
    baseline_decisions = {name: 0 for name in DECISION_ORDER}
    candidate_decisions = {name: 0 for name in DECISION_ORDER}
    for row in comparison_rows:
        baseline_decisions[row["baseline_decision"]] += 1
        candidate_decisions[row["candidate_decision"]] += 1

    by_segment = {key: _group_metrics(rows) for key, rows in sorted(segment_rows.items())}
    portfolio_impact = build_impact_analysis(baseline_rows, candidate_rows)
    summary = {
        "report_schema_version": 3,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha256,
        "case_count": len(ids),
        "baseline_runtime_release": baseline_rows[0].get("runtime_release"),
        "baseline_runtime_manifest_sha256": next(iter(baseline_runtime_hashes)),
        "candidate_runtime_release": candidate_rows[0].get("runtime_release"),
        "candidate_runtime_manifest_sha256": next(iter(candidate_runtime_hashes)),
        "decision_changes": sum(1 for row in comparison_rows if row["decision_changed"]),
        "decision_change_rate": round(
            sum(1 for row in comparison_rows if row["decision_changed"]) / len(ids), 6
        ),
        "source_plan_changes": source_plan_changed,
        "hard_gate_result_changes": hard_gate_changed,
        "baseline_decisions": baseline_decisions,
        "candidate_decisions": candidate_decisions,
        "decision_migration_matrix": matrix,
        "profile_score_delta": {
            "count": len(score_deltas),
            "mean_candidate_minus_baseline": round(mean_score_delta, 4)
            if mean_score_delta is not None
            else None,
            "minimum": min(score_deltas) if score_deltas else None,
            "maximum": max(score_deltas) if score_deltas else None,
        },
        "approved_amount_delta_eur": {
            "mean_candidate_minus_baseline": round(mean_amount_delta, 2)
            if mean_amount_delta is not None
            else None,
            "total_candidate_minus_baseline": round(sum(amount_deltas), 2),
            "changed_case_count": sum(1 for value in amount_deltas if value != 0),
        },
        "outcome_validation": {
            "metrics_by_label_type": {
                label_type: {
                    **metrics,
                    "default_rate_all_labelled_cases": _rate(
                        metrics["default_events"], metrics["labelled_cases"]
                    ),
                    "baseline_offer_default_rate": _rate(
                        metrics["baseline_offer_default_events"],
                        metrics["baseline_offer_labelled_cases"],
                    ),
                    "candidate_offer_default_rate": _rate(
                        metrics["candidate_offer_default_events"],
                        metrics["candidate_offer_labelled_cases"],
                    ),
                }
                for label_type, metrics in sorted(outcome_groups.items())
            },
            "FSTPD30_metrics_by_label_type": {
                label_type: {
                    **metrics,
                    "FSTPD30_rate_all_matured": _rate(
                        metrics["event_count"], metrics["labelled_cases"]
                    ),
                    "baseline_approved_FSTPD30_rate": _rate(
                        metrics["baseline_approved_events"],
                        metrics["baseline_approved_labelled_cases"],
                    ),
                    "challenger_approved_FSTPD30_rate": _rate(
                        metrics["challenger_approved_events"],
                        metrics["challenger_approved_labelled_cases"],
                    ),
                    "baseline_offer_FSTPD30_rate": _rate(
                        metrics["baseline_offer_events"], metrics["baseline_offer_labelled_cases"]
                    ),
                    "challenger_offer_FSTPD30_rate": _rate(
                        metrics["challenger_offer_events"],
                        metrics["challenger_offer_labelled_cases"],
                    ),
                }
                for label_type, metrics in sorted(fstpd30_groups.items())
            },
            "target_definition": "FSTPD30: 1 if any of the first three scheduled instalments reaches 30+ DPD; 0 otherwise; null until mature.",
            "interpretation": (
                "Outcome labels are reported separately by label_type. FSTPD30 is 1 when any of the first "
                "three scheduled payments reaches 30+ DPD, 0 otherwise, and null until matured. "
                "SYNTHETIC_COUNTERFACTUAL labels are generated for applicants whether or not a loan was booked and are software-test "
                "fixtures only. Only independently observed, matured outcomes for actually booked loans "
                "can support realized portfolio performance analysis; approval selection, take-up, "
                "censoring and observation-window effects must still be handled."
            ),
        },
        "historical_decision_reconciliation": {
            "recorded_decision_cases": historical_decision_cases,
            "baseline_matches_recorded_decision": baseline_historical_matches,
            "candidate_matches_recorded_decision": candidate_historical_matches,
            "baseline_match_rate": _rate(baseline_historical_matches, historical_decision_cases),
            "candidate_match_rate": _rate(candidate_historical_matches, historical_decision_cases),
            "recorded_policy_versions": dict(sorted(historical_decision_versions.items())),
            "interpretation": (
                "Reconciliation is descriptive. Only interpret a mismatch as a runtime regression after "
                "confirming that the replayed baseline has the same policy, model, source snapshots and "
                "decision semantics as the originally recorded decision. Synthetic datasets intentionally "
                "contain no recorded historical decisions."
            ),
        },
        "new_policy_trace_hits": dict(
            sorted(trace_hits.items(), key=lambda item: (-item[1], item[0]))
        ),
        "segment_analysis": by_segment,
        "portfolio_impact": portfolio_impact,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "case_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison_rows[0]))
        writer.writeheader()
        writer.writerows(comparison_rows)
    with (output_dir / "decision_migrations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["baseline_decision", "candidate_decision", "case_count"])
        for old_decision in sorted(matrix):
            for new_decision in sorted(matrix[old_decision]):
                writer.writerow([old_decision, new_decision, matrix[old_decision][new_decision]])

    csv_outputs = (
        (
            "stage_comparison.csv",
            portfolio_impact["stage_comparison_rows"],
            [
                "stage_id",
                "stage_name",
                "outcome",
                "champion_count",
                "champion_share_of_cohort",
                "champion_share_of_stage_entrants",
                "challenger_count",
                "challenger_share_of_cohort",
                "challenger_share_of_stage_entrants",
                "champion_final_approval_count_of_entrants",
                "champion_final_approval_rate_of_entrants",
                "challenger_final_approval_count_of_entrants",
                "challenger_final_approval_rate_of_entrants",
                "delta_count",
            ],
        ),
        (
            "score_deciles.csv",
            portfolio_impact["score_deciles"],
            [
                "policy",
                "decile",
                "interpretation",
                "case_count",
                "score_min",
                "score_max",
                "approval_count",
                "approval_rate",
                "offer_count",
                "offer_rate",
                "FSTPD30_events_all",
                "FSTPD30_labelled_all",
                "FSTPD30_rate_all",
                "FSTPD30_events_offered",
                "FSTPD30_labelled_offered",
                "FSTPD30_rate_offered",
            ],
        ),
        (
            "segment_impact.csv",
            portfolio_impact["segment_analysis"],
            [
                "policy",
                "segment",
                "value",
                "case_count",
                "approval_count",
                "approval_rate",
                "offer_count",
                "offer_rate",
                "FSTPD30_events_approved",
                "FSTPD30_labelled_approved",
                "FSTPD30_rate_on_approved",
                "FSTPD30_events_offered",
                "FSTPD30_labelled_offers",
                "FSTPD30_rate_on_offers",
            ],
        ),
        (
            "source_coverage.csv",
            portfolio_impact["source_coverage"],
            [
                "policy",
                "source_id",
                "eligible_cases",
                "successful",
                "failed",
                "missing",
                "not_attempted",
                "coverage_rate",
            ],
        ),
    )
    for filename, rows, empty_fieldnames in csv_outputs:
        with (output_dir / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else empty_fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    render_html_report(summary, output_dir / "champion_challenger_report.html")
    render_pdf_report(summary, output_dir / "champion_challenger_report.pdf")
    summary["report_artifacts"] = [
        "champion_challenger_report.html",
        "champion_challenger_report.pdf",
        "stage_comparison.csv",
        "score_deciles.csv",
        "segment_impact.csv",
        "source_coverage.csv",
    ]
    (output_dir / "comparison.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    """Compare two replay output directories and generate the configured reports."""
    parser = argparse.ArgumentParser(
        description="Compare baseline and candidate historical replay files"
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("var/reports/history-comparison"))
    args = parser.parse_args()
    try:
        summary = compare_batches(args.baseline, args.candidate, args.output_dir)
    except (OSError, ValueError, RuntimeError, HistoryComparisonError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
