"""Tests for Policy Studio Docker configuration, startup and diagnostics contracts."""

from __future__ import annotations

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "modules/policy-studio/compose.yml"
STUDIO_HELPER = ROOT / "tools/guides/workflow/lib/studio-compose.sh"


def test_studio_compose_uses_one_stable_project_and_external_dependency_volume() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    assert compose["name"] == "uwflow-studio"
    assert set(services) == {"studio-api", "studio-frontend"}

    api = services["studio-api"]
    frontend = services["studio-frontend"]

    assert api["build"]["dockerfile"] == "modules/policy-studio/docker/studio/api.Dockerfile"
    assert (
        frontend["build"]["dockerfile"] == "modules/policy-studio/docker/studio/frontend.Dockerfile"
    )
    assert api["user"] == "${UWFLOW_DOCKER_UID:-1000}:${UWFLOW_DOCKER_GID:-1000}"
    assert api["volumes"][0]["target"] == "/workspace"
    assert frontend["volumes"][0]["source"] == "../../modules/policy-studio/frontend"
    assert frontend["volumes"][0]["target"] == "/workspace/frontend"
    assert frontend["volumes"][0]["read_only"] is True
    assert frontend["working_dir"] == "/workspace"
    assert frontend["volumes"][1]["target"] == "/workspace/node_modules"
    assert not frontend["volumes"][1]["target"].startswith(frontend["volumes"][0]["target"] + "/")
    assert frontend["volumes"][1]["source"] == "uwflow_studio_node_modules"
    assert compose["volumes"]["uwflow_studio_node_modules"] == {
        "external": True,
        "name": "uwflow_studio_node_modules",
    }
    assert frontend["environment"]["VITE_STUDIO_API_URL"] == "http://studio-api:9000"
    assert frontend["environment"]["UWFLOW_VITE_CACHE_DIR"] == "/workspace/node_modules/.vite"
    assert frontend["depends_on"]["studio-api"]["condition"] == "service_healthy"
    assert api["healthcheck"]["test"][0] == "CMD"
    assert frontend["healthcheck"]["test"][0:2] == ["CMD", "node"]
    assert all(value.startswith("127.0.0.1:") for value in api["ports"] + frontend["ports"])


def test_studio_images_pin_python_and_node_major_versions_and_keep_node_off_host() -> None:
    api_dockerfile = (ROOT / "modules/policy-studio/docker/studio/api.Dockerfile").read_text(
        encoding="utf-8"
    )
    frontend_dockerfile = (
        ROOT / "modules/policy-studio/docker/studio/frontend.Dockerfile"
    ).read_text(encoding="utf-8")
    entrypoint = (ROOT / "modules/policy-studio/docker/studio/frontend-entrypoint.sh").read_text(
        encoding="utf-8"
    )

    assert re.search(r"^FROM python:3\.11\.[0-9]+-slim-trixie", api_dockerfile, re.MULTILINE)
    assert "apt-get install --no-install-recommends -y git ca-certificates" in api_dockerfile
    assert re.search(r"^FROM node:26-", frontend_dockerfile, re.MULTILINE)
    assert "WORKDIR /workspace" in frontend_dockerfile
    assert "COPY modules/policy-studio/frontend/package.json ./package.json" in frontend_dockerfile
    assert "npm install --no-package-lock --no-audit --no-fund" in frontend_dockerfile
    assert "npm install --prefix /workspace" in entrypoint
    assert "cp frontend/package.json package.json" in entrypoint
    assert "npm install --prefix /workspace" in entrypoint
    assert "npm --prefix /workspace run dev" in entrypoint
    assert "/workspace/node_modules" in entrypoint or "node_modules/.bin/vite" in entrypoint
    assert "/workspace/frontend" in entrypoint
    assert "--config /workspace/frontend/vite.config.ts" in entrypoint
    assert "/workspace/frontend/node_modules" not in entrypoint + frontend_dockerfile
    assert "UWFLOW_VITE_CACHE_DIR" in entrypoint
    assert 'mkdir -p "$cache_dir"' in entrypoint
    assert '[ ! -w "$cache_dir" ]' in entrypoint
    assert ".uwflow-package-hash" in entrypoint
    assert "node --version" in entrypoint

    frontend_package = (ROOT / "modules/policy-studio/frontend/package.json").read_text(
        encoding="utf-8"
    )
    assert '"dev": "vite"' in frontend_package

    for path in (
        ROOT / "README.md",
        ROOT / "docs/development/end-to-end-dev-workflow.md",
        ROOT / "docs/studio/policy-studio.md",
    ):
        content = path.read_text(encoding="utf-8")
        assert "02-node-environment.sh" not in content
        assert "15-start-studio-api.sh" not in content
        assert "16-start-studio-frontend.sh" not in content
        assert "Install NVM" not in content
        assert "Node.js 26 and npm" not in content


def test_vite_optimizer_cache_is_moved_to_writable_docker_volume() -> None:
    vite_config = (ROOT / "modules/policy-studio/frontend/vite.config.ts").read_text(
        encoding="utf-8"
    )
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    env = compose["services"]["studio-frontend"]["environment"]

    assert "cacheDir: process.env.UWFLOW_VITE_CACHE_DIR || 'node_modules/.vite'" in vite_config
    assert env["UWFLOW_VITE_CACHE_DIR"] == "/workspace/node_modules/.vite"
    assert (
        'mkdir -p "$cache_dir"'
        in (ROOT / "modules/policy-studio/docker/studio/frontend-entrypoint.sh").read_text()
    )


