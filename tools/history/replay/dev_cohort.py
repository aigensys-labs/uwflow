"""Replay a de-identified JSONL cohort through DEV baseline and candidate flows.

This script calls the Kestra API only in the configured DEV namespace. It never
submits executions to the production namespace. It writes one CSV comparison row
per cohort member plus a small aggregate JSON report.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
from pathlib import Path
import time
from typing import Any
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REQUIRED_INPUTS = {
    "applicant_id",
    "applicant_name",
    "applicant_age",
    "monthly_income",
    "requested_amount",
    "employment_status",
    "existing_monthly_debt_payments",
    "monthly_housing_cost",
    "loan_term_months",
    "data_sharing_consent",
    "currency",
}
TERMINAL_STATES = {"SUCCESS", "FAILED", "WARNING", "KILLED", "CANCELLED", "EXPIRED"}
DEV_NAMESPACE = "com.ai.credit.dev"


class KestraReplayError(RuntimeError):
    """Raised for an API or execution failure during DEV cohort replay."""


def _auth_header(username: str | None, password: str | None) -> str | None:
    if username is None and password is None:
        return None
    if not username or password is None:
        raise KestraReplayError(
            "Set both KESTRACTL_USERNAME and KESTRACTL_PASSWORD for authenticated API access"
        )
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise KestraReplayError(f"Kestra API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise KestraReplayError(f"Cannot reach Kestra API: {exc.reason}") from exc
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise KestraReplayError("Kestra API returned a non-JSON response") from exc
    if not isinstance(value, dict):
        raise KestraReplayError("Kestra API returned an unexpected JSON structure")
    return value


def _encode_multipart_form(fields: dict[str, str]) -> tuple[str, bytes]:
    """Encode simple Kestra execution inputs as multipart/form-data.

    Kestra's execution API documents form-data inputs; using a fresh boundary
    avoids relying on application/x-www-form-urlencoded parser behavior.
    Field names are fixed by the underwriting flow contract.
    """
    boundary = f"uwflow-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if any(character in name for character in ("\r", "\n", '"')):
            raise KestraReplayError(f"Invalid multipart field name: {name!r}")
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n'
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            f"{value}\r\n".encode("utf-8")
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return boundary, b"".join(chunks)


def _validate_application(application: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(application, dict):
        raise KestraReplayError("Each JSONL cohort row must be a JSON object")
    missing = sorted(REQUIRED_INPUTS - set(application))
    extra = sorted(set(application) - REQUIRED_INPUTS)
    if missing or extra:
        raise KestraReplayError(
            f"Invalid cohort input keys; missing={missing}, unsupported={extra}"
        )
    for field in ("applicant_id", "applicant_name", "employment_status", "currency"):
        if not isinstance(application[field], str) or not application[field].strip():
            raise KestraReplayError(f"{field} must be a non-empty string")
    if not isinstance(application["data_sharing_consent"], bool):
        raise KestraReplayError("data_sharing_consent must be a JSON boolean")
    for field in ("applicant_age", "loan_term_months"):
        if isinstance(application[field], bool) or not isinstance(application[field], int):
            raise KestraReplayError(f"{field} must be an integer")
    for field in (
        "monthly_income",
        "requested_amount",
        "existing_monthly_debt_payments",
        "monthly_housing_cost",
    ):
        value = application[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise KestraReplayError(f"{field} must be a finite number")
    return application


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict):
        if "value" in value and len(value) <= 4:
            return _unwrap(value["value"])
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    return value


def _find_named_value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        if name in value:
            candidate = _unwrap(value[name])
            if candidate is not None:
                return candidate
        for item in value.values():
            found = _find_named_value(item, name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_named_value(item, name)
            if found is not None:
                return found
    return None


def _execution_state(execution: dict[str, Any]) -> str:
    state = execution.get("state", {})
    if isinstance(state, dict):
        return str(state.get("current", "UNKNOWN")).upper()
    return str(state or "UNKNOWN").upper()


class KestraClient:
    """Small DEV-scoped Kestra API client used by the sample cohort replay tool."""

    def __init__(
        self,
        base_url: str,
        tenant: str,
        namespace: str,
        username: str | None,
        password: str | None,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant = quote(tenant, safe="")
        self.namespace = quote(namespace, safe="")
        self.timeout = timeout
        self.headers = {"Accept": "application/json"}
        auth = _auth_header(username, password)
        if auth:
            self.headers["Authorization"] = auth

    def execute(
        self, flow_id: str, application: dict[str, Any], poll_seconds: float
    ) -> dict[str, Any]:
        """Submit one application to the named DEV flow and poll for a terminal result."""
        encoded_inputs = {
            key: json.dumps(value, separators=(",", ":"))
            if isinstance(value, (bool, list, dict))
            else str(value)
            for key, value in application.items()
        }
        url = (
            f"{self.base_url}/api/v1/{self.tenant}/executions/"
            f"{self.namespace}/{quote(flow_id, safe='')}"
        )
        boundary, form_body = _encode_multipart_form(encoded_inputs)
        headers = {**self.headers, "Content-Type": f"multipart/form-data; boundary={boundary}"}
        created = _request_json(
            url,
            method="POST",
            headers=headers,
            body=form_body,
            timeout=self.timeout,
        )
        execution_id = created.get("id")
        if not isinstance(execution_id, str) or not execution_id:
            raise KestraReplayError(f"Kestra did not return an execution ID for flow {flow_id}")
        execution_url = (
            f"{self.base_url}/api/v1/{self.tenant}/executions/{quote(execution_id, safe='')}"
        )
        deadline = time.monotonic() + self.timeout
        latest = created
        while time.monotonic() < deadline:
            latest = _request_json(
                execution_url, method="GET", headers=self.headers, timeout=self.timeout
            )
            state = _execution_state(latest)
            if state in TERMINAL_STATES:
                break
            time.sleep(poll_seconds)
        else:
            raise KestraReplayError(
                f"Execution {execution_id} timed out after {self.timeout:g} seconds"
            )
        final_state = _execution_state(latest)
        if final_state != "SUCCESS":
            raise KestraReplayError(
                f"DEV flow {flow_id} execution {execution_id} finished with state {final_state}; "
                "replay stopped and no comparison row was written for this case."
            )
        return {"execution_id": execution_id, "state": final_state, "payload": latest}


def _summarize_execution(result: dict[str, Any]) -> dict[str, Any]:
    payload = result["payload"]
    outputs = payload.get("outputs", {})
    decision = _find_named_value(outputs, "decision") or _find_named_value(payload, "decision")
    score = _find_named_value(outputs, "complex_customer_profile_score")
    approved_amount = _find_named_value(outputs, "approved_amount")
    return {
        "execution_id": result["execution_id"],
        "state": result["state"],
        "decision": decision,
        "profile_score": score,
        "approved_amount": approved_amount,
    }


def replay_cohort(
    *,
    base_url: str,
    tenant: str,
    namespace: str,
    baseline_flow: str,
    candidate_flow: str,
    cohort_path: Path,
    output_path: Path,
    username: str | None = None,
    password: str | None = None,
    poll_seconds: float = 2.0,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Execute a fixed synthetic cohort through a DEV flow and persist replay results."""
    if namespace != DEV_NAMESPACE:
        raise KestraReplayError(
            f"Replay is restricted to the DEV namespace {DEV_NAMESPACE!r}; refusing {namespace!r}."
        )
    client = KestraClient(base_url, tenant, DEV_NAMESPACE, username, password, timeout)
    rows: list[dict[str, Any]] = []
    with cohort_path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            try:
                application = _validate_application(json.loads(raw))
            except (json.JSONDecodeError, KestraReplayError) as exc:
                raise KestraReplayError(f"Invalid cohort line {line_number}: {exc}") from exc
            baseline = _summarize_execution(
                client.execute(baseline_flow, application, poll_seconds)
            )
            candidate = _summarize_execution(
                client.execute(candidate_flow, application, poll_seconds)
            )
            baseline_decision = baseline["decision"]
            candidate_decision = candidate["decision"]
            rows.append(
                {
                    "applicant_id": application["applicant_id"],
                    "baseline_state": baseline["state"],
                    "candidate_state": candidate["state"],
                    "baseline_decision": baseline_decision,
                    "candidate_decision": candidate_decision,
                    "decision_changed": baseline_decision != candidate_decision,
                    "baseline_profile_score": baseline["profile_score"],
                    "candidate_profile_score": candidate["profile_score"],
                    "profile_score_changed": baseline["profile_score"]
                    != candidate["profile_score"],
                    "baseline_approved_amount": baseline["approved_amount"],
                    "candidate_approved_amount": candidate["approved_amount"],
                    "approved_amount_changed": baseline["approved_amount"]
                    != candidate["approved_amount"],
                    "baseline_execution_id": baseline["execution_id"],
                    "candidate_execution_id": candidate["execution_id"],
                }
            )

    if not rows:
        raise KestraReplayError("The cohort contains no application rows; nothing was replayed.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        list(rows[0])
        if rows
        else [
            "applicant_id",
            "baseline_state",
            "candidate_state",
            "baseline_decision",
            "candidate_decision",
            "decision_changed",
        ]
    )
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    def counts(key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            value = row.get(key)
            label = str(value) if value is not None else "NO_DECISION"
            result[label] = result.get(label, 0) + 1
        return dict(sorted(result.items()))

    summary = {
        "namespace": namespace,
        "baseline_flow": baseline_flow,
        "candidate_flow": candidate_flow,
        "case_count": len(rows),
        "decision_change_count": sum(1 for row in rows if row["decision_changed"]),
        "profile_score_change_count": sum(1 for row in rows if row["profile_score_changed"]),
        "approved_amount_change_count": sum(1 for row in rows if row["approved_amount_changed"]),
        "baseline_decisions": counts("baseline_decision"),
        "candidate_decisions": counts("candidate_decision"),
        "csv_path": str(output_path),
    }
    output_path.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    """Run the DEV-only sample cohort replay from the command line."""
    parser = argparse.ArgumentParser(
        description="Compare a de-identified cohort on DEV baseline and candidate flows"
    )
    parser.add_argument("--base-url", default=os.getenv("KESTRACTL_HOST", "http://localhost:8080"))
    parser.add_argument("--tenant", default=os.getenv("KESTRACTL_TENANT", "main"))
    parser.add_argument(
        "--namespace",
        choices=[DEV_NAMESPACE],
        default=DEV_NAMESPACE,
        help="Fixed DEV namespace; production replay is intentionally unsupported",
    )
    parser.add_argument("--baseline-flow", default="uwflow_dev_baseline_v2_0_0")
    parser.add_argument("--candidate-flow", required=True)
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("modules/history/examples/cohorts/dev_cohort.sample.jsonl"),
    )
    parser.add_argument("--output", type=Path, default=Path("var/reports/dev-replay.csv"))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()
    try:
        summary = replay_cohort(
            base_url=args.base_url,
            tenant=args.tenant,
            namespace=args.namespace,
            baseline_flow=args.baseline_flow,
            candidate_flow=args.candidate_flow,
            cohort_path=args.cohort,
            output_path=args.output,
            username=os.getenv("KESTRACTL_USERNAME"),
            password=os.getenv("KESTRACTL_PASSWORD"),
            poll_seconds=args.poll_seconds,
            timeout=args.timeout_seconds,
        )
    except (KestraReplayError, OSError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
