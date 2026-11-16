from __future__ import annotations

from pathlib import Path
import hashlib

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _python_script_tasks(tasks):
    for task in tasks:
        if task.get("type") == "io.kestra.plugin.scripts.python.Script":
            yield task
        yield from _python_script_tasks(task.get("tasks", []))
        for branch in ("then", "else"):
            yield from _python_script_tasks(task.get(branch, []))


def test_kestra_flow_has_expected_identity_and_separate_engines() -> None:
    flow_path = ROOT / "kestra" / "flows" / "uwflow_production_underwriting.yaml"
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))

    assert flow["id"] == "uwflow_production_underwriting"
    assert flow["namespace"] == "com.aigensys.credit.production"

    task_ids = {task["id"] for task in flow["tasks"]}
    assert "stage5_aidflow_inference" in task_ids
    assert "stage6_uwflow_decision" in task_ids
    assert "stage7_render_report" in task_ids
    assert flow["labels"]["system.readOnly"] == "true"
    assert flow["labels"]["runtime-release"] == "1.2.2"
    assert len(flow["labels"]["runtime-manifest-sha256"]) == 64


def test_every_python_task_uses_only_the_versioned_namespace_release() -> None:
    flow = yaml.safe_load(
        (ROOT / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
            encoding="utf-8"
        )
    )
    script_tasks = list(_python_script_tasks(flow["tasks"]))
    assert len(script_tasks) == 7
    for task in script_tasks:
        assert task["namespaceFiles"]["enabled"] is True
        assert task["namespaceFiles"]["include"] == ["runtime/releases/1.2.2/**"]
        assert task["namespaceFiles"]["ifExists"] == "FAIL"
        assert task["taskRunner"]["type"] == "io.kestra.plugin.scripts.runner.docker.Docker"
        assert task["containerImage"] == "aigensys/uwflow-runtime:1.2.2"
        assert "Path.cwd()" not in task["script"]
        assert "WORKING_DIR" in task["script"]
        assert "/app/scripts" not in task["script"]


def test_runtime_bundle_and_flow_are_version_aligned() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    flow = (ROOT / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
        encoding="utf-8"
    )
    assert 'version = "1.2.2"' in project
    assert "runtime/releases/1.2.2" in flow


def test_docker_runner_does_not_mount_application_source() -> None:
    docker_run = (ROOT / "docker-run.sh").read_text(encoding="utf-8")
    assert "/app/scripts" not in docker_run
    assert "--env-file" in docker_run


def test_deployment_workflow_uses_immutable_runtime_upload_and_pinned_actions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-kestra.yml").read_text(encoding="utf-8")
    assert "kestra-io/deploy-namespace-files-action@46a87d14c9c81644cb232492ac25067228ecf473" in workflow
    assert "kestra-io/validate-flows-action-v2@f95154ee2d16037585c18ab88fd9fb8668cee635" in workflow
    assert "kestra-io/deploy-flows-action-v2@82d96bc143fe021017ed7219941da528c9ce3eb2" in workflow
    assert "override: false" in workflow
    assert "override: true" in workflow  # Updating the stable flow is intentional.
    assert workflow.index("Deploy immutable runtime bundle") < workflow.index("Validate Kestra flow")
    assert workflow.index("Validate Kestra flow") < workflow.index("Deploy read-only UWflow production flow")


def test_local_slim_kestra_launcher_uses_server_local_plugin_install_without_source_mounts() -> None:
    docker_run = (ROOT / "docker-run.sh").read_text(encoding="utf-8")
    assert "kestra/kestra:v2.0.10-slim server local" in docker_run
    assert "KESTRA_PLUGINS_AUTO_INSTALL_ENABLED" not in docker_run
    assert "/app/scripts" not in docker_run
    assert "--env-file" in docker_run


def test_kestra_runtime_python_dependencies_are_exactly_pinned() -> None:
    flow = yaml.safe_load(
        (ROOT / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
            encoding="utf-8"
        )
    )
    script_tasks = list(_python_script_tasks(flow["tasks"]))
    for task in script_tasks:
        assert task.get("dependencies", []) == []

    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "reportlab==4.4.9" in dockerfile



def test_stage_one_records_the_pinned_python_task_image_in_provenance() -> None:
    flow = yaml.safe_load(
        (ROOT / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
            encoding="utf-8"
        )
    )
    stage_one = next(task for task in flow["tasks"] if task["id"] == "stage1_hard_gates")
    image = stage_one["containerImage"]
    assert stage_one["env"]["UWFLOW_TASK_IMAGE"] == image
    assert '"task_runner": "Docker"' in stage_one["script"]
    assert '"task_runner_type": "io.kestra.plugin.scripts.runner.docker.Docker"' in stage_one["script"]
    assert '"python_task_image": ctx.env_str("UWFLOW_TASK_IMAGE")' in stage_one["script"]
    assert '"python_version": ctx.sys.version.split()[0]' in stage_one["script"]

def test_flow_pins_the_exact_checked_in_runtime_manifest_digest() -> None:
    flow = yaml.safe_load(
        (ROOT / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
            encoding="utf-8"
        )
    )
    manifest = (
        ROOT
        / "kestra"
        / "namespace-files"
        / "runtime"
        / "releases"
        / "1.2.2"
        / "release-manifest.json"
    )
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert flow["labels"]["runtime-manifest-sha256"] == digest
    assert f'expected_manifest_sha256="{digest}"' in flow["tasks"][0]["script"]


def test_first_run_guide_uses_documented_oss_namespace_upload_contract() -> None:
    guide = (ROOT / "docs" / "FIRST_RUN.md").read_text(encoding="utf-8")
    assert "kestractl namespaces create" not in guide
    assert "namespaces are implicit" in guide.lower()
    assert "kestractl nsfiles upload com.aigensys.credit.production" in guide
    assert "runtime/releases/1.2.2" in guide
    assert "python tools/build_runtime_bundle.py --check" in guide
    upload_step = guide.split("## 7. Upload the approved Python release", 1)[1].split("## 8.", 1)[0]
    upload_command = upload_step.split("```bash", 1)[1].split("```", 1)[0]
    assert "--fail-fast" in upload_command
    assert "--allow-missing-namespace" in upload_command
    assert "--override" not in upload_command
    assert "kestractl nsfiles list com.aigensys.credit.production" in upload_step
    assert "Why:" in guide


def test_local_env_generator_is_safe_and_base64_encodes_webhook_secret() -> None:
    generator = (ROOT / "tools" / "create-local-env.sh").read_text(encoding="utf-8")
    assert "openssl rand -hex 32" in generator
    assert "openssl base64 -A" in generator
    assert 'chmod 600 "${ENV_FILE}"' in generator
    assert 'if [[ -e "${ENV_FILE}" ]]' in generator


def test_local_kestra_image_is_version_pinned_without_source_mounts() -> None:
    docker_run = (ROOT / "docker-run.sh").read_text(encoding="utf-8")
    assert "kestra/kestra:v2.0.10-slim server local" in docker_run
    assert "kestra/kestra:latest-slim" not in docker_run
    assert "--env-file" in docker_run
    assert "/app/scripts" not in docker_run