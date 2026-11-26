#!/usr/bin/env python3
"""Small authenticated Kestra API client used only by the DEV Fast Route."""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

TERMINAL_STATES = {"SUCCESS", "FAILED", "KILLED", "CANCELLED", "WARNING"}


class KestraApiError(RuntimeError):
    """Raised when Kestra cannot accept or successfully complete a DEV run."""


class KestraHttpError(KestraApiError):
    """An HTTP response from Kestra, retaining its status for retry decisions."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        super().__init__(f"Kestra API returned HTTP {status_code}: {detail}")


def _credentials() -> str:
    username = os.environ.get("KESTRA_SERVER_BASIC_AUTH_USERNAME", "")
    password = os.environ.get("KESTRA_SERVER_BASIC_AUTH_PASSWORD", "")
    if not username or not password:
        raise KestraApiError(
            "Kestra credentials are not available in this process. Check the protected .env file."
        )
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    headers = {"Authorization": _credentials(), "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        detail = detail[:1200] if detail else exc.reason
        raise KestraHttpError(exc.code, detail) from exc
    except URLError as exc:
        raise KestraApiError(f"Kestra API connection failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise KestraApiError(f"Kestra API request timed out: {url}") from exc
    except (OSError, http.client.HTTPException) as exc:
        # During container startup Docker can accept the published TCP port
        # before the Kestra HTTP server is ready. The socket may be reset or
        # closed while plugins and the API are initializing. Normalize these
        # transport failures so wait_until_ready can retry them like other
        # transient startup responses instead of leaking a Python traceback.
        raise KestraApiError(f"Kestra API connection was interrupted: {exc}") from exc

    try:
        decoded = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise KestraApiError("Kestra API returned a response that was not valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise KestraApiError("Kestra API returned an unexpected JSON response shape.")
    return decoded


def wait_until_ready(base_url: str, timeout: int) -> None:
    """Wait for an authenticated Kestra flow-search request to succeed.

    Kestra's ``/api/v1/main/flows`` route creates a flow and accepts POST only.
    Listing/searching flows uses the separate GET ``/flows/search`` endpoint.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v1/main/flows/search?page=1&size=1"
    deadline = time.monotonic() + timeout
    last_error = "Kestra API is not ready yet."
    next_status = time.monotonic() + 15
    print(f"Waiting for authenticated Kestra API: {base_url}", flush=True)
    while time.monotonic() < deadline:
        try:
            _request_json(endpoint, timeout=10)
            print("Kestra API is ready and accepts the configured credentials.", flush=True)
            return
        except KestraApiError as exc:
            last_error = str(exc)
            # Authentication, authorization, and client/route errors are not
            # startup conditions. Retrying them only wastes the operator's time
            # and can hide an incorrect API path (for example, HTTP 405).
            if isinstance(exc, KestraHttpError) and 400 <= exc.status_code < 500:
                if exc.status_code not in {408, 425, 429}:
                    raise
            elif any(
                status in last_error
                for status in (
                    "HTTP 400",
                    "HTTP 401",
                    "HTTP 403",
                    "HTTP 404",
                    "HTTP 405",
                    "HTTP 422",
                )
            ):
                raise
            now = time.monotonic()
            if now >= next_status:
                print(
                    f"Kestra is still starting; retrying API readiness ({last_error}).", flush=True
                )
                next_status = now + 15
            time.sleep(min(3, max(0, deadline - now)))
    raise KestraApiError(f"Kestra did not become ready within {timeout}s. Last check: {last_error}")


HISTORY_SECRET_KEYS = (
    "SECRET_UWFLOW_HISTORY_CONNECTOR",
    "SECRET_UWFLOW_HISTORY_DSN",
    "SECRET_UWFLOW_HISTORY_ROOT",
)


