"""Tests for repository structure, ownership boundaries and release hygiene."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _python_script_tasks(tasks):
    for task in tasks:
        if task.get("type") in {
            "io.kestra.plugin.scripts.python.Script",
            "io.kestra.plugin.scripts.python.Commands",
        }:
            yield task
        yield from _python_script_tasks(task.get("tasks", []))
        for branch in ("then", "else"):
            yield from _python_script_tasks(task.get(branch, []))


def test_production_flow_identity_and_engine_boundaries() -> None:
    flow = yaml.safe_load(
        (ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml").read_text()
    )
    assert flow["id"] == "uwflow_production_underwriting"
    assert flow["namespace"] == "com.ai.credit.production"
    assert flow["labels"]["system.readOnly"] == "true"
    assert flow["labels"]["runtime-release"] == "2.0.0"
    assert len(flow["labels"]["runtime-manifest-sha256"]) == 64
    assert "Kestra orchestrates" in flow["description"]
    assert "UWflow owns" in flow["description"]
    task_ids = {task["id"] for task in flow["tasks"]}
    assert {
        "stage5_aidflow_inference",
        "stage6_uwflow_decision",
        "stage7_render_report",
    } <= task_ids


def test_every_production_python_task_uses_bootstrap_prebuilt_image_and_materialized_config() -> (
    None
):
    flow_path = ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml"
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    script_tasks = list(_python_script_tasks(flow["tasks"]))
    assert len(script_tasks) == 7
    for task in script_tasks:
        assert task["namespaceFiles"]["enabled"] is True
        assert task["namespaceFiles"]["include"] == ["runtime/releases/2.0.0/**"]
        assert task["namespaceFiles"]["ifExists"] == "FAIL"
        assert task["taskRunner"]["type"] == "io.kestra.plugin.scripts.runner.docker.Docker"
        assert task["containerImage"] == "ai/uwflow-core-runtime:2.0.0"
        assert task["env"]["APP_TASK_IMAGE"] == task["containerImage"]
        assert task["env"]["APP_RUNTIME_PATH"] == "runtime/releases/2.0.0"
        assert (
            task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == flow["labels"]["runtime-manifest-sha256"]
        )
        assert task["script"].startswith("from bootstrap import ctx\n")
        assert "dependencies" not in task
        assert "sys.path.insert" not in task["script"]
        assert "WORKING_DIR" not in task["script"]
    raw = flow_path.read_text(encoding="utf-8")
    assert "&uwflow_" not in raw
    assert "*uwflow_" not in raw


def test_runtime_bundle_and_flow_match_current_project_version() -> None:
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    flow = yaml.safe_load(
        (ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml").read_text()
    )
    assert project["license"] == {"file": "LICENSE"}
    assert flow["labels"]["runtime-release"] == project["version"]
    assert f"runtime/releases/{project['version']}" in str(flow)


def test_core_and_platform_images_separate_reusable_and_optional_dependencies() -> None:
    core_requirements = (ROOT / "core/docker/requirements.txt").read_text(encoding="utf-8")
    platform_requirements = (ROOT / "modules/platform-runtime/requirements.txt").read_text(
        encoding="utf-8"
    )
    core_dockerfile = (ROOT / "core/docker/Dockerfile").read_text(encoding="utf-8")
    platform_dockerfile = (ROOT / "modules/platform-runtime/Dockerfile").read_text(encoding="utf-8")
    builder = (ROOT / "tools/docker/build-images.sh").read_text(encoding="utf-8")
    assert "kestra==2.0.0" in core_requirements
    assert "reportlab==5.1.0" in core_requirements
    assert "SQLAlchemy" not in core_requirements and "psycopg" not in core_requirements
    assert "pyarrow" not in core_requirements
    assert "reportlab" not in platform_requirements
    assert "SQLAlchemy" in platform_requirements and "psycopg[binary]" in platform_requirements
    assert "pyarrow" in platform_requirements
    assert "COPY core/docker/bootstrap.py /app/bootstrap.py" in core_dockerfile
    assert "pip install" in core_dockerfile
    assert "ARG CORE_IMAGE=ai/uwflow-core-runtime" in platform_dockerfile
    assert "FROM ${CORE_IMAGE}:${UWFLOW_VERSION}" in platform_dockerfile
    assert "--core-only" in builder
    assert "--replace-existing" in builder
    assert "--push" in builder


def test_bootstrap_is_outside_the_immutable_business_runtime_bundle() -> None:
    bootstrap = (ROOT / "core/docker/bootstrap.py").read_text(encoding="utf-8")
    manifest = ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0/release-manifest.json"
    assert manifest.is_file()
    assert "_verify_runtime_bundle" in bootstrap
    assert "runtime_manifest_sha256" in bootstrap
    assert "sys.path" in bootstrap
    assert "bootstrap.py" not in manifest.read_text(encoding="utf-8")


def test_environment_example_does_not_contain_live_credentials() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "GENERATE_WITH_tools/guides/workflow/03-create-local-credentials.sh" in env_example
    assert "SECRET_UNDERWRITING_WEBHOOK_KEY=" in env_example
    assert (
        "replace-this-with-a-long-random-secret"
        in __import__("base64")
        .b64decode(env_example.split("SECRET_UNDERWRITING_WEBHOOK_KEY=", 1)[1].splitlines()[0])
        .decode()
    )
    assert "local-uw-demo-hook-2026-change-me" not in env_example
    assert "UWFLOW_BASELINE_RELEASE" in env_example
    assert "UWFLOW_STUDIO_API_PORT=9000" in env_example
    assert "UWFLOW_STUDIO_WEB_PORT=5173" in env_example


def test_docker_runner_does_not_mount_application_source() -> None:
    docker_run = (ROOT / "core/docker-run.sh").read_text(encoding="utf-8")
    assert "/app/runtime" not in docker_run
    assert "/app/uwflow_history" not in docker_run
    assert "--env-file" in docker_run


def test_ci_builds_derived_history_bundle_before_verifying_it() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    build_command = "python -m modules.history.tools.history_tools_bundle"
    check_command = "python -m modules.history.tools.history_tools_bundle --check"
    assert build_command in workflow
    assert check_command in workflow
    assert workflow.index(build_command) < workflow.index(check_command)


def test_first_run_and_repository_verifier_bootstrap_history_bundle() -> None:
    setup = (ROOT / "tools/guides/workflow/01-python-environment.sh").read_text(encoding="utf-8")
    verify = (ROOT / "tools/guides/workflow/22-verify-repository.sh").read_text(encoding="utf-8")
    build_command = "python -m modules.history.tools.history_tools_bundle"
    check_command = "python -m modules.history.tools.history_tools_bundle --check"
    for script in (setup, verify):
        assert build_command in script
        assert check_command in script
        assert script.index(build_command) < script.index(check_command)


def test_ci_uses_current_bundle_verifiers_and_no_removed_build_package() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m core.underwriting.tools.runtime_bundle --check" in workflow
    assert "tools.build" not in workflow


def test_deployment_workflow_uses_immutable_runtime_upload_and_pinned_actions() -> None:
    workflow = (ROOT / ".github/workflows/deploy-kestra.yml").read_text(encoding="utf-8")
    assert (
        "kestra-io/deploy-namespace-files-action@46a87d14c9c81644cb232492ac25067228ecf473"
        in workflow
    )
    assert "kestra-io/validate-flows-action-v2@f95154ee2d16037585c18ab88fd9fb8668cee635" in workflow
    assert "kestra-io/deploy-flows-action-v2@82d96bc143fe021017ed7219941da528c9ce3eb2" in workflow
    assert "override: false" in workflow
    assert "override: true" in workflow
    assert workflow.index("Upload immutable Core runtime to PROD") < workflow.index(
        "Validate approved production flow"
    )
    assert workflow.index("Validate approved production flow") < workflow.index(
        "Deploy approved production flow"
    )


def test_local_slim_kestra_launcher_is_pinned_and_does_not_mount_source() -> None:
    docker_run = (ROOT / "core/docker-run.sh").read_text(encoding="utf-8")
    assert "kestra/kestra:v2.0.10-slim server local" in docker_run
    assert "KESTRA_PLUGINS_AUTO_INSTALL_ENABLED" not in docker_run
    assert "kestra/kestra:latest-slim" not in docker_run
    assert "/app/runtime" not in docker_run
    assert "/app/uwflow_history" not in docker_run
    assert "--env-file" in docker_run


def test_flow_pins_exact_checked_in_runtime_manifest_digest() -> None:
    flow = yaml.safe_load(
        (ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml").read_text()
    )
    manifest = ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0/release-manifest.json"
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert flow["labels"]["runtime-manifest-sha256"] == digest
    assert all(
        task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == digest
        for task in _python_script_tasks(flow["tasks"])
    )


def test_core_first_run_guide_prepares_minimal_venv_before_deployment() -> None:
    guide = (ROOT / "core/kestra/README.md").read_text(encoding="utf-8")
    common = (ROOT / "tools/guides/workflow/lib/common.sh").read_text(encoding="utf-8")
    assert "python3 -m venv var/venv" in guide
    assert "python -m pip install -e ." in guide
    assert "python -m core.python.cli --output-dir var/reports/local" in guide
    assert "bash tools/docker/build-images.sh --core-only" in guide
    assert "bash core/docker-run.sh" in guide
    assert "bash tools/guides/workflow/08-install-kestra-cli.sh" in guide
    assert "bash tools/guides/workflow/09-deploy-dev-baseline.sh" in guide
    assert "do not run `tools/guides/workflow/01-python-environment.sh`" in guide
    assert "core/kestra/README.md" in common
    assert "01-python-environment.sh" not in common


def test_history_env_generator_quotes_paths_when_repository_path_contains_spaces(
    tmp_path: Path,
) -> None:
    """History env files must be valid when sourced and when read by Compose."""
    copied_root = tmp_path / "UWflow DEV checkout with spaces"
    tools_dir = copied_root / "tools"
    tools_dir.mkdir(parents=True)
    generator = tools_dir / "guides" / "workflow" / "lib" / "create-history-env.sh"
    generator.parent.mkdir(parents=True, exist_ok=True)
    generator.write_text(
        (ROOT / "tools/guides/workflow/lib/create-history-env.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # The generator only needs Docker to ensure the shared network exists.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == "network inspect" ]]; then exit 1; fi\n'
        'if [[ "$1 $2" == "network create" ]]; then exit 0; fi\n'
        'echo "Unexpected docker command: $*" >&2; exit 2\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    subprocess.run(
        ["bash", str(generator)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    history_env = copied_root / ".env.history"
    source_result = subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; set -a; source "$1"; set +a; '
            'printf "%s\\n%s\\n%s" '
            '"$UWFLOW_HISTORY_ROOT" "$UWFLOW_HISTORY_WRITE_ROOT" '
            '"$UWFLOW_HISTORY_DOCKER_ROOT"',
            "bash",
            str(history_env),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    expected_root = str(copied_root / "var" / "data" / "history")
    assert source_result.stdout.splitlines() == [expected_root] * 3

    # Docker Compose's dotenv syntax accepts double-quoted values; assert the
    # generator retains this shared Bash/Compose-compatible representation.
    history_text = history_env.read_text(encoding="utf-8")
    for key in (
        "UWFLOW_HISTORY_ROOT",
        "UWFLOW_HISTORY_WRITE_ROOT",
        "UWFLOW_HISTORY_DOCKER_ROOT",
    ):
        assert f'{key}="{expected_root}"' in history_text


def test_local_env_generator_is_safe_and_base64_encodes_webhook_secret() -> None:
    generator = (ROOT / "tools/guides/workflow/lib/create-local-env.sh").read_text(encoding="utf-8")
    assert "openssl rand -hex 32" in generator
    assert "openssl base64 -A" in generator
    assert 'chmod 600 "${ENV_FILE}"' in generator
    assert "UWFLOW_STUDIO_API_PORT=9000" in generator
    assert "UWFLOW_STUDIO_WEB_PORT=5173" in generator
    assert 'if [[ -e "${ENV_FILE}" ]]' in generator


def test_dev_baseline_is_pinned_to_explicit_baseline_and_bootstrap_path() -> None:
    flow = yaml.safe_load(
        (ROOT / "core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml").read_text()
    )
    manifest = ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0/release-manifest.json"
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert flow["namespace"] == "com.ai.credit.dev"
    assert flow["labels"]["runtime-release"] == "2.0.0"
    assert flow["labels"]["runtime-manifest-sha256"] == digest
    assert "triggers" not in flow
    for task in _python_script_tasks(flow["tasks"]):
        assert task["namespaceFiles"]["include"] == ["runtime/releases/2.0.0/**"]
        assert task["env"]["APP_RUNTIME_PATH"] == "runtime/releases/2.0.0"
        assert task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == digest
        assert task["script"].startswith("from bootstrap import ctx\n")
        assert task["containerImage"] == "ai/uwflow-core-runtime:2.0.0"


def test_fresh_candidate_references_its_own_immutable_bundle(candidate_package: dict) -> None:
    candidate_id = candidate_package["candidate_id"]
    candidate_root = candidate_package["root"] / "var/artifacts/candidates" / candidate_id
    flow_path = candidate_root / "candidate-flow.yaml"
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    manifest_path = candidate_root / "release-manifest.json"
    expected_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert flow["namespace"] == "com.ai.credit.dev"
    assert flow["labels"]["environment"] == "dev-candidate"
    assert flow["labels"]["runtime-manifest-sha256"] == expected_sha
    assert "system.readOnly" not in flow["labels"]
    assert "triggers" not in flow
    for task in _python_script_tasks(flow["tasks"]):
        assert task["namespaceFiles"]["include"] == [f"runtime/candidates/{candidate_id}/**"]
        assert task["env"]["APP_RUNTIME_PATH"] == f"runtime/candidates/{candidate_id}"
        assert task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == expected_sha
        assert task["env"]["APP_RUNTIME_ARTIFACT_TYPE"] == "uwflow-kestra-runtime"
        assert task["env"]["APP_TASK_IMAGE"] == task["containerImage"]
        assert task["script"].startswith("from bootstrap import ctx\n")
        assert task["containerImage"] in {"ai/uwflow-core-runtime:2.0.0", "ai/uwflow-runtime:2.0.0"}


def test_production_deployment_does_not_include_dev_flow_directory() -> None:
    workflow = (ROOT / ".github/workflows/deploy-kestra.yml").read_text(encoding="utf-8")
    assert "directory: ./${{ steps.release.outputs.dir }}" in workflow
    assert "directory: ./kestra/dev/flows" not in workflow


def test_production_flow_materializes_shared_python_and_image_values() -> None:
    raw = (ROOT / "core/kestra/flows/uwflow_production_underwriting.yaml").read_text(
        encoding="utf-8"
    )
    assert "&uwflow_" not in raw
    assert "*uwflow_" not in raw
    flow = yaml.safe_load(raw)
    tasks = list(_python_script_tasks(flow["tasks"]))
    assert len(tasks) == 7
    assert {task["pythonVersion"] for task in tasks} == {"3.11"}
    assert {task["containerImage"] for task in tasks} == {"ai/uwflow-core-runtime:2.0.0"}
    assert all(task["env"]["APP_TASK_IMAGE"] == task["containerImage"] for task in tasks)


def test_docker_build_context_excludes_local_secrets_but_keeps_examples() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env.*" in dockerignore
    assert "!.env.example" in dockerignore
    assert "modules/policy-studio/frontend/.env.local.*" in dockerignore
    assert "!modules/policy-studio/frontend/.env.local.example" in dockerignore
    assert "*.pem" in dockerignore and "*.key" in dockerignore


def test_namespace_directory_upload_scripts_use_no_root() -> None:
    publish_scripts = [
        ROOT / "tools/guides/workflow/09-deploy-dev-baseline.sh",
        ROOT / "tools/guides/workflow/14-publish-history-replay-flow.sh",
    ]
    for path in publish_scripts:
        content = path.read_text(encoding="utf-8")
        assert "publish_immutable_bundle" in content
        assert "kestractl nsfiles list" not in content
        assert "|| true" not in content

    shared_publisher = (ROOT / "tools/guides/workflow/lib/common.sh").read_text(encoding="utf-8")
    assert "nsfiles upload" in shared_publisher
    assert "--no-root" in shared_publisher
    assert "Directory not found: $namespace_path" in shared_publisher
    assert "|| true" not in (ROOT / "tools/guides/workflow/09-deploy-dev-baseline.sh").read_text(
        encoding="utf-8"
    )
    assert "|| true" not in (
        ROOT / "tools/guides/workflow/14-publish-history-replay-flow.sh"
    ).read_text(encoding="utf-8")
    history_publisher = (
        ROOT / "tools/guides/workflow/14-publish-history-replay-flow.sh"
    ).read_text(encoding="utf-8")
    assert "bundle_id" in history_publisher
    assert "candidate_id" in history_publisher
    assert "history-tools/$TOOLS_ID/" in history_publisher
    assert "Re-run Step 13" in history_publisher

    assert "nsfiles_upload_directory_command" in (
        ROOT / "modules/lifecycle/tools/dev_candidate.py"
    ).read_text(encoding="utf-8")
    assert "nsfiles_upload_directory_command" not in (
        ROOT / "modules/evaluation/tools/history_replay_flow.py"
    ).read_text(encoding="utf-8")


def test_synthetic_example_data_is_grouped_by_use() -> None:
    examples = ROOT / "core/underwriting/examples"
    assert (examples / "README.md").is_file()
    assert (examples / "applications/application_default.json").is_file()
    assert (examples / "applications/expected_default_decision.json").is_file()
    assert (ROOT / "modules/history/examples/cohorts/dev_cohort.sample.jsonl").is_file()
    assert not (examples / "reports").exists()
    assert not list(examples.glob("application_*.json"))
    replay_source = (ROOT / "tools/history/replay/dev_cohort.py").read_text(encoding="utf-8")
    assert "modules/history/examples/cohorts/dev_cohort.sample.jsonl" in replay_source
    candidate_builder = (ROOT / "modules/lifecycle/tools/dev_candidate.py").read_text(
        encoding="utf-8"
    )
    assert "--cohort modules/history/examples/cohorts/dev_cohort.sample.jsonl" in (
        ROOT / "modules/lifecycle/tools/dev_candidate.py"
    ).read_text(encoding="utf-8")


def test_testclient_uses_httpx2_in_development_extras() -> None:
    import tomllib

    optional = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    assert any(item.startswith("httpx2>=2.0") for item in optional["dev"])
    assert any(item.startswith("httpx2>=2.0") for item in optional["studio"])


def test_manifest_explicit_includes_exist() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for line in manifest.splitlines():
        line = line.strip()
        if not line.startswith("include "):
            continue
        for relative in line.split()[1:]:
            assert (ROOT / relative).is_file(), f"MANIFEST.in references missing file: {relative}"


def test_source_layout_separates_runtime_history_and_local_demo_tools() -> None:
    runtime = ROOT / "core/python/runtime"
    history = ROOT / "modules/history/python/uwflow_history"
    demo = ROOT / "tools" / "demo"

    assert runtime.is_dir()
    assert history.is_dir()
    assert demo.is_dir()
    assert not (ROOT / "scripts").exists()
    assert not (runtime / "demo_run.py").exists()
    assert not (runtime / "render_demo_report.py").exists()

    from core.underwriting.tools.runtime_bundle import RUNTIME_MODULES

    assert {path.name for path in runtime.glob("*.py")} == set(RUNTIME_MODULES)
    assert (history / "contracts.py").is_file()
    assert (demo / "run.py").is_file()
    assert (demo / "render_report.py").is_file()


def test_mermaid_diagrams_exist_for_each_documentation_work_area() -> None:
    paths = {
        "README.md": ROOT / "README.md",
        "development": ROOT / "docs" / "development" / "end-to-end-dev-workflow.md",
        "production": ROOT / "docs" / "production" / "production-release-workflow.md",
        "studio": ROOT / "docs" / "studio" / "policy-studio.md",
        "studio_candidate": ROOT / "docs" / "studio" / "policy-studio-dev.md",
        "architecture": ROOT / "docs" / "architecture" / "architecture.md",
        "history": ROOT / "docs" / "development" / "historical-data-and-replay.md",
    }
    for label, path in paths.items():
        content = path.read_text(encoding="utf-8")
        blocks = re.findall(r"```mermaid\s*\n(.*?)```", content, re.DOTALL)
        assert blocks, f"Missing Mermaid diagram for {label}"
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            assert lines[0].startswith(("flowchart ", "sequenceDiagram", "stateDiagram")), (
                label,
                lines[0],
            )
            assert sum(line.startswith("subgraph ") for line in lines) == sum(
                line == "end" for line in lines
            )


def test_readme_architecture_diagram_models_the_workspace_candidate_release_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```mermaid\s*\n(.*?)```", readme, re.DOTALL)
    assert block is not None
    diagram = block.group(1)
    for expected in (
        "Core default / approved PROD release / any DEV candidate",
        "Independent analyst workspace",
        "Policy Studio",
        "Immutable DEV candidate",
        "Kestra DEV paired replay",
        "Frozen historical evidence",
        "Registered evaluation evidence",
        "External risk approval + Git review",
        "Immutable approved release package",
        "Merge release package to protected main",
        "Manual deploy with exact release ID",
        "Kestra PROD — Core only",
        "Docker Task Runner",
        "Verify immutable runtime manifest",
        "Stage 7 applicant report",
    ):
        assert expected in diagram

    assert diagram.index("Independent analyst workspace") < diagram.index("Immutable DEV candidate")
    assert diagram.index("Immutable DEV candidate") < diagram.index(
        "Registered evaluation evidence"
    )
    assert diagram.index("Registered evaluation evidence") < diagram.index(
        "Immutable approved release package"
    )
    assert diagram.index("Immutable approved release package") < diagram.index(
        "Merge release package to protected main"
    )
    assert diagram.index("Merge release package to protected main") < diagram.index(
        "Manual deploy with exact release ID"
    )


def test_production_mermaid_diagram_matches_the_governed_lifecycle_order() -> None:
    content = (ROOT / "docs" / "production" / "production-release-workflow.md").read_text(
        encoding="utf-8"
    )
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", content, re.DOTALL)
    assert len(blocks) == 1
    diagram = blocks[0]
    sequence = (
        "Analyst strategy workspace",
        "Immutable candidate snapshot",
        "Kestra DEV",
        "Paired evaluation and evidence",
        "Explicit underwriting and risk approval",
        "var/releases/approved",
        "Protected GitHub production workflow",
        "Kestra PROD",
        "Deployment provenance ledger",
    )
    positions = [diagram.index(label) for label in sequence]
    assert positions == sorted(positions)


def test_runtime_source_layout_is_reflected_in_developer_docs_and_api_reload() -> None:
    architecture = (ROOT / "docs" / "architecture" / "architecture.md").read_text(encoding="utf-8")
    for expected in (
        "`core/python/runtime/`",
        "`modules/history/python/uwflow_history/`",
        "`tools/demo/`",
        "scripts/uwflow_history/",
        "flat top-level modules",
    ):
        assert expected in architecture

    dockerfile = (
        ROOT / "modules" / "policy-studio" / "docker" / "studio" / "api.Dockerfile"
    ).read_text(encoding="utf-8")
    assert '"/workspace/core/python/runtime"' in dockerfile
    assert '"/workspace/modules/history/python"' in dockerfile
    assert '"/workspace/scripts"' not in dockerfile
