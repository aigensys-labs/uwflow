"""Tests for immutable Kestra Namespace Files publishing workflows."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "tools/guides/workflow/lib/common.sh"


MOCK_KESTRACTL = r"""#!/usr/bin/env bash
set -euo pipefail
command_name="$1 $2"
shift 2
case "$command_name" in
  "nsfiles list")
    namespace="$1"
    shift
    path=""
    while (($#)); do
      case "$1" in
        --path) path="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    if [[ "${MOCK_LIST_MODE:-}" == "unauthorized" ]]; then
      echo "Error: API error: Unauthorized" >&2
      exit 1
    fi
    marker="$MOCK_REMOTE_ROOT/${path//\//_}"
    if [[ -f "$marker" ]]; then
      printf 'Name Type Size Modified\n'
      printf '%s/release-manifest.json File 128 2026-11-23T00:00:00Z\n' "$path"
      exit 0
    fi
    echo "Error: API error: Resource not found: Directory not found: $path" >&2
    echo "Usage: kestractl nsfiles list" >&2
    exit 1
    ;;
  "flows validate")
    flow_file="$1"
    printf 'validate|%s\n' "$flow_file" >> "$MOCK_UPLOAD_LOG"
    if [[ "${MOCK_VALIDATE_MODE:-}" == "fail" ]]; then
      echo 'Validation failed: unsupported flow task property' >&2
      exit 1
    fi
    echo 'Flow validation passed'
    ;;
  "nsfiles upload")
    namespace="$1"
    source_directory="$2"
    destination="$3"
    shift 3
    printf '%s\n' "$namespace|$source_directory|$destination|$*" >> "$MOCK_UPLOAD_LOG"
    touch "$MOCK_REMOTE_ROOT/${destination//\//_}"
    ;;
  *)
    echo "Unexpected mock command: $command_name" >&2
    exit 99
    ;;