def test_studio_launchers_manage_only_the_explicit_stable_compose_project() -> None:
    start = (ROOT / "tools/guides/workflow/15-start-studio.sh").read_text(encoding="utf-8")
    stop = (ROOT / "tools/guides/workflow/16-stop-studio.sh").read_text(encoding="utf-8")
    build = (ROOT / "tools/guides/workflow/02-build-studio-images.sh").read_text(encoding="utf-8")
    helper = STUDIO_HELPER.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    for script in (start, stop, build):
        assert "lib/studio-compose.sh" in script
    assert 'STUDIO_COMPOSE_PROJECT="uwflow-studio"' in helper
    assert (
        'docker compose --project-name "$STUDIO_COMPOSE_PROJECT" -f "$STUDIO_COMPOSE_FILE"'
        in helper
    )
    assert "studio_prepare_compose_stack" in start
    assert "studio_ensure_node_modules_volume" in helper
    assert 'docker volume create "$STUDIO_NODE_MODULES_VOLUME"' in helper
    assert '"${STUDIO_COMPOSE[@]}" up --build -d' in start
    assert 'exec "${STUDIO_COMPOSE[@]}" up --build' in start
    assert '"${STUDIO_COMPOSE[@]}" down' in stop
    assert '"${STUDIO_COMPOSE[@]}" build' in build

    # Startup and shutdown are scoped to this Compose project only.
    for content in (helper, start, stop, build, compose):
        assert "docker stop" not in content
        assert "docker rm" not in content
        assert "--remove-orphans" not in content
    assert "container_name:" not in compose
    assert "ps -q studio-api" in start
    assert "ps -q studio-frontend" in start
    assert "docker compose down -v" not in start + stop + build


def test_studio_start_verifies_container_health_frontend_proxy_and_stage_catalogue() -> None:
    start = (ROOT / "tools/guides/workflow/15-start-studio.sh").read_text(encoding="utf-8")
    assert "api_health" in start and "frontend_health" in start
    assert "http://127.0.0.1:${API_PORT}/api/health" in start
    assert "http://127.0.0.1:${API_PORT}/api/stages" in start
    assert "http://127.0.0.1:${WEB_PORT}/" in start
    assert "http://127.0.0.1:${WEB_PORT}/src/main.tsx" in start
    assert "http://127.0.0.1:${WEB_PORT}/src/App.tsx" in start
    assert "http://127.0.0.1:${WEB_PORT}/api/stages" in start
    assert "seven-stage catalogue" in start
    assert "stage_1_hard_gates" in start
    assert "stage_3_source_plan" in start
    assert "for attempt in $(seq 1 90)" in start


def test_studio_dockerfiles_and_launcher_are_in_the_package() -> None:
    expected = [
        "modules/policy-studio/compose.yml",
        "modules/policy-studio/docker/studio/api.Dockerfile",
        "modules/policy-studio/docker/studio/frontend.Dockerfile",
        "modules/policy-studio/docker/studio/frontend-entrypoint.sh",
        "tools/guides/workflow/lib/studio-compose.sh",
    ]
    for relative in expected:
        assert (ROOT / relative).is_file(), relative


def test_vite_proxy_uses_the_api_service_address_from_docker_compose() -> None:
    vite_config = (ROOT / "modules/policy-studio/frontend/vite.config.ts").read_text(
        encoding="utf-8"
    )
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    configured_target = compose["services"]["studio-frontend"]["environment"]["VITE_STUDIO_API_URL"]
    assert configured_target == "http://studio-api:9000"
    assert "process.env.VITE_STUDIO_API_URL" in vite_config
    assert "target: apiTarget" in vite_config
    assert "fileURLToPath(new URL('.', import.meta.url))" in vite_config
    assert "loadEnv(mode, frontendDirectory, '')" in vite_config
    assert "http://127.0.0.1:9000" in vite_config  # host-development fallback only


def test_studio_compose_files_are_in_the_source_distribution() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".dockerignore" in manifest
    assert "modules/policy-studio/compose.yml" in manifest
    assert "var/" in dockerignore
    assert "/core/kestra/namespace-files/" in dockerignore


def test_api_reload_directories_all_exist_in_the_var_based_repository_layout() -> None:
    import json

    api_dockerfile = (ROOT / "modules/policy-studio/docker/studio/api.Dockerfile").read_text(
        encoding="utf-8"
    )
    command_match = re.search(r"^CMD (\[.*\])$", api_dockerfile, re.MULTILINE)
    assert command_match is not None
    command = json.loads(command_match.group(1))
    reload_dirs = [
        command[index + 1] for index, value in enumerate(command[:-1]) if value == "--reload-dir"
    ]
    assert reload_dirs
    for container_path in reload_dirs:
        assert container_path.startswith("/workspace/")
        repository_path = ROOT / container_path.removeprefix("/workspace/")
        assert repository_path.is_dir(), (
            f"Uvicorn watches a missing repository path: {container_path}"
        )
    assert "/workspace/var/workspaces" in reload_dirs
    assert "/workspace/workspaces" not in reload_dirs


def test_studio_startup_and_diagnostics_print_logs_for_exited_api_container() -> None:
    start = (ROOT / "tools/guides/workflow/15-start-studio.sh").read_text(encoding="utf-8")
    diagnostics = (ROOT / "tools/guides/workflow/90-diagnostics.sh").read_text(encoding="utf-8")
    assert 'if ! "${STUDIO_COMPOSE[@]}" up --build -d; then' in start
    assert "logs --no-color --tail 150 studio-api studio-frontend" in start
    assert "ps --all" in start
    assert "source tools/guides/workflow/lib/studio-compose.sh" in diagnostics
    assert "logs --no-color --tail 100 studio-api studio-frontend" in diagnostics
    assert "docker ps -a" in diagnostics and "--filter name=uwflow-studio" in diagnostics
