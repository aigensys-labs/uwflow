"""Tests for paired historical replay inputs, outputs and evidence handling."""

from __future__ import annotations

from datetime import date
from dataclasses import replace
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

from tools.history.replay import run_batch as run_history_batch
from tools.history.replay.compare_batches import HistoryComparisonError, compare_batches
from tools.history.replay.run_batch import (
    HistoryReplayError,
    evaluate_case,
    load_runtime,
    verify_runtime_bundle,
)
from uwflow_history.generation.synthetic_portfolio import generate_cases


def test_runtime_manifest_hash_can_be_pinned(tmp_path: Path) -> None:
    runtime_root = ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0"
    metadata = verify_runtime_bundle(runtime_root)
    assert (
        verify_runtime_bundle(
            runtime_root,
            expected_manifest_sha256=metadata["runtime_manifest_sha256"],
        )
        == metadata
    )
    with pytest.raises(HistoryReplayError, match="pinned"):
        verify_runtime_bundle(runtime_root, expected_manifest_sha256="0" * 64)


def test_pinned_runtime_evaluates_historical_case_without_regeneration() -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    case = next(generate_cases(count=1, seed=17, as_of_date=date(2026, 11, 22)))
    result = evaluate_case(case, runtime)
    assert result["application_id"] == case.application_id
    assert result["hard_gate_passed"] is False  # deterministic first boundary case: age 17
    assert result["bureau_decision_status"] == "NOT_ASSESSED"
    assert result["bureau_snapshot_used"] is False
    assert result["outcome"]["label_type"].startswith("SYNTHETIC_COUNTERFACTUAL")
    assert result["recorded_decision_snapshot"] is None
    assert "runtime_manifest_sha256" not in result  # added by run_batch, not the pure evaluator


def test_run_batch_streams_rows_and_records_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sqlalchemy import create_engine
    from uwflow_history.connectors.postgres import PostgresHistoryStore
    from uwflow_history.contracts import DatasetManifest
    from uwflow_history.canonical import update_case_digest
    import hashlib
    from dataclasses import replace

    cases = list(generate_cases(count=4, seed=29, as_of_date=date(2026, 11, 22)))
    manifest = DatasetManifest(
        dataset_id="replay-test",
        display_name="Replay test",
        case_count=len(cases),
        created_at="2026-11-22T10:00:00Z",
        as_of_timestamp="2026-11-22T23:59:59Z",
        history_start="2025-11-22T00:00:00Z",
        history_end="2026-11-22T23:59:59Z",
        synthetic=True,
        source_snapshot_semantics="SYNTHETIC_CONSENTED_FIXTURE_AVAILABILITY",
        outcome_definition="synthetic counterfactual test labels",
    )
    digest = hashlib.sha256()
    for case in cases:
        update_case_digest(digest, case.to_dict())
    manifest = replace(manifest, data_sha256=digest.hexdigest())

    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    writer.write_dataset(manifest, cases)
    reader = PostgresHistoryStore(engine=engine, read_only=True)
    monkeypatch.setattr(run_history_batch, "create_history_source", lambda: reader)

    output = tmp_path / "replay.jsonl"
    result = run_history_batch.run_batch(
        dataset_id="replay-test",
        runtime_root=ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0",
        output_path=output,
        batch_size=2,
        max_cases=0,
    )
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 4
    assert result["batch_count"] == 4
    assert result["dataset_sha256"] == manifest.data_sha256
    assert output.with_suffix(".jsonl.manifest.json").is_file()
    reader.close()
    writer.close()