esac
"""


def _mock_environment(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock = bin_dir / "kestractl"
    mock.write_text(MOCK_KESTRACTL, encoding="utf-8")
    mock.chmod(0o755)
    remote = tmp_path / "remote"
    remote.mkdir()
    upload_log = tmp_path / "uploads.log"
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "MOCK_REMOTE_ROOT": str(remote),
        "MOCK_UPLOAD_LOG": str(upload_log),
        "COMMON": str(COMMON),
    }


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "release-manifest.json").write_text('{"files": {}}\n', encoding="utf-8")
    return bundle


def test_first_namespace_files_publication_uploads_absent_path_without_false_404(
    tmp_path: Path,
) -> None:
    env = _mock_environment(tmp_path)
    bundle = _bundle(tmp_path)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$COMMON"; publish_immutable_bundle com.ai.credit.dev "$BUNDLE" runtime/releases/2.0.0',
        ],
        input="\n",
        text=True,
        capture_output=True,
        env={**env, "BUNDLE": str(bundle)},
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Directory not found" not in result.stdout
    assert "directory has not been created yet" in result.stdout
    assert "Namespace Files path is now present" in result.stdout
    assert "Error: API error" not in result.stderr
    upload_log = Path(env["MOCK_UPLOAD_LOG"]).read_text(encoding="utf-8")
    assert "com.ai.credit.dev|" in upload_log
    assert "runtime/releases/2.0.0" in upload_log
    assert "--no-root" in upload_log
    assert "--fail-fast" in upload_log
    assert "--override" not in upload_log


def test_existing_immutable_namespace_path_can_only_be_reused_after_confirmation(
    tmp_path: Path,
) -> None:
    env = _mock_environment(tmp_path)
    bundle = _bundle(tmp_path)
    remote_marker = Path(env["MOCK_REMOTE_ROOT"]) / "runtime_releases_2.0.0"
    remote_marker.touch()
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$COMMON"; publish_immutable_bundle com.ai.credit.dev "$BUNDLE" runtime/releases/2.0.0',
        ],
        input="y\n",
        text=True,
        capture_output=True,
        env={**env, "BUNDLE": str(bundle)},
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Reusing existing immutable bundle" in result.stdout
    assert not Path(env["MOCK_UPLOAD_LOG"]).exists()


def test_unexpected_namespace_files_api_error_is_not_suppressed_or_treated_as_missing(
    tmp_path: Path,
) -> None:
    env = _mock_environment(tmp_path)
    bundle = _bundle(tmp_path)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$COMMON"; publish_immutable_bundle com.ai.credit.dev "$BUNDLE" runtime/releases/2.0.0',
        ],
        input="\n",
        text=True,
        capture_output=True,
        env={**env, "BUNDLE": str(bundle), "MOCK_LIST_MODE": "unauthorized"},
        check=False,
    )

    assert result.returncode != 0
    assert "Unauthorized" in result.stderr
    assert not Path(env["MOCK_UPLOAD_LOG"]).exists()


def _prepare_operator_checkout(
    tmp_path: Path, launcher: str, *, with_python_env: bool
) -> tuple[Path, dict[str, str]]:
    import shutil
    import venv
    import yaml
    from modules.evaluation.tools.history_replay_flow import build_flow
    from modules.lifecycle.tools.dev_candidate import build_dev_candidate

    root = tmp_path / "UWflow checkout with spaces"
    ignore = shutil.ignore_patterns(
        ".git",
        "var/venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
        "*.egg-info",
    )
    shutil.copytree(ROOT, root, ignore=ignore)
    candidate_result = build_dev_candidate(root, baseline_release="2.0.0")
    candidate_id = candidate_result["candidate_id"]
    flow_path = build_flow(candidate_id, baseline_release="2.0.0", repository_root=root)
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    tools_id = flow["labels"]["history-tools-bundle"]
    flow_id = flow["id"]
    if with_python_env:
        venv.EnvBuilder(with_pip=False).create(root / "var/venv")
    (root / ".env").write_text(
        "KESTRA_SERVER_BASIC_AUTH_USERNAME=test-user\n"
        "KESTRA_SERVER_BASIC_AUTH_PASSWORD=test-password\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "operator-bin"
    bin_dir.mkdir()
    mock = bin_dir / "kestractl"
    mock.write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail
command_name="$1 $2"
shift 2
case "$command_name" in
  "nsfiles list")
    namespace="$1"; shift
    path=""
    while (($#)); do
      case "$1" in
        --path) path="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    marker="$MOCK_REMOTE_ROOT/${path//\//_}"
    if [[ -f "$marker" ]]; then
      printf 'Name Type Size Modified\n%s/release-manifest.json File 128 2026-11-23T00:00:00Z\n' "$path"
      exit 0
    fi
    echo "Error: API error: Resource not found: Directory not found: $path" >&2
    echo 'Usage: kestractl nsfiles list' >&2
    exit 1
    ;;
  "nsfiles upload")
    namespace="$1"; source_directory="$2"; destination="$3"; shift 3
    printf 'upload|%s|%s|%s|%s\n' "$namespace" "$source_directory" "$destination" "$*" >> "$MOCK_LOG"
    touch "$MOCK_REMOTE_ROOT/${destination//\//_}"
    ;;
  "flows validate")
    flow_file="$1"
    printf 'validate|%s\n' "$flow_file" >> "$MOCK_LOG"
    if [[ "${MOCK_VALIDATE_MODE:-}" == "fail" ]]; then
      echo 'Validation failed: unsupported flow task property' >&2
      exit 1
    fi
    echo 'Flow validation passed'
    ;;
  "flows deploy")
    printf 'deploy|%s\n' "$*" >> "$MOCK_LOG"
    ;;
  *) echo "Unexpected kestractl command: $command_name" >&2; exit 99 ;;
esac
""",
        encoding="utf-8",
    )
    mock.chmod(0o755)

    remote = tmp_path / "operator-remote"
    remote.mkdir()
    log = tmp_path / "operator-kestra.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "MOCK_REMOTE_ROOT": str(remote),
        "MOCK_LOG": str(log),
        "TEST_CANDIDATE_ID": candidate_id,
        "TEST_HISTORY_TOOLS_ID": tools_id,
        "TEST_REPLAY_FLOW_ID": flow_id,
    }
    return root, env


