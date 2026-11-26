"""Tests for comparative champion and challenger portfolio reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import csv
import hashlib
import json
import shutil
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]

from tools.history.replay.compare_batches import compare_batches
from modules.reporting.tools.impact_report import build_impact_analysis
from tools.history.replay.run_batch import evaluate_case, load_runtime
from uwflow_history.generation.synthetic_portfolio import default_dataset_id, generate_cases

STAGES = (
    "stage1_hard_gates",
    "stage2_bureau",
    "stage3_source_plan",
    "stage4_data_collection",
    "stage5_aidflow",
    "stage6_uwflow",
)


def _stage_results(final_outcome: str) -> dict:
    return {
        "stage1_hard_gates": {"outcome": "PASSED", "reached": True},
        "stage2_bureau": {"outcome": "PASSED", "reached": True},
        "stage3_source_plan": {"outcome": "ROUTED_TO_COLLECTION", "reached": True},
        "stage4_data_collection": {
            "outcome": "COMPLETE",
            "reached": True,
            "source_outcomes": {
                source: "SUCCESS"
                for source in (
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
            },
        },
        "stage5_aidflow": {"outcome": "SCORED", "reached": True, "profile_score": 700},
        "stage6_uwflow": {"outcome": final_outcome, "reached": True},
    }


def test_fstpd30_generator_is_matured_and_payment_level_consistent() -> None:
    cases = list(generate_cases(count=2000, seed=17, as_of_date=date(2026, 11, 23)))
    assert default_dataset_id(count=2000, seed=17, as_of_date=date(2026, 11, 23)).startswith(
        "synthetic-eur-v4-fstpd30-"
    )
    rates: dict[str, list[int]] = defaultdict(list)

    for case in cases:
        outcome = case.outcome_snapshot
        assert outcome["target_name"] == "FSTPD30"
        dpd_values = [
            outcome["first_payment_days_past_due"],
            outcome["second_payment_days_past_due"],
            outcome["third_payment_days_past_due"],
        ]
        if outcome["outcome_status"] == "IMMATURE":
            assert outcome["FSTPD30"] is None
            assert dpd_values == [None, None, None]
            continue
        expected = int(any(value is not None and value >= 30 for value in dpd_values))
        assert outcome["FSTPD30"] == expected
        rates[case.segments["bureau_band"]].append(expected)

    # The fixed seed is deliberately designed to produce a visible, monotonic
    # relationship between adverse bureau profile and subsequent synthetic FSTPD30.
    ordered = ("GE_700", "640_699", "600_639", "LT_600")
    band_rates = [sum(rates[band]) / len(rates[band]) for band in ordered]
    assert band_rates == sorted(band_rates)
    assert band_rates[-1] > band_rates[0] * 3

    # Historical default counts and higher open-loan bands must also carry a
    # visibly higher synthetic early-delinquency incidence on this fixed seed.
    default_rates: dict[str, list[int]] = defaultdict(list)
    open_loan_rates: dict[str, list[int]] = defaultdict(list)
    for case in cases:
        target = case.outcome_snapshot["FSTPD30"]
        if target is None:
            continue
        default_rates[str(case.segments["bureau_historical_defaults"])].append(target)
        open_loan_rates[str(case.segments["open_loan_band"])].append(target)
    assert mean(default_rates["0"]) < mean(default_rates["1"]) < mean(default_rates["2"])
    ordered_loan_bands = ("1_2", "3_5", "6_8", "9_PLUS")
    loan_rates = [mean(open_loan_rates[band]) for band in ordered_loan_bands]
    assert loan_rates == sorted(loan_rates)


def test_aidflow_profile_deciles_show_expected_inverse_ar_dr_relationship() -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    cases = list(generate_cases(count=2000, seed=17, as_of_date=date(2026, 11, 23)))
    scored: list[tuple[int, int, str]] = []
    for case in cases:
        result = evaluate_case(case, runtime)
        target = case.outcome_snapshot["FSTPD30"]
        score = result.get("profile_score")
        if target is not None and isinstance(score, int):
            scored.append((score, target, str(result["decision"])))
    scored.sort(key=lambda row: row[0])
    quartiles = [
        scored[index * len(scored) // 4 : (index + 1) * len(scored) // 4] for index in range(4)
    ]
    risk_rates = [sum(row[1] for row in group) / len(group) for group in quartiles]
    approval_rates = [
        sum(row[2] in {"APPROVED", "COUNTEROFFER"} for row in group) / len(group)
        for group in quartiles
    ]
    assert risk_rates[0] > risk_rates[-1] * 5
    assert approval_rates[0] < approval_rates[-1] * 0.25


def test_comparison_writes_cro_report_stage_distributions_and_fstpd30(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    baseline_rows = []
    candidate_rows = []
    scenarios = (
        ("APP-1", 1, "APPROVED", "DECLINED", 560, 0),
        ("APP-2", 0, "APPROVED", "APPROVED", 730, 1),
        ("APP-3", 0, "DECLINED", "APPROVED", 810, 1),
    )
    for application_id, target, old_decision, new_decision, score, amount_factor in scenarios:
        common = {
            "application_id": application_id,
            "dataset_id": "synthetic-eur-v4-fstpd30-test",
            "dataset_sha256": "a" * 64,
            "runtime_release": "2.0.0",
            "runtime_manifest_sha256": "b" * 64,
            "profile_score": score,
            "approved_amount": 1000 if amount_factor else 0,
            "hard_gate_passed": True,
            "source_plan_ids": ["bd_telco"],
            "segments": {"bureau_band": "600_639", "bureau_historical_defaults": "1"},
            "stage_results": _stage_results(
                "APPROVED" if old_decision == "APPROVED" else "REJECTED"
            ),
            "outcome": {
                "outcome_status": "MATURED",
                "target_name": "FSTPD30",
                "FSTPD30": target,
                "first_payment_days_past_due": 35 if target else 0,
                "second_payment_days_past_due": 0,
                "third_payment_days_past_due": 0,
                "label_type": "SYNTHETIC_COUNTERFACTUAL_FSTPD30_NOT_BOOKED_LOAN_PERFORMANCE",
            },
        }
        old = {**common, "decision": old_decision}
        new = {
            **common,
            "decision": new_decision,
            "runtime_release": "dev-1234567890abcdef",
            "runtime_manifest_sha256": "c" * 64,
            "stage_results": _stage_results(
                "APPROVED" if new_decision == "APPROVED" else "REJECTED"
            ),
        }
        baseline_rows.append(old)
        candidate_rows.append(new)

    baseline_path.write_text(
        "".join(json.dumps(row) + "\n" for row in baseline_rows), encoding="utf-8"
    )
    candidate_path.write_text(
        "".join(json.dumps(row) + "\n" for row in candidate_rows), encoding="utf-8"
    )

    output = tmp_path / "comparison"
    summary = compare_batches(baseline_path, candidate_path, output)
    impact = summary["portfolio_impact"]
    assert impact["target"]["name"] == "FSTPD30"
    assert abs(impact["champion"]["strict_approval_rate"] - (2 / 3)) < 1e-6
    assert abs(impact["challenger"]["strict_approval_rate"] - (2 / 3)) < 1e-6
    assert impact["champion"]["FSTPD30_rate_on_offers"] == 0.5
    assert impact["challenger"]["FSTPD30_rate_on_offers"] == 0.0
    assert len(impact["stage_analysis"]) == 6
    assert impact["stage_analysis"]["stage6_uwflow"]["champion"]["outcome_counts"]["APPROVED"] == 2
    assert (
        impact["stage_analysis"]["stage6_uwflow"]["challenger"]["outcome_counts"]["REJECTED"] == 1
    )
    assert (
        abs(
            impact["stage_analysis"]["stage6_uwflow"]["champion"]["outcome_distribution"][
                "APPROVED"
            ]
            - 2 / 3
        )
        < 1e-5
    )
    assert (
        abs(
            impact["stage_analysis"]["stage6_uwflow"]["champion"][
                "outcome_distribution_of_entered"
            ]["APPROVED"]
            - 2 / 3
        )
        < 1e-5
    )
    assert (
        impact["stage_analysis"]["stage6_uwflow"]["champion"]["FSTPD30_risk_population"]
        == "APPROVED_ONLY"
    )
    assert (
        impact["stage_analysis"]["stage6_uwflow"]["champion"]["FSTPD30_risk_population_count"] == 2
    )
    assert (
        abs(
            impact["stage_analysis"]["stage1_hard_gates"]["champion"][
                "final_approval_rate_of_entrants"
            ]
            - (2 / 3)
        )
        < 1e-6
    )
    assert (
        impact["stage_analysis"]["stage2_bureau"]["champion"]["final_approval_count_of_entrants"]
        == 2
    )
    assert (
        abs(
            impact["stage_analysis"]["stage6_uwflow"]["champion"]["final_approval_rate_of_entrants"]
            - (2 / 3)
        )
        < 1e-6
    )
    assert len(impact["source_coverage"]) == 20  # ten configured sources for both policies
    assert len(impact["score_deciles"]) == 20
    assert all(
        "FSTPD30_rate_approved" in row and "FSTPD30_rate_offered" in row
        for row in impact["score_deciles"]
    )
    assert impact["assessment"] == "UNCHANGED_APPROVAL_LOWER_FSTPD30"
    assert "FSTPD30_metrics_by_label_type" in summary["outcome_validation"]

    expected_files = (
        "comparison.json",
        "case_comparison.csv",
        "decision_migrations.csv",
        "stage_comparison.csv",
        "score_deciles.csv",
        "segment_impact.csv",
        "source_coverage.csv",
        "champion_challenger_report.html",
        "champion_challenger_report.pdf",
    )
    assert all((output / name).is_file() for name in expected_files)
    assert (output / "champion_challenger_report.pdf").read_bytes().startswith(b"%PDF-1.")
    html = (output / "champion_challenger_report.html").read_text(encoding="utf-8")
    assert "Stage 1 - Input validation" in html
    assert "Stage 6 - UWflow decision" in html
    assert "FSTPD30" in html
    assert "Approval rate (APPROVED only)" in html
    assert "Final approval rate among stage entrants" in html
    assert "FSTPD30 approved events / labels" in html
    assert "FSTPD30 events / matured labels" in html
    assert (
        "FSTPD30 among approved (events / labels)" in html or "FSTPD30 rate among approved" in html
    )
    with (output / "case_comparison.csv").open(encoding="utf-8", newline="") as handle:
        columns = next(csv.reader(handle))
    assert "FSTPD30" in columns
    assert "baseline_stage1_hard_gates_outcome" in columns
    assert "challenger_stage6_uwflow_outcome" in columns
    assert summary["report_artifacts"] == [
        "champion_challenger_report.html",
        "champion_challenger_report.pdf",
        "stage_comparison.csv",
        "score_deciles.csv",
        "segment_impact.csv",
        "source_coverage.csv",
    ]


def test_replay_trace_attributes_upstream_rejections_to_the_correct_stage() -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    cases = list(generate_cases(count=500, seed=29, as_of_date=date(2026, 11, 23)))

    hard_gate_case = next(
        case
        for case in cases
        if not runtime["modules"]["hard_gates"]
        .evaluate_hard_gates(case.application)
        .get("passed", False)
    )
    hard_gate_result = evaluate_case(hard_gate_case, runtime)
    assert hard_gate_result["decision"] == "DECLINED"
    assert hard_gate_result["stage_results"]["stage1_hard_gates"]["outcome"] == "REJECTED"
    assert hard_gate_result["stage_results"]["stage6_uwflow"]["outcome"] == "NOT_REACHED"
    assert hard_gate_result["stage_results"]["stage6_uwflow"]["reached"] is False

    bureau_reject_case = next(
        case
        for case in cases
        if runtime["modules"]["hard_gates"]
        .evaluate_hard_gates(case.application)
        .get("passed", False)
        and case.bureau_snapshot.get("decision_status") == "DECLINE"
    )
    bureau_result = evaluate_case(bureau_reject_case, runtime)
    assert bureau_result["stage_results"]["stage2_bureau"]["outcome"] == "REJECTED"
    assert bureau_result["stage_results"]["stage6_uwflow"]["outcome"] == "NOT_REACHED"
    assert bureau_result["stage_results"]["stage6_uwflow"]["reached"] is False

    fully_eligible = next(
        case
        for case in cases
        if runtime["modules"]["hard_gates"]
        .evaluate_hard_gates(case.application)
        .get("passed", False)
        and case.bureau_snapshot.get("decision_status") == "PASS"
        and case.application.get("data_sharing_consent")
        and case.outcome_snapshot.get("synthetic_withdrawal_stage") is None
    )
    complete_result = evaluate_case(fully_eligible, runtime)
    assert set(complete_result["stage_results"]) == set(STAGES)
    assert (
        complete_result["stage_results"]["stage3_source_plan"]["outcome"] == "ROUTED_TO_COLLECTION"
    )
    assert complete_result["stage_results"]["stage4_data_collection"]["outcome"] == "COMPLETE"
    assert complete_result["stage_results"]["stage5_aidflow"]["outcome"] == "SCORED"


def test_candidate_profile_cutoff_produces_logical_approval_risk_tradeoff(tmp_path: Path) -> None:
    """A stricter AIDflow-score acceptance cutoff lowers approval and FSTPD30.

    AIDflow owns score inference; the acceptance cutoff is UWflow decision
    policy. This test changes only that candidate policy threshold and replays
    exactly the same counterfactual snapshots through both immutable runtimes.
    """
    champion_root = ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0"
    candidate_root = tmp_path / "candidate-runtime"
    shutil.copytree(champion_root, candidate_root)

    engine_path = candidate_root / "uwflow_engine.py"
    engine_source = engine_path.read_text(encoding="utf-8")
    assert engine_source.count("if profile_score < 620:") == 1
    assert engine_source.count('"minimum": 620') == 2
    candidate_source = engine_source.replace("if profile_score < 620:", "if profile_score < 840:")
    candidate_source = candidate_source.replace('"minimum": 620', '"minimum": 840')
    engine_path.write_text(candidate_source, encoding="utf-8")

    manifest_path = candidate_root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_version"] = "dev-cutoff-840-test"
    manifest["source_ref"] = "synthetic-policy-sensitivity-test"
    manifest["files"]["uwflow_engine.py"] = hashlib.sha256(engine_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    champion_runtime = load_runtime(champion_root)
    challenger_runtime = load_runtime(candidate_root)
    cases = list(generate_cases(count=10_000, seed=17, as_of_date=date(2026, 11, 23)))
    champion_rows = [evaluate_case(case, champion_runtime) for case in cases]
    challenger_rows = [evaluate_case(case, challenger_runtime) for case in cases]

    impact = build_impact_analysis(champion_rows, challenger_rows)
    champion = impact["champion"]
    challenger = impact["challenger"]

    assert challenger["strict_approval_rate"] < champion["strict_approval_rate"]
    assert challenger["FSTPD30_rate_on_approved"] < champion["FSTPD30_rate_on_approved"]
    assert challenger["offer_rate"] < champion["offer_rate"]
    assert challenger["FSTPD30_rate_on_offers"] < champion["FSTPD30_rate_on_offers"]
    assert impact["assessment"] == "LOWER_APPROVAL_LOWER_FSTPD30_TRADE_OFF"

    # Reversing the same pair represents the more permissive cutoff: more
    # approvals, accompanied by more FSTPD30 incidence in this fixed portfolio.
    reverse = build_impact_analysis(challenger_rows, champion_rows)
    assert (
        reverse["challenger"]["strict_approval_rate"] > reverse["champion"]["strict_approval_rate"]
    )
    assert (
        reverse["challenger"]["FSTPD30_rate_on_approved"]
        > reverse["champion"]["FSTPD30_rate_on_approved"]
    )
    assert reverse["assessment"] == "APPROVAL_RISK_TRADE_OFF"
