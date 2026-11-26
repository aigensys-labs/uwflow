"""Tests for immutable DEV candidate construction and artifact manifests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import yaml

from modules.lifecycle.tools.dev_candidate import build_dev_candidate
from tools.policy.compiler import compile_specs

ROOT = Path(__file__).resolve().parents[2]


def _copy_repository(destination: Path) -> Path:
    target = destination / "uwflow-copy"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__", "venv", "node_modules"),
    )
    return target


def _python_script_tasks(tasks: list[dict]) -> list[dict]:
    found: list[dict] = []
    for task in tasks:
        if task.get("type") == "io.kestra.plugin.scripts.python.Script":
            found.append(task)
        found.extend(_python_script_tasks(task.get("tasks", [])))
        found.extend(_python_script_tasks(task.get("then", [])))
        found.extend(_python_script_tasks(task.get("else", [])))
    return found


def test_candidate_does_not_assign_or_reserve_an_approved_release_id(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)

    result = build_dev_candidate(root, baseline_release="2.0.0")

    assert result["based_on_production_release"] == "2.0.0"
    assert result["candidate_id"].startswith("dev-")
    assert "intended_production_release" not in result
    candidate_manifest = json.loads(
        (root / result["bundle_relative_path"] / "release-manifest.json").read_text()
    )
    assert candidate_manifest["candidate_id"] == result["candidate_id"]
    assert candidate_manifest["based_on_production_release"] == "2.0.0"
    assert "intended_production_release" not in candidate_manifest


def test_workspace_policy_change_creates_new_candidate_without_touching_core(
    tmp_path: Path,
) -> None:
    from modules.lifecycle.workspaces import WorkspaceStore

    root = _copy_repository(tmp_path)
    store = WorkspaceStore(root)
    workspace = store.ensure_default()
    workspace_dir = root / "var" / "workspaces" / "strategies" / workspace["workspace_id"]
    policy_path = workspace_dir / "policy-specs" / "stage1_hard_gates.json"
    core_policy_path = (
        root / "core" / "underwriting" / "policies" / "stages" / "stage1_hard_gates.json"
    )
    core_policy_before = core_policy_path.read_bytes()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    income_check = next(item for item in policy["checks"] if item["check_id"] == "MINIMUM_INCOME")
    income_check["valid_when"]["value"] = 700.0
    policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    generated, _ = compile_specs(
        workspace_dir / "policy-specs",
        root / "core" / "underwriting" / "policies" / "schema" / "fields.json",
    )
    generated_path = workspace_dir / "generated" / "policy_generated.py"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text(generated, encoding="utf-8")

    result = build_dev_candidate(
        root, baseline_release="2.0.0", workspace_id=workspace["workspace_id"]
    )

    assert result["based_on_production_release"] == "2.0.0"
    assert "intended_production_release" not in result
    assert core_policy_path.read_bytes() == core_policy_before
    candidate_dir = root / result["bundle_relative_path"]
    manifest = json.loads((candidate_dir / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["workspace_id"] == workspace["workspace_id"]
    assert "intended_production_release" not in manifest
    assert (candidate_dir / "policy-specs" / "stage1_hard_gates.json").is_file()
    flow = yaml.safe_load((root / result["flow_relative_path"]).read_text(encoding="utf-8"))
    assert flow["namespace"] == "com.ai.credit.dev"
    assert flow["labels"]["runtime-release"] == result["candidate_id"]
    assert flow["labels"]["runtime-manifest-sha256"] == result["manifest_sha256"]

    python_tasks = _python_script_tasks(flow["tasks"])
    assert len(python_tasks) == 7
    for task in python_tasks:
        include = task["namespaceFiles"]["include"]
        assert include == [f"runtime/candidates/{result['candidate_id']}/**"]
        assert task["env"]["APP_RUNTIME_PATH"] == f"runtime/candidates/{result['candidate_id']}"
        assert task["containerImage"] == "ai/uwflow-core-runtime:2.0.0"


def test_candidate_build_is_the_only_strategy_artifact_writer_and_leaves_core_flow_unchanged(
    tmp_path: Path,
) -> None:
    root = _copy_repository(tmp_path)
    flow = root / "core/kestra/flows/uwflow_production_underwriting.yaml"
    before = flow.read_bytes()
    result = build_dev_candidate(root, baseline_release="2.0.0")
    assert result["candidate_id"].startswith("dev-")
    assert flow.read_bytes() == before
    assert not (root / "tools/release/update_production_flow.py").exists()
    assert not (root / "modules/production/tools/release/update_production_flow.py").exists()


def test_git_source_reference_is_part_of_candidate_identity(tmp_path: Path, monkeypatch) -> None:
    import modules.lifecycle.tools.dev_candidate as candidate_module

    root = _copy_repository(tmp_path)
    monkeypatch.setattr(candidate_module, "_source_commit", lambda _root: "commit-a")
    first = build_dev_candidate(root, baseline_release="2.0.0")
    first_manifest = json.loads(
        (root / first["bundle_relative_path"] / "release-manifest.json").read_text(encoding="utf-8")
    )

    monkeypatch.setattr(candidate_module, "_source_commit", lambda _root: "commit-b")
    second = build_dev_candidate(root, baseline_release="2.0.0")
    second_manifest = json.loads(
        (root / second["bundle_relative_path"] / "release-manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert first["candidate_id"] != second["candidate_id"]
    assert first_manifest["source_ref"] == "commit-a"
    assert second_manifest["source_ref"] == "commit-b"