def test_step09_uploads_a_missing_baseline_directory_then_deploys_flow(tmp_path: Path) -> None:
    root, env = _prepare_operator_checkout(
        tmp_path, "09-deploy-dev-baseline.sh", with_python_env=True
    )
    flow = root / "core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml"
    flow.unlink()
    flow.parent.rmdir()
    flow.parent.mkdir(parents=True)
    flow.write_text("id: uwflow_dev_baseline_v2_0_0\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "tools/guides/workflow/09-deploy-dev-baseline.sh"],
        cwd=root,
        input="\ny\n",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Directory not found" not in result.stdout + result.stderr
    assert "has not been created yet" in result.stdout
    log = Path(env["MOCK_LOG"]).read_text(encoding="utf-8")
    assert log.splitlines()[0] == "validate|core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml"
    assert "upload|com.ai.credit.dev|" in log
    assert "runtime/releases/2.0.0" in log
    assert "deploy|core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml" in log


def test_step14_uploads_only_the_missing_current_candidate_directory(tmp_path: Path) -> None:
    root, env = _prepare_operator_checkout(
        tmp_path, "14-publish-history-replay-flow.sh", with_python_env=True
    )
    candidate_id = env["TEST_CANDIDATE_ID"]
    tools_id = env["TEST_HISTORY_TOOLS_ID"]
    flow_id = env["TEST_REPLAY_FLOW_ID"]
    state = root / "var/operator-state"
    state.mkdir()
    (state / "candidate-id").write_text(candidate_id + "\n", encoding="utf-8")
    (state / "baseline-release").write_text("2.0.0\n", encoding="utf-8")
    (state / "history-tools-bundle-id").write_text(tools_id + "\n", encoding="utf-8")
    (state / "replay-flow-id").write_text(flow_id + "\n", encoding="utf-8")

    remote = Path(env["MOCK_REMOTE_ROOT"])
    (remote / "runtime_releases_2.0.0").touch()
    (remote / f"history-tools_{tools_id}").touch()

    result = subprocess.run(
        ["bash", "tools/guides/workflow/14-publish-history-replay-flow.sh"],
        cwd=root,
        input="y\n\ny\n",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "Candidate, baseline, History bundle checksums and replay-flow identities verified."
        in result.stdout
    )
    assert "Flow validation passed" in result.stdout
    log = Path(env["MOCK_LOG"]).read_text(encoding="utf-8")
    assert log.splitlines()[0] == f"validate|var/artifacts/replay-flows/{flow_id}.yaml"
    uploads = [line for line in log.splitlines() if line.startswith("upload|")]
    assert len(uploads) == 1, log
    assert f"runtime/candidates/{candidate_id}" in uploads[0]
    assert f"deploy|var/artifacts/replay-flows/{flow_id}.yaml" in log


def test_step14_rejects_an_incomplete_candidate_before_validation_or_upload(tmp_path: Path) -> None:
    root, env = _prepare_operator_checkout(
        tmp_path, "14-publish-history-replay-flow.sh", with_python_env=True
    )
    candidate_id = env["TEST_CANDIDATE_ID"]
    tools_id = env["TEST_HISTORY_TOOLS_ID"]
    flow_id = env["TEST_REPLAY_FLOW_ID"]
    candidate_root = root / "var/artifacts/candidates" / candidate_id
    (candidate_root / "candidate-artifact-manifest.json").unlink()
    state = root / "var/operator-state"
    state.mkdir()
    (state / "candidate-id").write_text(candidate_id + "\n", encoding="utf-8")
    (state / "baseline-release").write_text("2.0.0\n", encoding="utf-8")
    (state / "history-tools-bundle-id").write_text(tools_id + "\n", encoding="utf-8")
    (state / "replay-flow-id").write_text(flow_id + "\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "tools/guides/workflow/14-publish-history-replay-flow.sh"],
        cwd=root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "Candidate is not a complete v2 artifact" in result.stderr
    log = (
        Path(env["MOCK_LOG"]).read_text(encoding="utf-8") if Path(env["MOCK_LOG"]).exists() else ""
    )
    assert "validate|" not in log and "upload|" not in log and "deploy|" not in log


def test_step14_validation_failure_stops_before_namespace_file_uploads_or_deploy(
    tmp_path: Path,
) -> None:
    root, env = _prepare_operator_checkout(
        tmp_path, "14-publish-history-replay-flow.sh", with_python_env=True
    )
    candidate_id = env["TEST_CANDIDATE_ID"]
    tools_id = env["TEST_HISTORY_TOOLS_ID"]
    flow_id = env["TEST_REPLAY_FLOW_ID"]
    state = root / "var/operator-state"
    state.mkdir()
    (state / "candidate-id").write_text(candidate_id + "\n", encoding="utf-8")
    (state / "baseline-release").write_text("2.0.0\n", encoding="utf-8")
    (state / "history-tools-bundle-id").write_text(tools_id + "\n", encoding="utf-8")
    (state / "replay-flow-id").write_text(flow_id + "\n", encoding="utf-8")
    env["MOCK_VALIDATE_MODE"] = "fail"

    result = subprocess.run(
        ["bash", "tools/guides/workflow/14-publish-history-replay-flow.sh"],
        cwd=root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "Validation failed: unsupported flow task property" in result.stderr
    log = Path(env["MOCK_LOG"]).read_text(encoding="utf-8")
    assert log.splitlines() == [f"validate|var/artifacts/replay-flows/{flow_id}.yaml"]
    assert not any(line.startswith("upload|") for line in log.splitlines())
    assert not any(line.startswith("deploy|") for line in log.splitlines())


def test_step09_validation_failure_stops_before_baseline_upload(tmp_path: Path) -> None:
    root, env = _prepare_operator_checkout(
        tmp_path, "09-deploy-dev-baseline.sh", with_python_env=True
    )
    flow = root / "core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml"
    flow.unlink()
    flow.parent.rmdir()
    flow.parent.mkdir(parents=True)
    flow.write_text("id: uwflow_dev_baseline_v2_0_0\n", encoding="utf-8")
    env["MOCK_VALIDATE_MODE"] = "fail"

    result = subprocess.run(
        ["bash", "tools/guides/workflow/09-deploy-dev-baseline.sh"],
        cwd=root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "Validation failed: unsupported flow task property" in result.stderr
    log = Path(env["MOCK_LOG"]).read_text(encoding="utf-8")
    assert log.splitlines() == [f"validate|{flow.relative_to(root).as_posix()}"]
    assert not any(line.startswith("upload|") for line in log.splitlines())
    assert not any(line.startswith("deploy|") for line in log.splitlines())