def verify_container_secrets(container_name: str = "kestra") -> None:
    """Verify that a running Kestra container has the current history secrets.

    Docker's inspected environment is captured in memory and never printed. Only
    the names of missing or stale variables are included in an error message.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
                container_name,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise KestraApiError(
            "Docker CLI is not available; cannot inspect the Kestra container."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise KestraApiError(
            "Docker did not return the Kestra container environment within 15 seconds."
        ) from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "Docker could not inspect the container."
        raise KestraApiError(f"Unable to inspect container {container_name!r}: {detail}")

    actual: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            actual[key] = value

    stale = [
        key
        for key in HISTORY_SECRET_KEYS
        if not os.environ.get(key) or actual.get(key) != os.environ.get(key)
    ]
    if stale:
        names = ", ".join(stale)
        raise KestraApiError(
            f"Container {container_name!r} is missing or has stale history secrets: {names}. "
            "Stop the local Kestra container with docker stop kestra, then rerun the DEV Fast Route. "
            "Its named data volumes will be preserved."
        )

    print(f"Container {container_name!r} has the current read-only history secrets.", flush=True)


def _multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"uwflow-fast-route-{os.urandom(12).hex()}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _execution_state(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    if isinstance(state, dict):
        return str(state.get("current") or "UNKNOWN").upper()
    return "UNKNOWN"


def _save_execution_id(path: str | None, execution_id: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(execution_id + "\n", encoding="utf-8")
    temporary.replace(target)


FAST_ROUTE_REQUEST_LABEL = "uwflow.fastRouteRequestId"


def _request_marker_path(state_file: str | None) -> Path | None:
    if not state_file:
        return None
    return Path(f"{state_file}.request.json")


def _load_or_create_request_marker(state_file: str | None) -> tuple[str, str, bool]:
    """Persist a unique trigger label before POST so an ambiguous response is recoverable."""
    marker = _request_marker_path(state_file)
    if marker is not None and marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            request_id = str(payload["request_id"]).strip()
            created_at = str(payload["created_at"]).strip()
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise KestraApiError(
                f"The persisted Kestra trigger marker is invalid: {marker}. "
                "Inspect it before retrying; the flow was not submitted again."
            ) from exc
        if not request_id or not created_at:
            raise KestraApiError(
                f"The persisted Kestra trigger marker is incomplete: {marker}. "
                "Inspect it before retrying; the flow was not submitted again."
            )
        return request_id, created_at, True

    request_id = uuid4().hex
    created_at = (
        datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    if marker is not None:
        marker.parent.mkdir(parents=True, exist_ok=True)
        temporary = marker.with_suffix(marker.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"request_id": request_id, "created_at": created_at}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(marker)
    return request_id, created_at, False


def _clear_request_marker(state_file: str | None) -> None:
    marker = _request_marker_path(state_file)
    if marker is not None:
        marker.unlink(missing_ok=True)


def _execution_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract execution rows from Kestra's paginated search response."""
    for key in ("results", "items", "content", "executions", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _has_request_label(item: dict[str, Any], request_id: str) -> bool:
    labels = item.get("labels")
    if isinstance(labels, dict):
        return labels.get(FAST_ROUTE_REQUEST_LABEL) == request_id
    if isinstance(labels, list):
        return any(
            isinstance(label, dict)
            and label.get("key") == FAST_ROUTE_REQUEST_LABEL
            and label.get("value") == request_id
            for label in labels
        )
    return False


def _find_triggered_execution(
    base_url: str,
    namespace: str,
    flow_id: str,
    request_id: str,
) -> dict[str, Any] | None:
    """Find the main execution carrying this Fast Route request label."""
    query = urlencode(
        {
            "filters[namespace][EQUALS]": namespace,
            "filters[flowId][EQUALS]": flow_id,
            "filters[childFilter][EQUALS]": "MAIN",
            f"filters[labels][EQUALS][{FAST_ROUTE_REQUEST_LABEL}]": request_id,
            "page": "1",
            "size": "20",
        }
    )
    endpoint = f"{base_url.rstrip('/')}/api/v1/main/executions/search?{query}"
    payload = _request_json(endpoint, timeout=20)
    matches = [
        item
        for item in _execution_items(payload)
        if item.get("namespace") == namespace
        and item.get("flowId") == flow_id
        and item.get("id")
        and _has_request_label(item, request_id)
    ]
    if len(matches) > 1:
        execution_ids = ", ".join(str(item.get("id")) for item in matches)
        raise KestraApiError(
            "More than one main execution has the same UWflow Fast Route request label "
            f"{request_id}: {execution_ids}. No execution was selected automatically."
        )
    return matches[0] if matches else None


def _wait_for_triggered_execution(
    base_url: str,
    namespace: str,
    flow_id: str,
    request_id: str,
    timeout: int,
    state_file: str | None,
) -> str:
    """Reconcile an uncertain POST using its unique execution label; never POST twice."""
    deadline = time.monotonic() + timeout
    print(
        "Kestra did not confirm the trigger request. Searching execution history "
        f"for UWflow request {request_id}; no duplicate trigger will be sent.",
        flush=True,
    )
    last_error: str | None = None
    while True:
        try:
            match = _find_triggered_execution(base_url, namespace, flow_id, request_id)
            if match is not None:
                execution_id = str(match["id"])
                print(f"Recovered Kestra execution ID: {execution_id}", flush=True)
                return execution_id
        except KestraApiError as exc:
            last_error = str(exc)
            if isinstance(exc, KestraHttpError) and 400 <= exc.status_code < 500:
                if exc.status_code not in {408, 425, 429}:
                    raise

        now = time.monotonic()
        if now >= deadline:
            detail = f" Last search error: {last_error}." if last_error else ""
            raise KestraApiError(
                "Kestra's trigger response was ambiguous, and no matching execution appeared "
                f"within {timeout}s. No duplicate trigger was sent. The request marker was retained. "
                "Inspect Kestra Executions for label "
                f"{FAST_ROUTE_REQUEST_LABEL}={request_id}. If the execution exists, rerun the Fast "
                "Route to resume monitoring. If it does not exist, remove only the matching "
                f"request marker ({_request_marker_path(state_file)}) after confirming "
                f"absence in Kestra.{detail}"
            )
        time.sleep(min(2, max(0, deadline - now)))


def _is_retryable_status_poll_error(exc: KestraApiError) -> bool:
    if isinstance(exc, KestraHttpError):
        return exc.status_code in {408, 425, 429, 500, 502, 503, 504}
    return True


def execute_and_wait(
    base_url: str,
    namespace: str,
    flow_id: str,
    label: str,
    inputs: dict[str, str],
    timeout: int,
    state_file: str,
    poll_interval: int,
    reconcile_timeout: int = 120,
) -> str:
    """Trigger once, recover ambiguous API responses, and require SUCCESS."""
    if not state_file:
        raise KestraApiError(
            "A persistent --state-file is required for safe Kestra triggering. "
            "It prevents duplicate submissions when the API response is ambiguous."
        )
    namespace_path = quote(namespace, safe="")
    flow_path = quote(flow_id, safe="")
    request_id, _, resuming = _load_or_create_request_marker(state_file)
    query = urlencode({"labels": f"{FAST_ROUTE_REQUEST_LABEL}:{request_id}"})
    endpoint = f"{base_url.rstrip('/')}/api/v1/main/executions/{namespace_path}/{flow_path}?{query}"

    execution_id = ""
    if resuming:
        print(
            f"Resuming Kestra trigger reconciliation for UWflow request {request_id}.",
            flush=True,
        )
        execution_id = _wait_for_triggered_execution(
            base_url, namespace, flow_id, request_id, reconcile_timeout, state_file
        )
    else:
        body: bytes | None = None
        content_type: str | None = None
        if inputs:
            body, content_type = _multipart(inputs)

        print(f"\nStarting Kestra {label}: {namespace}/{flow_id}", flush=True)
        try:
            started = _request_json(
                endpoint,
                method="POST",
                body=body,
                content_type=content_type,
                timeout=60,
            )
            execution_id = str(started.get("id") or "")
            if not execution_id:
                print(
                    "Kestra accepted the request without an execution ID; reconciling by label.",
                    flush=True,
                )
        except KestraApiError as exc:
            # A 5xx/transport failure can happen after the server accepted the
            # request. Persisted label + read-only search prevents a duplicate.
            if (
                isinstance(exc, KestraHttpError)
                and exc.status_code < 500
                and exc.status_code not in {408, 425, 429}
            ):
                _clear_request_marker(state_file)
                raise
            print(f"Kestra trigger response was not conclusive: {exc}", flush=True)

        if not execution_id:
            execution_id = _wait_for_triggered_execution(
                base_url, namespace, flow_id, request_id, reconcile_timeout, state_file
            )

    _save_execution_id(state_file, execution_id)
    print(f"Execution ID: {execution_id}", flush=True)

    status_endpoint = (
        f"{base_url.rstrip('/')}/api/v1/main/executions/{quote(execution_id, safe='')}"
    )
    deadline = time.monotonic() + timeout
    last_state = ""
    last_status_error: str | None = None
    while time.monotonic() < deadline:
        try:
            payload = _request_json(status_endpoint, timeout=30)
            last_status_error = None
        except KestraApiError as exc:
            if not _is_retryable_status_poll_error(exc):
                raise
            last_status_error = str(exc)
            time.sleep(max(1, poll_interval))
            continue

        state = _execution_state(payload)
        if state != last_state:
            print(f"  {label} state: {state}", flush=True)
            last_state = state
        if state in TERMINAL_STATES:
            _print_task_states(payload)
            _clear_request_marker(state_file)
            if state != "SUCCESS":
                raise KestraApiError(
                    f"Kestra {label} finished with state {state}. "
                    f"Inspect execution {execution_id} in the Kestra UI."
                )
            print(f"Kestra {label} completed successfully.", flush=True)
            return execution_id
        time.sleep(max(1, poll_interval))

    detail = f" Last status check: {last_status_error}." if last_status_error else ""
    raise KestraApiError(
        f"Kestra {label} did not finish within {timeout}s. Execution {execution_id} "
        f"is still available in Kestra; rerunning the Fast Route will resume this execution.{detail}"
    )


def _print_task_states(payload: dict[str, Any]) -> None:
    task_runs = payload.get("taskRunList")
    if not isinstance(task_runs, list):
        return
    for task in task_runs:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("taskId") or task.get("id") or "task")
        task_state = task.get("state")
        current = (
            str(task_state.get("current") or "UNKNOWN")
            if isinstance(task_state, dict)
            else "UNKNOWN"
        )
        print(f"  Task {task_id}: {current}", flush=True)


