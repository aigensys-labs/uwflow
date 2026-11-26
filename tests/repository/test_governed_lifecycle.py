"""Tests for workspace, candidate, evaluation, approval and release lifecycle boundaries."""

from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path
import pytest

from modules.lifecycle.workspaces import WorkspaceStore
from modules.production.tools.release.assemble_approved_release import (
    ReleaseAssemblyError,
    assemble_approved_release,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_core_foundation(root: Path) -> None:
    shutil.copytree(ROOT / "core/underwriting/policies", root / "core/underwriting/policies")
    flow = root / "core/kestra/flows/uwflow_production_underwriting.yaml"
    flow.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml", flow)
    shutil.copytree(ROOT / "core/python/runtime", root / "core/python/runtime")


def _make_candidate(root: Path, candidate_id: str = "dev-0123456789abcdef") -> Path:
    candidate = root / "var/artifacts/candidates" / candidate_id
    (candidate / "policy-specs").mkdir(parents=True)
    for filename in ("stage1_hard_gates.json", "stage3_source_plan.json"):
        shutil.copyfile(
            ROOT / "core/underwriting/policies/stages" / filename,
            candidate / "policy-specs" / filename,
        )
    for source in (ROOT / "core/python/runtime").glob("*.py"):
        shutil.copyfile(source, candidate / source.name)
    template = candidate / "production-flow-template.yaml"
    shutil.copyfile(ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml", template)
    (candidate / "candidate-flow.yaml").write_text(f"id: uwflow_dev_candidate_{candidate_id[4:]}\n")
    manifest = {
        "manifest_format": 1,
        "candidate_id": candidate_id,
        "environment": "DEV",
        "workspace_id": "strategy-parent",
        "based_on_production_release": "2.0.0",
        "production_flow_template_sha256": _sha(template),
        "policy_specs": {
            name: _sha(candidate / "policy-specs" / name)
            for name in ("stage1_hard_gates.json", "stage3_source_plan.json")
        },
        "core_runtime": {
            "platform_version": "2.0.0",
            "module_hashes": {path.name: _sha(path) for path in candidate.glob("*.py")},
        },
    }
    manifest_path = candidate / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    files = {
        path.relative_to(candidate).as_posix(): _sha(path)
        for path in candidate.rglob("*")
        if path.is_file()
    }
    artifact_manifest = {
        "artifact_format": 1,
        "candidate_id": candidate_id,
        "release_manifest_sha256": _sha(manifest_path),
        "files": files,
    }
    (candidate / "candidate-artifact-manifest.json").write_text(
        json.dumps(artifact_manifest, sort_keys=True), encoding="utf-8"
    )
    return candidate


def _make_approved_release(root: Path, release_id: str = "2.0.7") -> Path:
    candidate = _make_candidate(root)
    candidate_manifest_path = candidate / "release-manifest.json"
    candidate_artifact_manifest_path = candidate / "candidate-artifact-manifest.json"
    candidate_manifest_bytes = candidate_manifest_path.read_bytes()
    candidate_artifact_manifest_bytes = candidate_artifact_manifest_path.read_bytes()
    release = root / "var/releases/approved" / release_id
    runtime = release / "runtime"
    policy_dir = release / "policy-specs"
    runtime.mkdir(parents=True)
    policy_dir.mkdir()
    for source in (ROOT / "core/python/runtime").glob("*.py"):
        shutil.copyfile(source, runtime / source.name)
    for filename in ("stage1_hard_gates.json", "stage3_source_plan.json"):
        shutil.copyfile(
            ROOT / "core/underwriting/policies/stages" / filename, policy_dir / filename
        )
    runtime_files = {path.name: _sha(path) for path in runtime.glob("*.py")}
    runtime_manifest_path = runtime / "release-manifest.json"
    runtime_manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "uwflow-kestra-runtime",
                "manifest_format": 1,
                "release_version": release_id,
                "files": runtime_files,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    flow = release / "production-flow.yaml"
    shutil.copyfile(ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml", flow)
    (release / "candidate-manifest.json").write_bytes(candidate_manifest_bytes)
    (release / "candidate-artifact-manifest.json").write_bytes(candidate_artifact_manifest_bytes)
    approval = {
        "status": "approved",
        "candidate_id": "dev-0123456789abcdef",
        "candidate_manifest_sha256": hashlib.sha256(candidate_manifest_bytes).hexdigest(),
        "evaluation_id": "eval-test",
        "approved_by": "test-approver",
        "approved_at": "2026-11-25T10:00:00Z",
    }
    approval_path = release / "approval-reference.json"
    approval_path.write_text(json.dumps(approval, sort_keys=True) + "\n", encoding="utf-8")
    evidence = release / "evidence.json"
    evidence.write_text('{"cases": 10}\n', encoding="utf-8")
    evaluation_files = {"evidence.json": _sha(evidence)}
    evaluation_manifest = {
        "evaluation_format": 1,
        "evaluation_id": "eval-test",
        "candidate_id": "dev-0123456789abcdef",
        "candidate_manifest_sha256": hashlib.sha256(candidate_manifest_bytes).hexdigest(),
        "baseline_release": "2.0.0",
        "dataset_id": "dataset-test",
        "files": evaluation_files,
    }
    evaluation_manifest_path = root / "var/artifacts/evaluations/eval-test/evaluation-manifest.json"
    evaluation_manifest_path.parent.mkdir(parents=True)
    evaluation_manifest_path.write_text(
        json.dumps(evaluation_manifest, sort_keys=True), encoding="utf-8"
    )
    evaluation_reference = {
        "evaluation_id": "eval-test",
        "evaluation_manifest_sha256": _sha(evaluation_manifest_path),
        "files": evaluation_files,
    }
    evaluation_reference_path = release / "evaluation-reference.json"
    evaluation_reference_path.write_text(
        json.dumps(evaluation_reference, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "release_format": 1,
        "release_id": release_id,
        "candidate_id": "dev-0123456789abcdef",
        "candidate_manifest_sha256": hashlib.sha256(candidate_manifest_bytes).hexdigest(),
        "candidate_artifact_manifest_sha256": hashlib.sha256(
            candidate_artifact_manifest_bytes
        ).hexdigest(),
        "strategy_workspace_id": "strategy-origin",
        "evaluation_id": "eval-test",
        "evaluation_manifest_sha256": _sha(evaluation_manifest_path),
        "evaluation_files": evaluation_files,
        "approval_sha256": _sha(approval_path),
        "evaluation_reference_sha256": _sha(evaluation_reference_path),
        "core_runtime": {"platform_version": "2.0.0", "module_hashes": runtime_files},
        "runtime_manifest_sha256": _sha(runtime_manifest_path),
        "production_flow_sha256": _sha(flow),
    }
    (release / "release-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return release


def test_fork_candidate_creates_independent_workspace_with_parent_hash(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _copy_core_foundation(root)
    candidate_id = "dev-0123456789abcdef"
    candidate = _make_candidate(root, candidate_id)
    store = WorkspaceStore(root)
    fork = store.fork("candidate", candidate_id, "Fork for analyst")
    copied = (
        root
        / "var/workspaces/strategies"
        / fork["workspace_id"]
        / "policy-specs/stage1_hard_gates.json"
    )
    assert copied.read_bytes() == (candidate / "policy-specs/stage1_hard_gates.json").read_bytes()
    assert fork["source"]["type"] == "candidate"
    assert fork["source"]["id"] == candidate_id
    assert fork["parent_workspace_id"] == "strategy-parent"
    assert fork["core_runtime"]["runtime_source_path"] == f"var/artifacts/candidates/{candidate_id}"
    assert (candidate / "release-manifest.json").is_file()


def test_fork_approved_release_pins_runtime_and_flow_without_copying_source_runtime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    _copy_core_foundation(root)
    release_id = "2.0.7"
    release = _make_approved_release(root, release_id)
    manifest_bytes = (release / "release-manifest.json").read_bytes()

    store = WorkspaceStore(root)
    fork = store.fork("approved-release", release_id, "Start from approved release")
    workspace_root = root / "var/workspaces/strategies" / fork["workspace_id"]
    metadata = json.loads((workspace_root / "workspace.json").read_text())

    assert fork["source"]["type"] == "approved-release"
    assert fork["source"]["id"] == release_id
    assert fork["source"]["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert metadata["parent_workspace_id"] == "strategy-origin"
    assert (
        metadata["core_runtime"]["runtime_source_path"]
        == f"var/releases/approved/{release_id}/runtime"
    )
    assert (
        metadata["flow_template_source_path"]
        == f"var/releases/approved/{release_id}/production-flow.yaml"
    )
    assert (workspace_root / "policy-specs/stage1_hard_gates.json").read_bytes() == (
        release / "policy-specs/stage1_hard_gates.json"
    ).read_bytes()
    assert not (workspace_root / "runtime").exists()
    assert (release / "runtime/release-manifest.json").is_file()


def test_release_assembler_rejects_unverified_core_source(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    candidate_id = "dev-0123456789abcdef"
    candidate = root / "var/artifacts/candidates" / candidate_id
    candidate.mkdir(parents=True)
    (candidate / "release-manifest.json").write_text(
        json.dumps(
            {
                "manifest_format": 1,
                "candidate_id": candidate_id,
                "environment": "DEV",
                "core_source_tree_status": "dirty",
            }
        )
    )
    with pytest.raises(ReleaseAssemblyError, match="clean Git tree"):
        assemble_approved_release(
            root,
            candidate_id,
            "2.0.1",
            root / "approval.json",
            "registry.example/uwflow-core@sha256:" + "a" * 64,
        )


def test_evaluation_registration_is_immutable_and_candidate_bound(tmp_path: Path) -> None:
    from modules.evaluation.tools.register_evaluation import (
        register_evaluation,
        EvaluationRegistrationError,
    )

    root = tmp_path / "repo"
    candidate_id = "dev-0123456789abcdef"
    _copy_core_foundation(root)
    _make_candidate(root, candidate_id)
    source = root / "var/reports/evaluation"
    source.mkdir(parents=True)
    (source / "comparison.json").write_text('{"cases": 10}')
    with pytest.raises(
        EvaluationRegistrationError, match="does not match the candidate's recorded parent baseline"
    ):
        register_evaluation(
            root, "eval-wrong-baseline", candidate_id, "2.0.1", "dataset-001", source
        )
    assert not (root / "var/artifacts/evaluations/eval-wrong-baseline").exists()
    result = register_evaluation(
        root, "eval-test-001", candidate_id, "2.0.0", "dataset-001", source
    )
    target = root / result["path"]
    assert (target / "evaluation-manifest.json").is_file()
    with pytest.raises(EvaluationRegistrationError, match="immutable"):
        register_evaluation(root, "eval-test-001", candidate_id, "2.0.0", "dataset-001", source)


def test_approved_release_fork_rejects_tampered_approval_reference(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _copy_core_foundation(root)
    release = _make_approved_release(root)
    (release / "approval-reference.json").write_text('{"status":"approved"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="approval-reference checksum mismatch"):
        WorkspaceStore(root)._verify_approved_release("2.0.7")


def test_approved_release_fork_rejects_tampered_candidate_manifest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _copy_core_foundation(root)
    release = _make_approved_release(root)
    candidate_manifest = release / "candidate-manifest.json"
    candidate_manifest.write_text('{"candidate_id":"dev-ffffffffffffffff"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="candidate manifest identity/checksum mismatch"):
        WorkspaceStore(root)._verify_approved_release("2.0.7")


def test_evaluation_registration_rejects_incomplete_candidate(tmp_path: Path) -> None:
    from modules.evaluation.tools.register_evaluation import (
        EvaluationRegistrationError,
        register_evaluation,
    )

    root = tmp_path / "repo"
    candidate_id = "dev-0123456789abcdef"
    candidate = root / "var/artifacts/candidates" / candidate_id
    candidate.mkdir(parents=True)
    (candidate / "release-manifest.json").write_text(
        json.dumps({"candidate_id": candidate_id}), encoding="utf-8"
    )
    source = root / "var/reports/evaluation"
    source.mkdir(parents=True)
    (source / "comparison.json").write_text('{"cases": 10}', encoding="utf-8")

    with pytest.raises(EvaluationRegistrationError, match="complete verified v2 artifact"):
        register_evaluation(root, "eval-test-001", candidate_id, "2.0.0", "dataset-001", source)
