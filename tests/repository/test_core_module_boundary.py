"""Tests that Core remains independently runnable and isolated from platform Modules."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _python_tasks(tasks):
    for task in tasks:
        if task.get("type") in {
            "io.kestra.plugin.scripts.python.Script",
            "io.kestra.plugin.scripts.python.Commands",
        }:
            yield task
        yield from _python_tasks(task.get("tasks", []))
        yield from _python_tasks(task.get("then", []))
        yield from _python_tasks(task.get("else", []))


def test_original_seven_stage_system_is_owned_by_core() -> None:
    assert (ROOT / "core/docker-run.sh").is_file()
    assert (ROOT / "core/docker/Dockerfile").is_file()
    assert (ROOT / "core/python/cli.py").is_file()
    assert (ROOT / "core/python/runner.py").is_file()
    assert (ROOT / "core/underwriting/policies/stages/stage1_hard_gates.json").is_file()
    assert (ROOT / "core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml").is_file()
    assert (ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml").is_file()
    assert len(list((ROOT / "core/python/runtime").glob("*.py"))) == 9
    assert not (ROOT / "modules/underwriting").exists()


def test_only_current_core_runtime_and_flow_are_included() -> None:
    active = sorted(path.name for path in (ROOT / "core/kestra/dev/flows").glob("*.yaml"))
    assert active == ["uwflow_dev_baseline_v2_0_0.yaml"]
    releases = sorted(
        path.name for path in (ROOT / "core/kestra/namespace-files/runtime/releases").iterdir()
    )
    assert releases == ["2.0.0"]
    assert not (ROOT / "core/archive").exists()


def test_core_kestra_flow_uses_core_image_and_seven_stage_runtime() -> None:
    path = ROOT / "core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml"
    flow = yaml.safe_load(path.read_text(encoding="utf-8"))
    task_ids = {task["id"] for task in flow["tasks"]}
    assert {
        "stage1_hard_gates",
        "stage2_bureau_lookup",
        "stage3_source_plan",
        "stage4_bigdata_fanout",
        "stage5_aidflow_inference",
        "stage6_uwflow_decision",
        "stage7_render_report",
    } <= task_ids
    tasks = list(_python_tasks(flow["tasks"]))
    assert len(tasks) == 7
    assert {task["containerImage"] for task in tasks} == {"ai/uwflow-core-runtime:2.0.0"}


def test_direct_python_cli_runs_all_seven_stages_and_writes_basic_applicant_reports(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "applicant-reports"
    result = subprocess.run(
        [sys.executable, "-m", "core.python.cli", "--output-dir", str(output_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Stages completed: 7/7" in result.stdout
    assert "Decision: APPROVED" in result.stdout
    for filename in (
        "underwriting_decision.json",
        "underwriting_decision.html",
        "underwriting_decision.pdf",
    ):
        path = output_dir / filename
        assert path.is_file() and path.stat().st_size > 100


def test_history_and_evaluation_dependencies_are_not_part_of_core_image() -> None:
    core = (ROOT / "core/docker/requirements.txt").read_text(encoding="utf-8")
    platform = (ROOT / "modules/platform-runtime/requirements.txt").read_text(encoding="utf-8")
    assert "reportlab==5.1.0" in core
    assert "SQLAlchemy" not in core and "psycopg" not in core and "pyarrow" not in core
    assert "SQLAlchemy" in platform and "psycopg[binary]" in platform and "pyarrow" in platform


def test_generated_artifacts_are_not_shipped_in_the_source_package() -> None:
    for relative in (
        "var/artifacts/candidates",
        "var/artifacts/tool-bundles",
        "var/artifacts/replay-flows",
        "var/artifacts/baselines",
        "var/artifacts/evaluations",
        "var/workspaces/strategies",
        "var/releases/approved",
        "var/deployments/production",
    ):
        path = ROOT / relative
        assert not path.exists() or not any(path.iterdir()), (
            f"generated state shipped under {relative}"
        )
    assert not (ROOT / "var/artifacts/archive").exists()
    assert not (ROOT / "core/archive").exists()


def test_core_source_does_not_import_platform_modules() -> None:
    for path in (ROOT / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            assert all(not name.startswith("modules") for name in imported), (path, imported)


def test_candidate_registry_starts_empty_and_accepts_a_fresh_verified_candidate(
    candidate_package: dict,
) -> None:
    from modules.lifecycle.workspaces import WorkspaceStore

    root = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    sources = WorkspaceStore(root).sources()
    assert {item["source_id"] for item in sources if item["source_type"] == "candidate"} == {
        candidate_id
    }

    candidate_manifest = root / "var/artifacts/candidates" / candidate_id / "release-manifest.json"
    candidate_manifest.write_text('{"candidate_id":"tampered"}\n', encoding="utf-8")
    assert WorkspaceStore(root).sources() == []


def test_platform_modules_do_not_reference_retired_artifact_locations() -> None:
    module_roots = (
        ROOT / "modules/lifecycle",
        ROOT / "modules/history",
        ROOT / "modules/evaluation",
        ROOT / "modules/production",
        ROOT / "modules/policy-studio",
    )
    forbidden = (
        "modules/lifecycle/kestra",
        "modules/history/kestra",
        "modules/evaluation/kestra",
        "tools/build/",
    )
    for module_root in module_roots:
        for path in module_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for old_path in forbidden:
                assert old_path not in source, f"{path.relative_to(ROOT)} references {old_path}"


def test_generated_lifecycle_paths_are_ignored_by_git() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "/var/*",
        "/var/artifacts/*",
        "/var/workspaces/*",
        "/var/releases/*",
        "!/var/releases/approved/**",
        "/var/deployments/*",
        "*.egg-info/",
        "*.egg",
        "*.whl",
    ):
        assert pattern in ignore
    # Approved release packages are intentionally trackable through reviewed Git changes.
    assert "!/var/releases/approved/**" in ignore

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "var/" in dockerignore
    assert "*.egg-info" in dockerignore and "*.egg" in dockerignore and "*.whl" in dockerignore


def test_repository_operational_state_has_one_root() -> None:
    """Running UWflow must not create mutable lifecycle folders beside source at repo root."""
    forbidden_root_dirs = (
        "artifacts",
        "deployments",
        "releases",
        "workspaces",
        "reports",
        "generated_reports",
        "data",
        ".uwflow-dev-state",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
    )
    for name in forbidden_root_dirs:
        assert not (ROOT / name).exists(), f"Operational state leaked into repository root: {name}"

    allowed_root_dirs = {".github", ".git", "core", "docs", "modules", "tests", "tools", "var"}
    actual_root_dirs = {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert actual_root_dirs <= allowed_root_dirs, (
        f"Unexpected directories at repository root: {sorted(actual_root_dirs - allowed_root_dirs)}"
    )
    assert (ROOT / "var/README.md").is_file()
    assert (ROOT / "var/artifacts/README.md").is_file()
    assert (ROOT / "var/workspaces/README.md").is_file()
    assert (ROOT / "var/releases/README.md").is_file()
    assert (ROOT / "var/deployments/README.md").is_file()


def test_policy_studio_module_import_does_not_create_workspace_state() -> None:
    # The Studio ASGI application may be imported by CLI tooling and tests.
    # Import itself must not create mutable analyst data in the checkout.
    assert not (ROOT / "var/workspaces/strategies").exists()
