"""Tests for generated History tooling bundles and replay-flow contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

from modules.history.tools.history_tools_bundle import build_bundle, source_files
from modules.evaluation.tools.history_replay_flow import build_flow


def test_history_tooling_builder_preserves_the_virtual_namespace_files_path() -> None:
    files = source_files()
    assert "scripts/uwflow_history/__init__.py" in files
    assert "scripts/uwflow_history/contracts.py" in files
    assert "tools/run_history_batch.py" in files
    assert "tools/validate_history_dataset.py" in files


def test_history_tooling_bundle_is_content_addressed_and_verifiable(
    isolated_repository: Path,
) -> None:
    repo = isolated_repository
    bundle_id, path = build_bundle(repository_root=repo)
    assert bundle_id.startswith("ht-")
    assert (path / "release-manifest.json").is_file()
    checked_id, checked_path = build_bundle(check=True, repository_root=repo)
    assert checked_id == bundle_id
    assert checked_path == path


def test_dev_historical_replay_flow_is_manual_and_connector_configured(
    capsys, candidate_package: dict
) -> None:
    repo = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    flow_path = build_flow(candidate_id, baseline_release="2.0.0", repository_root=repo)
    command_output = capsys.readouterr().out
    assert "kestractl nsfiles upload" not in command_output
    assert "kestractl flows deploy" not in command_output
    assert "bash tools/guides/workflow/14-publish-history-replay-flow.sh" in command_output
    assert "uploads only missing Namespace Files paths" in command_output
    raw_flow = flow_path.read_text(encoding="utf-8")
    assert "&uwflow_" not in raw_flow
    assert "*uwflow_" not in raw_flow
    flow = yaml.safe_load(raw_flow)
    baseline_manifest = (
        repo / "core/kestra/namespace-files/runtime/releases/2.0.0/release-manifest.json"
    )
    candidate_manifest = repo / "var/artifacts/candidates" / candidate_id / "release-manifest.json"

    assert flow["namespace"] == "com.ai.credit.dev"
    assert "triggers" not in flow
    assert (
        flow["labels"]["baseline-manifest-sha256"]
        == hashlib.sha256(baseline_manifest.read_bytes()).hexdigest()
    )
    assert (
        flow["labels"]["candidate-manifest-sha256"]
        == hashlib.sha256(candidate_manifest.read_bytes()).hexdigest()
    )
    assert [task["id"] for task in flow["tasks"]] == [
        "validate_dataset",
        "replay_pair",
        "compare_replays",
    ]
    replay_pair = flow["tasks"][1]
    assert replay_pair["type"] == "io.kestra.plugin.core.flow.Parallel"
    assert replay_pair["concurrent"] == 2
    assert replay_pair["onChildFailure"] == "FAIL"
    assert [task["id"] for task in replay_pair["tasks"]] == ["baseline_replay", "candidate_replay"]
    assert all("dependsOn" not in task for task in replay_pair["tasks"])
    assert all("dependsOn" not in task for task in flow["tasks"])
    assert flow["tasks"][2]["inputFiles"]["baseline.jsonl"].startswith(
        "{{ outputs.baseline_replay.outputFiles["
    )
    assert flow["tasks"][2]["inputFiles"]["candidate.jsonl"].startswith(
        "{{ outputs.candidate_replay.outputFiles["
    )

    tasks_to_check = [flow["tasks"][0], *replay_pair["tasks"]]
    for task in tasks_to_check:
        assert task["taskRunner"]["networkMode"] == "uwflow-local"
        assert "{{ secret('UWFLOW_HISTORY_CONNECTOR') }}" in task["env"]["UWFLOW_HISTORY_CONNECTOR"]
        assert "{{ secret('UWFLOW_HISTORY_DSN') }}" in task["env"]["UWFLOW_HISTORY_DSN"]
        assert "{{ secret('UWFLOW_HISTORY_ROOT') }}" in task["env"]["UWFLOW_HISTORY_ROOT"]
        assert task["namespaceFiles"]["ifExists"] == "FAIL"
        assert task["containerImage"] == "ai/uwflow-runtime:2.0.0"
        assert task["env"]["APP_TASK_IMAGE"] == task["containerImage"]
        assert "dependencies" not in task
    assert "runtime/releases/2.0.0/**" in replay_pair["tasks"][0]["namespaceFiles"]["include"]
    assert (
        f"runtime/candidates/{candidate_id}/**"
        in replay_pair["tasks"][1]["namespaceFiles"]["include"]
    )
    assert (
        replay_pair["tasks"][0]["env"]["UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"]
        == flow["labels"]["baseline-manifest-sha256"]
    )
    assert (
        replay_pair["tasks"][1]["env"]["UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"]
        == flow["labels"]["candidate-manifest-sha256"]
    )
    assert all("com.ai.credit.production" not in str(task) for task in flow["tasks"])


def test_dev_flow_rejects_untrusted_runtime_path_identifiers(candidate_package: dict) -> None:
    import pytest

    repo = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    with pytest.raises(ValueError, match="candidate_id"):
        build_flow("../../production", baseline_release="2.0.0", repository_root=repo)
    with pytest.raises(ValueError, match="semantic"):
        build_flow(candidate_id, baseline_release="../prod", repository_root=repo)
    with pytest.raises(ValueError, match="built from baseline"):
        build_flow(candidate_id, baseline_release="2.0.1", repository_root=repo)


def test_dev_flow_can_mount_parquet_dataset_root(tmp_path: Path, candidate_package: dict) -> None:
    repo = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    host_root = tmp_path / "history data"
    flow_path = build_flow(
        candidate_id,
        baseline_release="2.0.0",
        parquet_host_root=host_root,
        repository_root=repo,
    )
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    assert flow["tasks"][0]["taskRunner"]["volumes"] == [f"{host_root}:/data/uwflow/history:ro"]
    replay_tasks = flow["tasks"][1]["tasks"]
    for task in replay_tasks:
        assert task["taskRunner"]["volumes"] == [f"{host_root}:/data/uwflow/history:ro"]
    assert "volumes" not in flow["tasks"][2]["taskRunner"]


def test_comparison_reconciles_replayed_decisions_to_original_record(tmp_path: Path) -> None:
    from tools.history.replay.compare_batches import compare_batches
    import json

    baseline = tmp_path / "baseline-recorded.jsonl"
    candidate = tmp_path / "candidate-recorded.jsonl"
    recorded = {
        "application_id": "APP-1",
        "decision_timestamp": "2026-01-01T10:00:00Z",
        "decision": "APPROVED",
        "policy_version": "UW-POLICY-1",
    }
    base = {
        "application_id": "APP-1",
        "dataset_id": "dataset-1",
        "dataset_sha256": "a" * 64,
        "runtime_release": "2.0.0",
        "runtime_manifest_sha256": "b" * 64,
        "decision": "APPROVED",
        "profile_score": 700,
        "approved_amount": 1000,
        "recorded_decision_snapshot": recorded,
        "outcome": {},
    }
    baseline.write_text(json.dumps(base) + "\n", encoding="utf-8")
    candidate.write_text(
        json.dumps(
            {
                **base,
                "decision": "REFER",
                "runtime_release": "dev-1",
                "runtime_manifest_sha256": "c" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = compare_batches(baseline, candidate, tmp_path / "recorded-report")
    reconciliation = report["historical_decision_reconciliation"]
    assert reconciliation["recorded_decision_cases"] == 1
    assert reconciliation["baseline_match_rate"] == 1.0
    assert reconciliation["candidate_match_rate"] == 0.0


def test_replay_builder_rejects_tampered_candidate_artifact(candidate_package: dict) -> None:
    import pytest

    repo = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    candidate = repo / "var/artifacts/candidates" / candidate_id / "candidate-flow.yaml"
    candidate.write_text("id: changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="complete verified v2 artifact"):
        build_flow(candidate_id, baseline_release="2.0.0", repository_root=repo)


def test_replay_builder_rejects_tampered_core_baseline_snapshot(candidate_package: dict) -> None:
    import pytest

    repo = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    runtime_file = repo / "core/kestra/namespace-files/runtime/releases/2.0.0/common.py"
    runtime_file.write_text("TAMPERED = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Core runtime snapshot checksum mismatch"):
        build_flow(candidate_id, baseline_release="2.0.0", repository_root=repo)
