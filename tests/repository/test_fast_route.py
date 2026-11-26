"""Tests for the complete local DEV Fast Route and its operator-step ordering."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / "tools/kestra/fast_route_api.py"
SPEC = importlib.util.spec_from_file_location("fast_route_api", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
fast_route_kestra = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fast_route_kestra)


def test_fast_route_shell_syntax_and_operator_script_order() -> None:
    launcher = ROOT / "tools/guides/workflow/dev-fast-route.sh"
    content = launcher.read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(launcher)], check=True, cwd=ROOT)

    expected = [
        "00-preflight.sh",
        "01-python-environment.sh",
        "02-build-studio-images.sh",
        "08-install-kestra-cli.sh",
        "03-create-local-credentials.sh",
        "04-create-history-credentials.sh",
        "05-build-task-image.sh",
        "06-start-history-database.sh",
        "07-start-kestra.sh",
        "09-deploy-dev-baseline.sh",
        "10-initialize-history-database.sh",
        "11-select-or-create-dataset.sh",
        "12-run-local-noop-replay.sh",
        "13-build-history-replay-flow.sh",
        "14-publish-history-replay-flow.sh",
        "15-start-studio.sh",
    ]
    positions = [content.index(name) for name in expected]
    assert positions == sorted(positions)
    assert "fast_route_api.py wait-ready" in content
    assert "single-application underwriting smoke test" in content
    assert "100-case champion/challenger replay" in content
    assert "max_cases=100" in content
    assert "Verify the local no-op replay comparison" in content
    assert "UWFLOW_FAST_ROUTE_AUTO_UPLOAD=true" in content
    assert "UWFLOW_FAST_ROUTE_AUTO_DEPLOY=true" in content
    assert "UWFLOW_STUDIO_DETACHED=true" in content
    assert '"$(uname -s)" != "Linux"' in content

    # The initial pytest process must not inherit Fast Route automation flags,
    # even when the calling shell had stale flags set before launching the route.
    assert content.index("unset UWFLOW_FAST_ROUTE") < content.index(
        'run_step "01 — Python environment'
    )
    assert content.index('run_step "01 — Python environment') < content.index(
        "export UWFLOW_FAST_ROUTE=true"
    )
    assert content.index('run_step "02 — Build Policy Studio Docker images') < content.index(
        "export UWFLOW_FAST_ROUTE=true"
    )
    assert content.index("100-case champion/challenger replay") < content.index(
        "15 — Start and verify"
    )
    assert not (ROOT / "tools/guides/workflow/dev-fast-route.bat").exists()


def test_kestra_cli_installation_requires_explicit_approval() -> None:
    installer = (ROOT / "tools/guides/workflow/08-install-kestra-cli.sh").read_text(
        encoding="utf-8"
    )
    assert (
        'read -r -p "Install kestractl from the official Kestra installer now? [y/N] "' in installer
    )
    assert "y|yes)" in installer
    assert "kestractl was not installed" in installer


def test_policy_studio_is_a_required_fast_route_dependency() -> None:
    launcher = (ROOT / "tools/guides/workflow/dev-fast-route.sh").read_text(encoding="utf-8")
    studio = (ROOT / "tools/guides/workflow/15-start-studio.sh").read_text(encoding="utf-8")
    guide = (ROOT / "docs/development/dev-fast-route.md").read_text(encoding="utf-8")
    assert "02-build-studio-images.sh" in launcher
    assert "15-start-studio.sh" in launcher
    assert "docker inspect --format" in studio
    assert "api_health" in studio
    assert 'curl --silent --fail --max-time 3 "http://127.0.0.1:${WEB_PORT}/"' in studio
    assert "http://127.0.0.1:${WEB_PORT}/api/stages" in studio
    assert "Build the Policy Studio API and frontend images" in guide
    assert "Studio API" in guide and "frontend" in guide
    assert "required, not optional" not in guide


def test_linux_only_fast_route_has_no_windows_wrapper() -> None:
    launcher = (ROOT / "tools/guides/workflow/dev-fast-route.sh").read_text(encoding="utf-8")
    guide = (ROOT / "docs/development/dev-fast-route.md").read_text(encoding="utf-8")
    assert "Linux host" in launcher
    assert "Linux" in guide and "Docker Compose V2" in guide
    assert not (ROOT / "tools/guides/workflow/dev-fast-route.bat").exists()


def test_fast_route_kestra_form_inputs_are_multipart() -> None:
    body, content_type = fast_route_kestra._multipart(
        {"dataset_id": "synthetic-test", "batch_size": "2000", "max_cases": "100"}
    )
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="dataset_id"\r\n\r\nsynthetic-test' in body
    assert b'name="batch_size"\r\n\r\n2000' in body
    assert b'name="max_cases"\r\n\r\n100' in body


def test_fast_route_kestra_waits_until_execution_is_successful(tmp_path: Path) -> None:
    state_file = tmp_path / "var/operator-state" / "execution-id"
    responses = [
        {"id": "execution-123", "state": {"current": "CREATED"}},
        {"id": "execution-123", "state": {"current": "RUNNING"}},
        {
            "id": "execution-123",
            "state": {"current": "SUCCESS"},
            "taskRunList": [{"taskId": "compare_replays", "state": {"current": "SUCCESS"}}],
        },
    ]
    with (
        patch.object(fast_route_kestra, "_request_json", side_effect=responses),
        patch.object(fast_route_kestra.time, "sleep"),
    ):
        execution_id = fast_route_kestra.execute_and_wait(
            "http://localhost:8080",
            "com.ai.credit.dev",
            "uwflow_dev_history_replay_test",
            "paired replay",
            {"dataset_id": "synthetic-test", "max_cases": "100"},
            timeout=30,
            state_file=str(state_file),
            poll_interval=1,
        )

    assert execution_id == "execution-123"
    assert state_file.read_text(encoding="utf-8").strip() == "execution-123"


def test_fast_route_kestra_rejects_failed_execution(tmp_path: Path) -> None:
    responses = [
        {"id": "execution-failed"},
        {"id": "execution-failed", "state": {"current": "FAILED"}},
    ]
    with (
        patch.object(fast_route_kestra, "_request_json", side_effect=responses),
        patch.object(fast_route_kestra.time, "sleep"),
        patch("builtins.print"),
    ):
        try:
            fast_route_kestra.execute_and_wait(
                "http://localhost:8080",
                "com.ai.credit.dev",
                "uwflow_dev_history_replay_test",
                "paired replay",
                {},
                timeout=30,
                state_file=str(tmp_path / "execution-id"),
                poll_interval=1,
            )
        except fast_route_kestra.KestraApiError as exc:
            assert "finished with state FAILED" in str(exc)
        else:
            raise AssertionError("A failed Kestra execution must stop the Fast Route")


def test_detached_kestra_mode_is_opt_in_and_keeps_foreground_default() -> None:
    launcher = (ROOT / "core/docker-run.sh").read_text(encoding="utf-8")
    starter = (ROOT / "tools/guides/workflow/07-start-kestra.sh").read_text(encoding="utf-8")
    assert 'if [[ "${UWFLOW_KESTRA_DETACHED:-false}" == "true" ]]' in launcher
    assert "RUN_MODE=(-d)" in launcher
    assert "RUN_MODE=(-it)" in launcher
    assert 'if [[ "${UWFLOW_KESTRA_DETACHED:-false}" == "true" ]]' in starter


def test_fast_route_guide_is_linked_from_navigation() -> None:
    guide = ROOT / "docs/development/dev-fast-route.md"
    assert guide.is_file()
    assert "bash tools/guides/workflow/dev-fast-route.sh" in guide.read_text(encoding="utf-8")
    assert "DEV Fast Route" in (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "DEV Fast Route" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_fast_route_kestra_readiness_uses_supported_authenticated_search_endpoint() -> None:
    with (
        patch.object(fast_route_kestra, "_request_json", return_value={}) as request,
        patch("builtins.print"),
    ):
        fast_route_kestra.wait_until_ready("http://localhost:8080", timeout=30)

    assert request.call_count == 1
    assert request.call_args.args[0] == (
        "http://localhost:8080/api/v1/main/flows/search?page=1&size=1"
    )


def test_fast_route_kestra_method_not_allowed_fails_immediately() -> None:
    error = fast_route_kestra.KestraHttpError(405, "Method [GET] not allowed")
    with (
        patch.object(fast_route_kestra, "_request_json", side_effect=error),
        patch.object(fast_route_kestra.time, "sleep") as sleep,
    ):
        try:
            fast_route_kestra.wait_until_ready("http://localhost:8080", timeout=240)
        except fast_route_kestra.KestraApiError as exc:
            assert "HTTP 405" in str(exc)
        else:
            raise AssertionError("An unsupported API method must fail immediately")
        sleep.assert_not_called()


def test_fast_route_kestra_auth_failure_does_not_wait_for_timeout() -> None:
    with (
        patch.object(
            fast_route_kestra,
            "_request_json",
            side_effect=fast_route_kestra.KestraApiError(
                "Kestra API returned HTTP 401: unauthorized"
            ),
        ),
        patch.object(fast_route_kestra.time, "sleep") as sleep,
    ):
        try:
            fast_route_kestra.wait_until_ready("http://localhost:8080", timeout=240)
        except fast_route_kestra.KestraApiError as exc:
            assert "HTTP 401" in str(exc)
        else:
            raise AssertionError("Invalid credentials must fail immediately")
        sleep.assert_not_called()


def test_kestra_api_connection_reset_during_startup_is_retried() -> None:
    import io

    with (
        patch.object(
            fast_route_kestra,
            "urlopen",
            side_effect=[ConnectionResetError(104, "Connection reset by peer"), io.BytesIO(b"{}")],
        ) as urlopen,
        patch.object(fast_route_kestra.time, "sleep") as sleep,
        patch.object(fast_route_kestra, "_credentials", return_value="Basic dGVzdDp0ZXN0"),
        patch("builtins.print"),
    ):
        fast_route_kestra.wait_until_ready("http://localhost:8080", timeout=30)

    assert urlopen.call_count == 2
    sleep.assert_called_once_with(3)


def test_kestra_api_request_normalizes_remote_disconnect() -> None:
    import http.client

    with (
        patch.object(
            fast_route_kestra,
            "urlopen",
            side_effect=http.client.RemoteDisconnected("remote end closed connection"),
        ),
        patch.object(fast_route_kestra, "_credentials", return_value="Basic dGVzdDp0ZXN0"),
    ):
        try:
            fast_route_kestra._request_json(
                "http://localhost:8080/api/v1/main/flows/search?page=1&size=1"
            )
        except fast_route_kestra.KestraApiError as exc:
            assert "connection was interrupted" in str(exc)
        else:
            raise AssertionError("A remote disconnect must be normalized for readiness retry")


def test_kestra_history_secret_verification_compares_without_printing_values() -> None:
    expected = {
        "SECRET_UWFLOW_HISTORY_CONNECTOR": "cG9zdGdyZXM=",
        "SECRET_UWFLOW_HISTORY_DSN": "c2VjcmV0LWRzbg==",
        "SECRET_UWFLOW_HISTORY_ROOT": "L2RhdGEvdXdmbG93L2hpc3Rvcnk=",
    }
    stdout = "\n".join(f"{key}={value}" for key, value in expected.items())
    completed = subprocess.CompletedProcess(
        args=["docker", "inspect"], returncode=0, stdout=stdout, stderr=""
    )
    with (
        patch.dict(os.environ, expected, clear=False),
        patch.object(fast_route_kestra.subprocess, "run", return_value=completed) as run,
        patch("builtins.print") as print_output,
    ):
        fast_route_kestra.verify_container_secrets("kestra")

    assert run.call_args.args[0] == [
        "docker",
        "inspect",
        "--format",
        "{{range .Config.Env}}{{println .}}{{end}}",
        "kestra",
    ]
    printed = " ".join(str(call.args) for call in print_output.call_args_list)
    assert all(value not in printed for value in expected.values())


def test_kestra_history_secret_verification_rejects_stale_values_without_leaking_them() -> None:
    expected = {
        "SECRET_UWFLOW_HISTORY_CONNECTOR": "cG9zdGdyZXM=",
        "SECRET_UWFLOW_HISTORY_DSN": "c2VjcmV0LWRzbg==",
        "SECRET_UWFLOW_HISTORY_ROOT": "L2RhdGEvdXdmbG93L2hpc3Rvcnk=",
    }
    actual = dict(expected)
    actual["SECRET_UWFLOW_HISTORY_DSN"] = "c3RhbGU="
    stdout = "\n".join(f"{key}={value}" for key, value in actual.items())
    completed = subprocess.CompletedProcess(
        args=["docker", "inspect"], returncode=0, stdout=stdout, stderr=""
    )
    with (
        patch.dict(os.environ, expected, clear=False),
        patch.object(fast_route_kestra.subprocess, "run", return_value=completed),
    ):
        try:
            fast_route_kestra.verify_container_secrets("kestra")
        except fast_route_kestra.KestraApiError as exc:
            assert "SECRET_UWFLOW_HISTORY_DSN" in str(exc)
            assert all(value not in str(exc) for value in expected.values())
        else:
            raise AssertionError("A stale Kestra history secret must stop the Fast Route")


def test_fast_route_reconciles_kestra_504_without_duplicate_trigger(tmp_path: Path) -> None:
    state_file = tmp_path / "var/operator-state" / "baseline-smoke-execution-id"
    request_id = "fast-route-request-123"
    search_result = {
        "results": [
            {
                "id": "execution-after-504",
                "namespace": "com.ai.credit.dev",
                "flowId": "uwflow_dev_baseline_test",
                "labels": [
                    {"key": "uwflow.fastRouteRequestId", "value": request_id},
                ],
            }
        ]
    }
    execution_result = {
        "id": "execution-after-504",
        "namespace": "com.ai.credit.dev",
        "flowId": "uwflow_dev_baseline_test",
        "state": {"current": "SUCCESS"},
        "taskRunList": [{"taskId": "stage7_render_report", "state": {"current": "SUCCESS"}}],
    }
    with (
        patch.object(
            fast_route_kestra,
            "_request_json",
            side_effect=[
                fast_route_kestra.KestraHttpError(504, "Operation timed out"),
                search_result,
                execution_result,
            ],
        ) as request,
        patch("builtins.print"),
    ):
        # Make the request identifier deterministic for URL assertions.
        with (
            patch.object(
                fast_route_kestra,
                "_load_or_create_request_marker",
                return_value=(request_id, "2026-11-24T16:00:00Z", False),
            ),
            patch.object(fast_route_kestra, "_clear_request_marker") as clear_marker,
        ):
            execution_id = fast_route_kestra.execute_and_wait(
                "http://localhost:8080",
                "com.ai.credit.dev",
                "uwflow_dev_baseline_test",
                "single-application underwriting smoke test",
                {},
                timeout=30,
                state_file=str(state_file),
                poll_interval=1,
                reconcile_timeout=0,
            )

    assert execution_id == "execution-after-504"
    assert state_file.read_text(encoding="utf-8").strip() == execution_id
    assert request.call_count == 3  # POST once, search once, then monitor by ID.
    post_call = request.call_args_list[0]
    assert post_call.kwargs["method"] == "POST"
    assert "labels=uwflow.fastRouteRequestId%3Afast-route-request-123" in post_call.args[0]
    search_url = request.call_args_list[1].args[0]
    assert "/api/v1/main/executions/search?" in search_url
    assert (
        "filters%5Blabels%5D%5BEQUALS%5D%5Buwflow.fastRouteRequestId%5D=fast-route-request-123"
        in search_url
    )
    assert "filters%5BchildFilter%5D%5BEQUALS%5D=MAIN" in search_url
    clear_marker.assert_called_once_with(str(state_file))


def test_fast_route_resumes_existing_trigger_marker_without_posting_again(tmp_path: Path) -> None:
    state_file = tmp_path / "var/operator-state" / "history-replay-execution-id"
    marker = Path(f"{state_file}.request.json")
    marker.parent.mkdir(parents=True)
    marker.write_text(
        '{"created_at":"2026-11-24T16:00:00Z","request_id":"resume-request-1"}\n',
        encoding="utf-8",
    )
    search_result = {
        "results": [
            {
                "id": "execution-already-created",
                "namespace": "com.ai.credit.dev",
                "flowId": "uwflow_dev_history_replay_test",
                "labels": {"uwflow.fastRouteRequestId": "resume-request-1"},
            }
        ]
    }
    execution_result = {
        "id": "execution-already-created",
        "state": {"current": "SUCCESS"},
    }
    with (
        patch.object(
            fast_route_kestra,
            "_request_json",
            side_effect=[search_result, execution_result],
        ) as request,
        patch("builtins.print"),
    ):
        execution_id = fast_route_kestra.execute_and_wait(
            "http://localhost:8080",
            "com.ai.credit.dev",
            "uwflow_dev_history_replay_test",
            "paired replay",
            {"max_cases": "100"},
            timeout=30,
            state_file=str(state_file),
            poll_interval=1,
            reconcile_timeout=0,
        )

    assert execution_id == "execution-already-created"
    assert state_file.read_text(encoding="utf-8").strip() == execution_id
    assert not marker.exists()
    assert request.call_count == 2
    assert "/api/v1/main/executions/search?" in request.call_args_list[0].args[0]
    assert "/executions/execution-already-created" in request.call_args_list[1].args[0]


def test_fast_route_keeps_marker_and_never_retriggers_when_504_has_no_search_match(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "var/operator-state" / "baseline-smoke-execution-id"
    with (
        patch.object(
            fast_route_kestra,
            "_request_json",
            side_effect=[
                fast_route_kestra.KestraHttpError(504, "Operation timed out"),
                {"results": []},
            ],
        ) as request,
        patch("builtins.print"),
    ):
        try:
            fast_route_kestra.execute_and_wait(
                "http://localhost:8080",
                "com.ai.credit.dev",
                "uwflow_dev_baseline_test",
                "baseline smoke test",
                {},
                timeout=30,
                state_file=str(state_file),
                poll_interval=1,
                reconcile_timeout=0,
            )
        except fast_route_kestra.KestraApiError as exc:
            assert "No duplicate trigger was sent" in str(exc)
            assert "uwflow.fastRouteRequestId=" in str(exc)
            assert str(state_file) + ".request.json" in str(exc)
        else:
            raise AssertionError(
                "An ambiguous trigger without a searchable execution must stop safely"
            )

    assert request.call_count == 2  # One POST, then one read-only search; never a second POST.
    assert not state_file.exists()
    marker = Path(f"{state_file}.request.json")
    assert marker.is_file()
    payload = __import__("json").loads(marker.read_text(encoding="utf-8"))
    assert payload["request_id"]
    assert marker.stat().st_mode & 0o777 == 0o600


def test_fast_route_rejects_multiple_executions_with_one_request_label() -> None:
    labels = [{"key": "uwflow.fastRouteRequestId", "value": "ambiguous-key"}]
    with patch.object(
        fast_route_kestra,
        "_request_json",
        return_value={
            "results": [
                {"id": "execution-1", "namespace": "n", "flowId": "f", "labels": labels},
                {"id": "execution-2", "namespace": "n", "flowId": "f", "labels": labels},
            ]
        },
    ):
        try:
            fast_route_kestra._find_triggered_execution(
                "http://localhost:8080", "n", "f", "ambiguous-key"
            )
        except fast_route_kestra.KestraApiError as exc:
            assert "More than one main execution" in str(exc)
            assert "execution-1" in str(exc) and "execution-2" in str(exc)
        else:
            raise AssertionError("Multiple matches must never be selected arbitrarily")


def test_fast_route_retries_transient_execution_status_504(tmp_path: Path) -> None:
    state_file = tmp_path / "var/operator-state" / "execution-id"
    with (
        patch.object(
            fast_route_kestra,
            "_request_json",
            side_effect=[
                {"id": "execution-123"},
                fast_route_kestra.KestraHttpError(504, "Operation timed out"),
                {"id": "execution-123", "state": {"current": "SUCCESS"}},
            ],
        ) as request,
        patch.object(fast_route_kestra.time, "sleep"),
        patch("builtins.print"),
        patch.object(
            fast_route_kestra,
            "_load_or_create_request_marker",
            return_value=("request-1", "now", False),
        ),
        patch.object(fast_route_kestra, "_clear_request_marker"),
    ):
        execution_id = fast_route_kestra.execute_and_wait(
            "http://localhost:8080",
            "com.ai.credit.dev",
            "uwflow_dev_history_replay_test",
            "paired replay",
            {},
            timeout=30,
            state_file=str(state_file),
            poll_interval=1,
        )

    assert execution_id == "execution-123"
    assert request.call_count == 3