def test_comparison_rejects_invalid_dataset_checksum(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline-invalid.jsonl"
    candidate = tmp_path / "candidate-invalid.jsonl"
    row = {
        "application_id": "SYN-1",
        "dataset_id": "test-dataset",
        "dataset_sha256": "not-a-hash",
        "runtime_release": "2.0.0",
        "runtime_manifest_sha256": "b" * 64,
        "outcome": {},
    }
    baseline.write_text(json.dumps(row) + "\n")
    candidate.write_text(json.dumps({**row, "runtime_release": "dev-1"}) + "\n")
    with pytest.raises(HistoryComparisonError, match="valid dataset SHA-256"):
        compare_batches(baseline, candidate, tmp_path / "invalid-checksum")


def test_comparison_separates_synthetic_counterfactual_labels(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    common = {
        "dataset_id": "test-dataset",
        "dataset_sha256": "a" * 64,
        "runtime_release": "2.0.0",
        "runtime_manifest_sha256": "b" * 64,
        "profile_score": 700,
        "approved_amount": 1000,
        "hard_gate_passed": True,
        "source_plan_ids": ["bd_telco"],
        "hard_gate_trace": [],
        "source_plan_trace": [],
        "segments": {"income_band": "2000_3499"},
        "recorded_decision_snapshot": None,
        "outcome": {
            "outcome_status": "MATURED",
            "default_12m": False,
            "label_type": "SYNTHETIC_COUNTERFACTUAL_NOT_BOOKED_LOAN_PERFORMANCE",
        },
    }
    old = {**common, "application_id": "SYN-1", "decision": "APPROVED"}
    new = {
        **common,
        "application_id": "SYN-1",
        "decision": "DECLINED",
        "runtime_release": "dev-1",
        "runtime_manifest_sha256": "c" * 64,
    }
    baseline.write_text(json.dumps(old) + "\n")
    candidate.write_text(json.dumps(new) + "\n")
    report = compare_batches(baseline, candidate, tmp_path / "report")
    metrics = report["outcome_validation"]["metrics_by_label_type"][
        "SYNTHETIC_COUNTERFACTUAL_NOT_BOOKED_LOAN_PERFORMANCE"
    ]
    assert metrics["labelled_cases"] == 1
    assert metrics["candidate_offer_labelled_cases"] == 0
    assert (
        "Only independently observed, matured outcomes"
        in report["outcome_validation"]["interpretation"]
    )


def test_comparison_rejects_different_outcome_snapshots(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    row = {
        "application_id": "SYN-1",
        "dataset_id": "test-dataset",
        "dataset_sha256": "a" * 64,
        "runtime_release": "2.0.0",
        "runtime_manifest_sha256": "b" * 64,
        "outcome": {"default_12m": False},
    }
    baseline.write_text(json.dumps(row) + "\n")
    candidate.write_text(json.dumps({**row, "outcome": {"default_12m": True}}) + "\n")
    with pytest.raises(HistoryComparisonError, match="Outcome snapshot differs"):
        compare_batches(baseline, candidate, tmp_path / "bad-report")


def test_replay_uses_recorded_bureau_snapshot_and_never_calls_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    case = next(generate_cases(count=1, seed=17, as_of_date=date(2026, 11, 22)))
    eligible_case = replace(
        case,
        application={**case.application, "applicant_age": 34},
    )

    def forbidden_adapter(*args, **kwargs):
        raise AssertionError("Historical replay must not regenerate bureau data")

    monkeypatch.setattr(runtime["modules"]["bureau_client"], "get_bureau_data", forbidden_adapter)
    result = evaluate_case(eligible_case, runtime)
    assert result["hard_gate_passed"] is True
    assert result["bureau_snapshot_used"] is True
    assert result["bureau_snapshot_id"] == case.bureau_snapshot["snapshot_id"]
    assert result["bureau_score"] == case.bureau_snapshot["bureau_score"]


def test_replay_skips_bureau_after_hard_gate_failure_without_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    case = next(generate_cases(count=1, seed=17, as_of_date=date(2026, 11, 22)))

    def forbidden_adapter(*args, **kwargs):
        raise AssertionError("Historical replay must never call a synthetic bureau adapter")

    monkeypatch.setattr(runtime["modules"]["bureau_client"], "get_bureau_data", forbidden_adapter)
    result = evaluate_case(case, runtime)
    assert result["hard_gate_passed"] is False
    assert result["bureau_decision_status"] == "NOT_ASSESSED"
    assert result["bureau_snapshot_used"] is False


def test_missing_historical_bureau_for_eligible_application_is_referred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    case = next(
        item
        for item in generate_cases(count=100, seed=431, as_of_date=date(2026, 11, 22))
        if runtime["modules"]["hard_gates"]
        .evaluate_hard_gates(item.application)
        .get("passed", False)
    )
    case_without_bureau = replace(case, bureau_snapshot=None)

    def forbidden_adapter(*args, **kwargs):
        raise AssertionError("Historical replay must never regenerate a missing bureau response")

    monkeypatch.setattr(runtime["modules"]["bureau_client"], "get_bureau_data", forbidden_adapter)
    result = evaluate_case(case_without_bureau, runtime)

    assert result["hard_gate_passed"] is True
    assert result["bureau_decision_status"] == "REFER"
    assert result["bureau_snapshot_missing"] is True
    assert result["bureau_snapshot_used"] is False
    assert result["decision"] == "REFER"
    assert "HISTORICAL_BUREAU_SNAPSHOT_UNAVAILABLE" in result["bureau_reason_codes"]
    assert "BUREAU_DATA_UNAVAILABLE" in result["reason_codes"]


def test_historical_bureau_snapshot_must_belong_to_application() -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    case = next(generate_cases(count=100, seed=531, as_of_date=date(2026, 11, 22)))
    if (
        not runtime["modules"]["hard_gates"]
        .evaluate_hard_gates(case.application)
        .get("passed", False)
    ):
        case = next(
            item
            for item in generate_cases(count=100, seed=531, as_of_date=date(2026, 11, 22))
            if runtime["modules"]["hard_gates"]
            .evaluate_hard_gates(item.application)
            .get("passed", False)
        )
    mismatched = replace(
        case,
        bureau_snapshot={**case.bureau_snapshot, "applicant_id": "SYN-WRONG-APPLICANT"},
    )
    with pytest.raises(HistoryReplayError, match="does not match"):
        evaluate_case(mismatched, runtime)


def test_failed_historical_bureau_snapshot_fails_closed_to_refer() -> None:
    runtime = load_runtime(ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0")
    case = next(
        item
        for item in generate_cases(count=100, seed=631, as_of_date=date(2026, 11, 22))
        if runtime["modules"]["hard_gates"]
        .evaluate_hard_gates(item.application)
        .get("passed", False)
    )
    failed_snapshot = {
        "snapshot_id": "BUR-FAILED-1",
        "applicant_id": case.application_id,
        "status": "FAILED",
        "decision_status": "NOT_AVAILABLE",
        "retrieved_at": case.decision_timestamp,
        "reason_codes": ["PROVIDER_TIMEOUT"],
    }
    failed_case = replace(case, bureau_snapshot=failed_snapshot)
    result = evaluate_case(failed_case, runtime)
    assert result["decision"] == "REFER"
    assert result["bureau_snapshot_used"] is False
    assert result["bureau_snapshot_missing"] is True
    assert "PROVIDER_TIMEOUT" in result["bureau_reason_codes"]
