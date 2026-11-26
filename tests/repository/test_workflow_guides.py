"""Tests that operator guides reference valid paths and preserve workflow order."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GUIDES = (
    ROOT / "README.md",
    ROOT / "core/kestra/README.md",
    ROOT / "docs/development/end-to-end-dev-workflow.md",
    ROOT / "docs/studio/policy-studio.md",
    ROOT / "docs/studio/policy-studio-dev.md",
)


def _fenced_blocks(markdown: str, language: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    active = False
    current: list[str] = []
    for line in markdown.splitlines():
        if not active and line.strip().lower() == f"```{language}":
            active = True
            current = []
        elif active and line.strip() == "```":
            blocks.append(current)
            active = False
        elif active:
            current.append(line)
    return blocks


def test_operator_guides_have_no_manual_root_or_placeholder_commands() -> None:
    for path in GUIDES:
        content = path.read_text(encoding="utf-8")
        assert "REPO_ROOT" not in content
        assert "uwflow-env.sh" not in content
        assert "/path/to/uwflow" not in content


def test_core_first_run_commands_are_complete_and_refer_to_existing_scripts() -> None:
    path = ROOT / "core/kestra/README.md"
    guide = path.read_text(encoding="utf-8")
    blocks = _fenced_blocks(guide, "bash")
    commands = [
        line.strip()
        for block in blocks
        for line in block
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "python3 -m venv var/venv" in commands
    assert "source var/venv/bin/activate" in commands
    assert "python -m pip install -e ." in commands
    assert "python -m core.python.cli --output-dir var/reports/local" in commands
    assert "bash core/scripts/create-local-credentials.sh" in commands
    assert "bash tools/docker/build-images.sh --core-only" in commands
    assert "bash core/docker-run.sh" in commands

    for command in commands:
        if command.startswith("bash "):
            script_command = command.removeprefix("bash ").split(maxsplit=1)[0]
            script = ROOT / script_command
            assert script.is_file(), f"Workflow script referenced by guide is missing: {script}"


def test_full_platform_and_policy_guides_use_single_line_workflow_launchers() -> None:
    for path in (
        ROOT / "README.md",
        ROOT / "docs/development/end-to-end-dev-workflow.md",
        ROOT / "docs/studio/policy-studio.md",
    ):
        content = path.read_text(encoding="utf-8")
        for block in _fenced_blocks(content, "bash"):
            commands = [
                line.strip() for line in block if line.strip() and not line.lstrip().startswith("#")
            ]
            assert len(commands) == 1, (
                f"{path.name} contains a multi-command Bash block: {commands!r}"
            )
            command = commands[0]
            if path == ROOT / "README.md" and command.startswith("python -m core.python.cli"):
                continue
            assert command.startswith("bash tools/guides/workflow/")
            script = ROOT / command.removeprefix("bash ")
            assert script.is_file(), f"Workflow script referenced by guide is missing: {script}"


def test_python_workflow_launchers_activate_the_project_venv() -> None:
    workflow_dir = ROOT / "tools" / "guides" / "workflow"
    for path in workflow_dir.glob("*.sh"):
        if path.name in {"_common.sh", "01-python-environment.sh"}:
            continue
        content = path.read_text(encoding="utf-8")
        invokes_python = re.search(r"(?<![A-Za-z0-9_])python(?:\s|$)", content) is not None
        if invokes_python:
            assert "load_python_environment" in content, (
                f"{path.name} invokes Python without activating var/venv"
            )


def test_host_preflight_checks_python_venv_module_without_installing_it() -> None:
    preflight = (ROOT / "tools/guides/workflow/00-preflight.sh").read_text(encoding="utf-8")
    assert "python3 -m venv --help" in preflight
    assert "No package was installed automatically." in preflight
    assert "python3-venv" in preflight


def test_python_environment_bootstrap_repairs_incomplete_venv(tmp_path: Path) -> None:
    common = ROOT / "tools/guides/workflow/lib/common.sh"
    broken = tmp_path / "var/venv"
    broken.mkdir(parents=True)
    (broken / "incomplete-marker").write_text("stale", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; cd "$2"; ensure_python_environment; load_python_environment; '
            'python -c "import sys; assert sys.prefix != sys.base_prefix"; echo venv-ok',
            "uwflow-venv-test",
            str(common),
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Found an incomplete or invalid var/venv; rebuilding" in result.stdout
    assert "Project virtual environment is ready." in result.stdout
    assert "venv-ok" in result.stdout
    assert (broken / "bin/activate").is_file()
    assert (broken / "bin/python").is_file()
    assert not (broken / "incomplete-marker").exists()


def test_python_environment_bootstrap_creates_missing_venv(tmp_path: Path) -> None:
    common = ROOT / "tools/guides/workflow/lib/common.sh"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; cd "$2"; ensure_python_environment; load_python_environment; '
            'python -c "import sys; assert sys.prefix != sys.base_prefix"',
            "uwflow-venv-test",
            str(common),
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Creating project virtual environment: var/venv" in result.stdout
    assert (tmp_path / "var/venv/bin/activate").is_file()


def test_python_environment_bootstrap_reuses_valid_venv(tmp_path: Path) -> None:
    common = ROOT / "tools/guides/workflow/lib/common.sh"
    subprocess.run(["python3", "-m", "venv", str(tmp_path / "var/venv")], check=True)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; cd "$2"; ensure_python_environment; load_python_environment',
            "uwflow-venv-test",
            str(common),
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Reusing valid var/venv" in result.stdout


def test_fast_route_uses_shared_venv_loader_after_step_01() -> None:
    launcher = (ROOT / "tools/guides/workflow/dev-fast-route.sh").read_text(encoding="utf-8")
    environment_step = (ROOT / "tools/guides/workflow/01-python-environment.sh").read_text(
        encoding="utf-8"
    )
    common = (ROOT / "tools/guides/workflow/lib/common.sh").read_text(encoding="utf-8")
    assert "ensure_python_environment" in environment_step
    assert "load_python_environment" in environment_step
    assert "source var/venv/bin/activate" not in launcher
    assert launcher.count("load_python_environment") == 1
    assert "-x var/venv/bin/python" in common
    assert "-r var/venv/bin/activate" in common


def test_workflow_python_module_paths_match_reorganized_tools_tree() -> None:
    workflow_dir = ROOT / "tools/guides/workflow"
    module_pattern = re.compile(r"\bpython\s+-m\s+(tools(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
    for path in workflow_dir.glob("*.sh"):
        content = path.read_text(encoding="utf-8")
        for module in module_pattern.findall(content):
            module_path = ROOT.joinpath(*module.split("."))
            assert (
                module_path.with_suffix(".py").is_file() or (module_path / "__main__.py").is_file()
            ), f"{path.name} references missing reorganized module {module}"


def test_kestra_cli_user_bin_is_added_in_each_workflow_shell() -> None:
    common = (ROOT / "tools/guides/workflow/lib/common.sh").read_text(encoding="utf-8")
    installer = (ROOT / "tools/guides/workflow/08-install-kestra-cli.sh").read_text(
        encoding="utf-8"
    )
    assert 'user_bin="${HOME}/.local/bin"' in common
    assert "add_user_bin_to_path" in common
    assert "add_user_bin_to_path" in installer
    assert 'INSTALL_DIR="$HOME/.local/bin"' in installer


def test_operator_workflow_scripts_are_grouped_under_guides_workflow() -> None:
    tools_dir = ROOT / "tools"
    stray = [path.name for path in tools_dir.glob("*.sh") if path.name != "build-docker.sh"]
    assert stray == [], f"Operator workflow scripts belong under tools/guides/workflow: {stray!r}"


def test_database_initializer_is_self_contained_for_a_new_terminal() -> None:
    initializer = (ROOT / "tools/guides/workflow/10-initialize-history-database.sh").read_text(
        encoding="utf-8"
    )
    assert "load_python_environment" in initializer
    assert "load_history_credentials" in initializer
    assert "require_history_database_healthy" in initializer
    assert "ensure_history_admin_connection" in initializer


def test_history_database_launcher_reuses_existing_named_container() -> None:
    launcher = (ROOT / "tools/guides/workflow/06-start-history-database.sh").read_text(
        encoding="utf-8"
    )
    assert "docker network inspect uwflow-local" in launcher
    assert "docker inspect uwflow-history-db" in launcher
    assert "docker start uwflow-history-db" in launcher
    assert "docker compose --env-file .env.history -f modules/history/compose.yml up -d" in launcher
    assert "uwflow_history_pgdata" in launcher
    assert "load_python_environment" in launcher
    assert "ensure_history_admin_connection" in launcher
    assert "attached_volume" in launcher
    assert "docker volume rm" not in launcher


def test_history_database_stop_preserves_the_container_and_volume() -> None:
    stopper = (ROOT / "tools/guides/workflow/21-stop-history-database.sh").read_text(
        encoding="utf-8"
    )
    assert "docker stop uwflow-history-db" in stopper
    assert "uwflow_history_pgdata was not removed" in stopper
    assert "docker compose down" not in stopper
    assert "docker volume rm" not in stopper


def test_tools_root_stays_small_and_new_modules_use_responsibility_packages() -> None:
    tools_dir = ROOT / "tools"
    root_python = {path.name for path in tools_dir.glob("*.py")}
    assert root_python == {"__init__.py", "compile_policy_spec.py"}

    expected_modules = {
        "demo/run.py",
        "demo/render_report.py",
        "policy/compiler.py",
        "history/database/check_connection.py",
        "history/database/initialize.py",
        "history/database/reconcile_owner_password.py",
        "history/database/recover_credentials.py",
        "history/datasets/generate_synthetic.py",
        "history/datasets/list_datasets.py",
        "history/datasets/validate_dataset.py",
        "history/replay/compare_batches.py",
        "history/replay/dev_cohort.py",
        "history/replay/run_batch.py",
        "kestra/cli.py",
        "kestra/fast_route_api.py",
        "kestra/namespace_files.py",
        "kestra/yaml.py",
    }
    actual_modules = {
        path.relative_to(tools_dir).as_posix()
        for path in tools_dir.rglob("*.py")
        if path.name != "__init__.py" and path.name != "compile_policy_spec.py"
    }
    assert actual_modules == expected_modules


def test_tests_root_stays_categorized() -> None:
    root_test_modules = list((ROOT / "tests").glob("test_*.py"))
    assert root_test_modules == [], (
        f"Place new tests in a responsibility folder: {root_test_modules!r}"
    )


def test_all_markdown_bash_blocks_are_single_line_commands() -> None:
    markdown_files = [
        *ROOT.glob("*.md"),
        *ROOT.rglob("*.md"),
    ]
    for path in sorted(set(markdown_files)):
        if any(part.startswith((".", "build", "dist")) for part in path.relative_to(ROOT).parts):
            continue
        for block in _fenced_blocks(path.read_text(encoding="utf-8"), "bash"):
            commands = [line.strip() for line in block if line.strip()]
            is_core_environment_setup = path == ROOT / "core/kestra/README.md" and commands == [
                "python3 -m venv var/venv",
                "source var/venv/bin/activate",
                "python -m pip install --upgrade pip",
                "python -m pip install -e .",
            ]


def test_github_publishing_initializer_requires_review_and_confirmation() -> None:
    launcher = ROOT / "tools/guides/workflow/23-initialize-github-repository.sh"
    content = launcher.read_text(encoding="utf-8")
    assert launcher.is_file()
    assert "git check-ignore -q --no-index" in content
    assert "git ls-files --error-unmatch" in content
    assert "git diff --cached --stat" in content
    assert "Commit the staged repository contents?" in content
    assert "Push branch main" in content
    assert "git push -u origin main" in content


def test_workflow_index_lists_every_entry_point() -> None:
    workflow_dir = ROOT / "tools/guides/workflow"
    index = (workflow_dir / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`([0-9]{2}-[a-z0-9-]+\.sh)`", index))
    actual = {path.name for path in workflow_dir.glob("[0-9][0-9]-*.sh")}
    assert documented == actual, (
        f"Workflow index differs from actual entry points; missing={actual - documented}, "
        f"stale={documented - actual}"
    )


def test_history_database_authentication_is_checked_before_initialization() -> None:
    workflow = ROOT / "tools/guides/workflow"
    common = (workflow / "lib/common.sh").read_text(encoding="utf-8")
    assert "tools.history.database.check_connection" in common
    assert "tools.history.database.reconcile_owner_password" in common
    assert "Synchronize the database owner password with .env.history?" in common
    check = ROOT / "tools/history/database/check_connection.py"
    reconcile = ROOT / "tools/history/database/reconcile_owner_password.py"
    assert check.is_file() and reconcile.is_file()
    repair = reconcile.read_text(encoding="utf-8")
    assert "uwflow_history_pgdata" in repair
    assert "ALTER ROLE" in repair
    assert "docker volume rm" not in repair
    assert "DROP DATABASE" not in repair


def test_history_credential_recovery_is_approved_and_volume_preserving() -> None:
    step = ROOT / "tools/guides/workflow/04-create-history-credentials.sh"
    recovery = ROOT / "tools/history/database/recover_credentials.py"
    common = ROOT / "tools/guides/workflow/lib/common.sh"
    starter = ROOT / "tools/guides/workflow/07-start-kestra.sh"
    initializer = ROOT / "tools/guides/workflow/10-initialize-history-database.sh"
    step_text = step.read_text(encoding="utf-8")
    recovery_text = recovery.read_text(encoding="utf-8")
    common_text = common.read_text(encoding="utf-8")
    starter_text = starter.read_text(encoding="utf-8")
    initializer_text = initializer.read_text(encoding="utf-8")

    assert "tools.history.database.recover_credentials" in step_text
    assert 'recovery_status" -ne 3' in step_text
    assert "docker info >/dev/null" in step_text
    assert "Reconcile the history credentials and continue? [y/N]" in recovery_text
    assert "uwflow_history_pgdata" in recovery_text
    assert "history-owner-password-reconcile-approved" in recovery_text
    assert "history-kestra-secrets-reload" in recovery_text
    assert "tools.history.database.reconcile_owner_password" in common_text
    assert "restart_local_kestra_for_history_secret_reload" in starter_text
    assert "kestra_data|/app/storage" in common_text
    assert "kestra_db|/app/data" in common_text
    assert "history-owner-password-reconcile-approved" in initializer_text
    assert initializer_text.index(
        "tools.history.database.initialize --allow-write"
    ) < initializer_text.index("history-owner-password-reconcile-approved")
    assert "docker volume rm" not in recovery_text + common_text + starter_text
    assert "docker rm -v" not in common_text + starter_text


def test_fresh_history_credential_generator_still_refuses_existing_database() -> None:
    generator = ROOT / "tools/guides/workflow/lib/create-history-env.sh"
    content = generator.read_text(encoding="utf-8")
    assert "docker inspect uwflow-history-db" in content
    assert "docker volume inspect uwflow_history_pgdata" in content
    assert "Refusing to generate new passwords" in content
    assert "Do not delete or recreate the volume" in content


def _run_kestra_secret_reload_helper(
    tmp_path: Path,
    *,
    initial_state: str,
    stop_behavior: str = "remove",
    mounts_ok: bool = True,
):
    import os
    import subprocess
    import textwrap

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state.txt"
    state.write_text(initial_state, encoding="utf-8")
    docker = fake_bin / "docker"
    shell_script = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$DOCKER_CALL_LOG"
state() { cat "$DOCKER_STATE_FILE"; }
set_state() { printf '%s' "$1" > "$DOCKER_STATE_FILE"; }
case "$1" in
  info) exit 0 ;;
  inspect)
    if [[ "${2:-}" == --format ]]; then
      template="$3"
      target="$4"
    else
      target="$2"
      template=""
    fi
    [[ "$(state)" != missing ]] || exit 1
    [[ "$target" == kestra || "$target" == container-id ]] || exit 1
    case "$template" in
      '{{.Id}}') printf 'container-id\n' ;;
      *'.Mounts'*) printf '%s\n' "$DOCKER_MOUNTS" ;;
      '{{.State.Running}}')
        if [[ "$(state)" == running ]]; then printf 'true\n'; else printf 'false\n'; fi
        ;;
      '') ;;
      *) exit 2 ;;
    esac
    exit 0 ;;
  stop)
    if [[ "$DOCKER_STOP_BEHAVIOR" == remove || "$DOCKER_STOP_BEHAVIOR" == error-after-remove ]]; then
      set_state missing
    else
      set_state stopped
    fi
    [[ "$DOCKER_STOP_BEHAVIOR" != error-after-remove ]] || exit 1
    exit 0 ;;
  rm)
    [[ "$(state)" != missing ]] || exit 1
    set_state missing
    exit 0 ;;
esac
exit 0
"""
    docker.write_text(textwrap.dedent(shell_script), encoding="utf-8")
    docker.chmod(0o755)
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)

    mounts = (
        "kestra_data|/app/storage\nkestra_db|/app/data" if mounts_ok else "unexpected_volume|/wrong"
    )
    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}:{env['PATH']}",
        DOCKER_CALL_LOG=str(calls),
        DOCKER_STATE_FILE=str(state),
        DOCKER_STOP_BEHAVIOR=stop_behavior,
        DOCKER_MOUNTS=mounts,
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            "source tools/guides/workflow/lib/common.sh; restart_local_kestra_for_history_secret_reload",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    observed = calls.read_text(encoding="utf-8") if calls.exists() else ""
    return result, observed, state.read_text(encoding="utf-8")


