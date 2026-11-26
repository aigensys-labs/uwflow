"""Tests for Policy Studio workspace, policy and candidate API endpoints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from studio.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def _temporary_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copytree(ROOT / "core/underwriting/policies", root / "core/underwriting/policies")
    shutil.copytree(ROOT / "core/python/runtime", root / "core/python/runtime")
    shutil.copytree(
        ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0",
        root / "core/kestra/namespace-files/runtime/releases/2.0.0",
    )
    flow = root / "core/kestra/flows/uwflow_production_underwriting.yaml"
    flow.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml", flow)
    return root


def test_workspace_list_initializes_default_workspace_lazily(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))
    workspace_root = root / "var" / "workspaces" / "strategies"
    assert not workspace_root.exists()

    response = client.get("/api/workspaces")

    assert response.status_code == 200
    assert response.json()["default_workspace_id"]
    assert len(response.json()["items"]) == 1
    assert workspace_root.is_dir()


def test_stage_catalogue_exposes_only_stage1_and_stage3_as_editable(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))

    response = client.get("/api/stages")

    assert response.status_code == 200
    stages = response.json()
    assert len(stages) == 7
    assert {stage["id"] for stage in stages if stage["editable"]} == {
        "stage_1_hard_gates",
        "stage_3_source_plan",
    }
    assert stages[4]["id"] == "stage_5_aidflow"
    assert stages[4]["status"] == "protected"


def test_protected_stage_cannot_be_opened_as_a_policy(tmp_path: Path) -> None:
    client = TestClient(create_app(_temporary_repository(tmp_path)))

    response = client.get("/api/policies/stage_5_aidflow")

    assert response.status_code == 403


def test_catalogue_is_stage_scoped(tmp_path: Path) -> None:
    client = TestClient(create_app(_temporary_repository(tmp_path)))

    response = client.get("/api/catalog/stage_3_source_plan")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["fields"]) == {
        "hard_gates_passed",
        "bureau_decision_status",
        "data_sharing_consent",
    }
    assert "telco_stability" in payload["source_ids"]


def test_valid_policy_can_be_validated_and_previewed_without_writing(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))
    loaded = client.get("/api/policies/stage_1_hard_gates").json()
    before = (root / "core/python/runtime" / "policy_generated.py").read_bytes()

    validation = client.post(
        "/api/policies/stage_1_hard_gates/validate",
        json={"spec": loaded["spec"]},
    )
    preview = client.post(
        "/api/policies/stage_1_hard_gates/preview",
        json={"spec": loaded["spec"]},
    )

    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert preview.status_code == 200
    assert "def evaluate_stage1_hard_gates" in preview.json()["code"]
    assert preview.json()["code"].encode() == before
    assert (
        hashlib.sha256(preview.json()["code"].encode()).hexdigest()
        == preview.json()["generated_sha256"]
    )
    assert (root / "core/python/runtime" / "policy_generated.py").read_bytes() == before


def test_invalid_field_is_rejected_by_the_allow_list(tmp_path: Path) -> None:
    client = TestClient(create_app(_temporary_repository(tmp_path)))
    loaded = client.get("/api/policies/stage_1_hard_gates").json()
    spec = loaded["spec"]
    spec["checks"][0]["field"] = "raw_bureau_payload"

    response = client.post(
        "/api/policies/stage_1_hard_gates/validate",
        json={"spec": spec},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "not in the allow-list" in response.json()["errors"][0]


def test_save_updates_only_policy_source_and_generated_module(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))
    loaded = client.get("/api/policies/stage_1_hard_gates").json()
    spec = loaded["spec"]
    spec["description"] = "Updated from a local studio test"

    response = client.put(
        "/api/policies/stage_1_hard_gates",
        json={"spec": spec, "expected_sha256": loaded["sha256"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    workspace_id = payload["workspace_id"]
    workspace = root / "var/workspaces/strategies" / workspace_id
    saved_spec = json.loads((workspace / "policy-specs/stage1_hard_gates.json").read_text())
    generated = (workspace / "generated/policy_generated.py").read_text()
    core_spec = json.loads(
        (root / "core/underwriting/policies/stages/stage1_hard_gates.json").read_text()
    )
    assert saved_spec["description"] == "Updated from a local studio test"
    assert core_spec["description"] != "Updated from a local studio test"
    assert "POLICY_METADATA" in generated
    assert payload["generated_sha256"] == hashlib.sha256(generated.encode()).hexdigest()


def test_stale_save_is_rejected_without_overwriting_current_policy(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))
    loaded = client.get("/api/policies/stage_3_source_plan").json()
    spec = loaded["spec"]
    spec["description"] = "A candidate update"
    wrong_hash = "0" * 64

    response = client.put(
        "/api/policies/stage_3_source_plan",
        json={"spec": spec, "expected_sha256": wrong_hash},
    )

    assert response.status_code == 409
    latest = client.get("/api/policies/stage_3_source_plan").json()
    assert latest["spec"]["description"] != "A candidate update"
    assert latest["sha256"] == loaded["sha256"]


def test_invalid_policy_cannot_be_saved(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))
    loaded = client.get("/api/policies/stage_3_source_plan").json()
    spec = loaded["spec"]
    spec["edges"] = [edge for edge in spec["edges"] if not edge["is_default"]]

    response = client.put(
        "/api/policies/stage_3_source_plan",
        json={"spec": spec, "expected_sha256": loaded["sha256"]},
    )

    assert response.status_code == 422
    latest = client.get("/api/policies/stage_3_source_plan").json()
    assert latest["sha256"] == loaded["sha256"]


def test_build_dev_candidate_prepares_local_only_candidate_artifacts(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))

    response = client.post("/api/dev-candidates/build", json={"baseline_release": "2.0.0"})

    assert response.status_code == 200
    candidate = response.json()
    assert candidate["dev_namespace"] == "com.ai.credit.dev"
    assert candidate["based_on_production_release"] == "2.0.0"
    assert "intended_production_release" not in candidate
    assert "runtime/candidates/" in candidate["candidate_commands"]
    assert "com.ai.credit.production" not in candidate["candidate_commands"]
    assert "kestractl nsfiles upload" in candidate["candidate_commands"]
    assert "--no-root" in candidate["candidate_commands"]
    assert "kestractl flows deploy" in candidate["candidate_commands"]

    bundle = root / candidate["bundle_relative_path"]
    flow = root / candidate["flow_relative_path"]
    assert (bundle / "release-manifest.json").is_file()
    assert flow.is_file()


def test_workspace_fork_preserves_source_and_creates_independent_copy(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    client = TestClient(create_app(root))
    created = client.post("/api/workspaces", json={"name": "Analyst experiment"})
    assert created.status_code == 200
    workspace = created.json()
    policy_path = (
        root
        / "var/workspaces/strategies"
        / workspace["workspace_id"]
        / "policy-specs/stage1_hard_gates.json"
    )
    assert policy_path.is_file()
    assert (root / "core/underwriting/policies/stages/stage1_hard_gates.json").is_file()


def test_studio_save_never_changes_core_runtime_or_policy(tmp_path: Path) -> None:
    root = _temporary_repository(tmp_path)
    core_policy = root / "core/underwriting/policies/stages/stage1_hard_gates.json"
    core_runtime = root / "core/python/runtime/policy_generated.py"
    before = (core_policy.read_bytes(), core_runtime.read_bytes())
    client = TestClient(create_app(root))
    loaded = client.get("/api/policies/stage_1_hard_gates").json()
    spec = loaded["spec"]
    spec["description"] = "Workspace-only change"
    response = client.put(
        "/api/policies/stage_1_hard_gates", json={"spec": spec, "expected_sha256": loaded["sha256"]}
    )
    assert response.status_code == 200
    assert (core_policy.read_bytes(), core_runtime.read_bytes()) == before