def main(argv: list[str] | None = None) -> int:
    """Expose the narrow CLI operations used by the DEV Fast Route for Kestra readiness and execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ready = subparsers.add_parser("wait-ready", help="Wait for authenticated Kestra API readiness")
    ready.add_argument("--base-url", default="http://localhost:8080")
    ready.add_argument("--timeout", type=int, default=240)

    verify = subparsers.add_parser(
        "verify-container-secrets",
        help="Verify that the Kestra container loaded the current history secrets",
    )
    verify.add_argument("--container", default="kestra")

    execute = subparsers.add_parser("execute", help="Trigger a DEV flow and wait for SUCCESS")
    execute.add_argument("--base-url", default="http://localhost:8080")
    execute.add_argument("--namespace", default="com.ai.credit.dev")
    execute.add_argument("--flow-id", required=True)
    execute.add_argument("--label", required=True)
    execute.add_argument("--timeout", type=int, default=1800)
    execute.add_argument("--poll-interval", type=int, default=5)
    execute.add_argument("--reconcile-timeout", type=int, default=120)
    execute.add_argument("--state-file", required=True)
    execute.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")

    args = parser.parse_args(argv)
    try:
        if args.command == "wait-ready":
            wait_until_ready(args.base_url, args.timeout)
            return 0
        if args.command == "verify-container-secrets":
            verify_container_secrets(args.container)
            return 0

        values: dict[str, str] = {}
        for item in args.input:
            key, separator, value = item.partition("=")
            if not separator or not key:
                raise KestraApiError(f"Invalid --input {item!r}; expected KEY=VALUE.")
            if key in values:
                raise KestraApiError(f"Duplicate flow input: {key}")
            values[key] = value
        execute_and_wait(
            args.base_url,
            args.namespace,
            args.flow_id,
            args.label,
            values,
            args.timeout,
            args.state_file,
            args.poll_interval,
            args.reconcile_timeout,
        )
        return 0
    except KestraApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