def test_kestra_secret_reload_handles_docker_auto_remove_without_rm_race(tmp_path: Path) -> None:
    result, observed, final_state = _run_kestra_secret_reload_helper(
        tmp_path, initial_state="running", stop_behavior="remove"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stop --time 30 container-id" in observed
    assert "rm container-id" not in observed
    assert "rm -v" not in observed
    assert final_state == "missing"
    assert "named data volumes are preserved" in result.stdout


def test_kestra_secret_reload_with_no_existing_container_starts_fresh(tmp_path: Path) -> None:
    result, observed, final_state = _run_kestra_secret_reload_helper(
        tmp_path, initial_state="missing"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No existing Kestra container found" in result.stdout
    assert not any(line.startswith(("stop ", "rm ")) for line in observed.splitlines())
    assert final_state == "missing"


def test_kestra_secret_reload_removes_stopped_container_object_only(tmp_path: Path) -> None:
    result, observed, final_state = _run_kestra_secret_reload_helper(
        tmp_path, initial_state="stopped", stop_behavior="remove"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stop --time 30" not in observed
    assert "rm container-id" in observed
    assert "rm -v" not in observed
    assert final_state == "missing"


def test_kestra_secret_reload_tolerates_container_disappearing_during_stop(tmp_path: Path) -> None:
    result, observed, final_state = _run_kestra_secret_reload_helper(
        tmp_path, initial_state="running", stop_behavior="error-after-remove"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stop --time 30 container-id" in observed
    assert "already removed while stopping" in result.stdout
    assert "rm container-id" not in observed
    assert final_state == "missing"


def test_kestra_secret_reload_refuses_unexpected_mounts(tmp_path: Path) -> None:
    result, observed, final_state = _run_kestra_secret_reload_helper(
        tmp_path, initial_state="running", mounts_ok=False
    )

    assert result.returncode != 0
    assert "does not use the expected named data volumes" in result.stderr
    assert not any(line.startswith(("stop ", "rm ")) for line in observed.splitlines())
    assert final_state == "running"


def test_kestra_step_07_starts_fresh_container_when_secret_reload_has_no_container(
    tmp_path: Path,
) -> None:
    import os
    import shutil
    import subprocess

    repo = tmp_path / "uwflow-test"
    (repo / "tools/guides/workflow/lib").mkdir(parents=True)
    (repo / "core/docker").mkdir(parents=True)
    (repo / "core/kestra").mkdir(parents=True)
    (repo / "var/data/history").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname='test'\nversion='2.0.0'\n", encoding="utf-8"
    )
    shutil.copy2(
        ROOT / "tools/guides/workflow/07-start-kestra.sh",
        repo / "tools/guides/workflow/07-start-kestra.sh",
    )
    shutil.copy2(
        ROOT / "tools/guides/workflow/lib/common.sh", repo / "tools/guides/workflow/lib/common.sh"
    )
    (repo / "docker-run.sh").write_text(
        "#!/usr/bin/env bash\nprintf 'docker-run invoked\n' >> \"$RUN_LOG\"\n",
        encoding="utf-8",
    )
    (repo / "docker-run.sh").chmod(0o755)
    (repo / ".env").write_text(
        "KESTRA_SERVER_BASIC_AUTH_USERNAME=test\nKESTRA_SERVER_BASIC_AUTH_PASSWORD=test\n",
        encoding="utf-8",
    )
    root = str(repo / "var/data/history")
    (repo / ".env.history").write_text(
        "\n".join(
            [
                "UWFLOW_HISTORY_CONNECTOR=postgres",
                "UWFLOW_HISTORY_ADMIN_DSN=postgresql://owner:secret@127.0.0.1:55432/history",
                "UWFLOW_HISTORY_DSN=postgresql://reader:secret@127.0.0.1:55432/history",
                "UWFLOW_HISTORY_WRITE_DSN=postgresql://writer:secret@127.0.0.1:55432/history",
                f'UWFLOW_HISTORY_ROOT="{root}"',
                f'UWFLOW_HISTORY_WRITE_ROOT="{root}"',
                f'UWFLOW_HISTORY_DOCKER_ROOT="{root}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / ".env.history.kestra").write_text(
        "SECRET_UWFLOW_HISTORY_DSN=dGVzdA==\n", encoding="utf-8"
    )
    (repo / "var/operator-state").mkdir()
    marker = repo / "var/operator-state/history-kestra-secrets-reload"
    marker.write_text("required\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        "  inspect) exit 1 ;;\n"
        "  info) exit 0 ;;\n"
        "  ps) printf 'uwflow-history-db\n'; exit 0 ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    run_log = tmp_path / "docker-run.log"
    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}:{env['PATH']}",
        RUN_LOG=str(run_log),
        UWFLOW_KESTRA_DETACHED="true",
    )

    result = subprocess.run(
        ["bash", "tools/guides/workflow/07-start-kestra.sh"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No existing Kestra container found" in result.stdout
    assert "Starting local Kestra in detached DEV mode" in result.stdout
    assert run_log.read_text(encoding="utf-8").strip() == "docker-run invoked"
    assert not marker.exists()
