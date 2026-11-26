"""Tests for the DEV-only sample cohort replay workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.history.replay import dev_cohort as replay

ROOT = Path(__file__).resolve().parents[2]


def _sample_application() -> dict:
    line = next(
        line
        for line in (ROOT / "modules/history/examples/cohorts/dev_cohort.sample.jsonl")
        .read_text()
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return json.loads(line)


def test_sample_cohort_has_valid_complete_flow_inputs() -> None:
    application = replay._validate_application(_sample_application())
    assert application["applicant_id"] == "DEV-SYNTH-001"
    assert application["data_sharing_consent"] is True


def test_cohort_requires_all_string_and_numeric_types() -> None:
    application = _sample_application()
    application["applicant_name"] = "  "
    with pytest.raises(replay.KestraReplayError, match="applicant_name"):
        replay._validate_application(application)

    application = _sample_application()
    application["monthly_income"] = True
    with pytest.raises(replay.KestraReplayError, match="monthly_income must be a finite number"):
        replay._validate_application(application)


def test_execution_inputs_are_encoded_as_multipart_form_data() -> None:
    boundary, body = replay._encode_multipart_form(
        {
            "applicant_id": "DEV-001",
            "applicant_name": "Test Applicant",
            "data_sharing_consent": "true",
        }
    )
    assert boundary.startswith("uwflow-")
    payload = body.decode("utf-8")
    assert f"--{boundary}" in payload
    assert 'name="applicant_id"' in payload
    assert "Test Applicant" in payload
    assert payload.endswith(f"--{boundary}--\r\n")


def test_execution_summary_reads_flow_level_outputs() -> None:
    result = replay._summarize_execution(
        {
            "execution_id": "exec-1",
            "state": "SUCCESS",
            "payload": {
                "outputs": {
                    "decision": {"value": "APPROVED"},
                    "complex_customer_profile_score": {"value": 837},
                    "underwriting_result": {
                        "value": {
                            "approved_amount": 8194.2,
                        }
                    },
                },
            },
        }
    )
    assert result == {
        "execution_id": "exec-1",
        "state": "SUCCESS",
        "decision": "APPROVED",
        "profile_score": 837,
        "approved_amount": 8194.2,
    }


def test_non_success_execution_stops_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(
        [
            {"id": "exec-failed", "state": {"current": "CREATED"}},
            {"id": "exec-failed", "state": {"current": "FAILED"}},
        ]
    )

    def fake_request_json(*args, **kwargs):
        return next(calls)

    monkeypatch.setattr(replay, "_request_json", fake_request_json)
    monkeypatch.setattr(replay.time, "sleep", lambda _: None)
    client = replay.KestraClient(
        "http://localhost:8080", "main", "com.ai.credit.dev", None, None, 2.0
    )

    with pytest.raises(replay.KestraReplayError, match="finished with state FAILED"):
        client.execute("uwflow_dev_candidate_test", _sample_application(), poll_seconds=0)


def test_replay_refuses_any_namespace_other_than_dev(tmp_path: Path) -> None:
    with pytest.raises(replay.KestraReplayError, match="restricted to the DEV namespace"):
        replay.replay_cohort(
            base_url="http://localhost:8080",
            tenant="main",
            namespace="com.ai.credit.production",
            baseline_flow="baseline",
            candidate_flow="candidate",
            cohort_path=tmp_path / "unused.jsonl",
            output_path=tmp_path / "unused.csv",
        )


def test_cohort_rejects_non_finite_numeric_inputs() -> None:
    application = _sample_application()
    application["monthly_income"] = float("nan")
    with pytest.raises(replay.KestraReplayError, match="finite number"):
        replay._validate_application(application)
