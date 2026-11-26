"""Tests for safe recovery of local History database credentials and state."""

from __future__ import annotations

import base64
from pathlib import Path
import subprocess

import pytest

from tools.history.database import recover_credentials


def _mock_existing_database(
    monkeypatch, *, port: str = "55432", expected_volume: str = "uwflow_history_pgdata"
) -> None:
    container = {
        "Mounts": [
            {
                "Type": "volume",
                "Name": expected_volume,
                "Destination": "/var/lib/postgresql/data",
            }
        ],
        "Config": {
            "Env": [
                "POSTGRES_USER=uwflow_history_owner",
                "POSTGRES_DB=uwflow_history",
            ]
        },
        "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}},
    }
    volume = {"Name": "uwflow_history_pgdata"}

    def fake_docker_json(command):
        if command[:3] == ["docker", "inspect", "uwflow-history-db"]:
            return [container]
        if command[:4] == ["docker", "volume", "inspect", "uwflow_history_pgdata"]:
            return [volume]
        raise AssertionError(command)

    monkeypatch.setattr(recover_credentials, "_docker_json", fake_docker_json)


def _parse_assignments(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip('"')
    return result


def test_recovery_rebuilds_pair_with_new_credentials_and_preserves_state(
    tmp_path, monkeypatch, capsys
):
    _mock_existing_database(monkeypatch, port="55433")

    assert recover_credentials.recover(tmp_path, approved=True)

    host_env = tmp_path / ".env.history"
    kestra_env = tmp_path / ".env.history.kestra"
    assert host_env.is_file() and kestra_env.is_file()
    assert host_env.stat().st_mode & 0o777 == 0o600
    assert kestra_env.stat().st_mode & 0o777 == 0o600

    host = _parse_assignments(host_env)
    kestra = _parse_assignments(kestra_env)
    assert host["UWFLOW_HISTORY_PORT"] == "55433"
    assert host["UWFLOW_HISTORY_OWNER_USER"] == "uwflow_history_owner"
    assert host["UWFLOW_HISTORY_READ_USER"] == "uwflow_history_reader"
    assert host["UWFLOW_HISTORY_WRITE_USER"] == "uwflow_history_writer"
    assert host["UWFLOW_HISTORY_OWNER_PASSWORD"]
    assert host["UWFLOW_HISTORY_READ_PASSWORD"]
    assert host["UWFLOW_HISTORY_WRITE_PASSWORD"]
    assert host["UWFLOW_HISTORY_OWNER_PASSWORD"] != host["UWFLOW_HISTORY_READ_PASSWORD"]
    assert host["UWFLOW_HISTORY_READ_PASSWORD"] != host["UWFLOW_HISTORY_WRITE_PASSWORD"]
    assert host["UWFLOW_HISTORY_ADMIN_DSN"].endswith("@127.0.0.1:55433/uwflow_history")
    assert host["UWFLOW_HISTORY_DSN"].endswith("@127.0.0.1:55433/uwflow_history")
    assert host["UWFLOW_HISTORY_WRITE_DSN"].endswith("@127.0.0.1:55433/uwflow_history")

    reader_dsn = base64.b64decode(kestra["SECRET_UWFLOW_HISTORY_DSN"]).decode("utf-8")
    assert host["UWFLOW_HISTORY_READ_PASSWORD"] in reader_dsn
    assert "@uwflow-history-db:5432/uwflow_history" in reader_dsn
    assert base64.b64decode(kestra["SECRET_UWFLOW_HISTORY_CONNECTOR"]) == b"postgres"
    assert base64.b64decode(kestra["SECRET_UWFLOW_HISTORY_ROOT"]) == b"/data/uwflow/history"

    assert (tmp_path / "var/operator-state/history-owner-password-reconcile-approved").is_file()
    assert (tmp_path / "var/operator-state/history-kestra-secrets-reload").is_file()
    output = capsys.readouterr().out
    assert "volume uwflow_history_pgdata was not modified or recreated" in output
    for secret in (
        host["UWFLOW_HISTORY_OWNER_PASSWORD"],
        host["UWFLOW_HISTORY_READ_PASSWORD"],
        host["UWFLOW_HISTORY_WRITE_PASSWORD"],
    ):
        assert secret not in output


def test_recovery_decline_writes_nothing(tmp_path, monkeypatch, capsys):
    _mock_existing_database(monkeypatch)

    with pytest.raises(PermissionError):
        recover_credentials.recover(tmp_path, approved=False)

    assert not (tmp_path / ".env.history").exists()
    assert not (tmp_path / ".env.history.kestra").exists()
    assert not (tmp_path / "var/operator-state").exists()
    assert "No credentials or database state were changed" in capsys.readouterr().err


def test_recovery_refuses_unexpected_postgres_volume(tmp_path, monkeypatch):
    _mock_existing_database(monkeypatch, expected_volume="some_other_volume")

    with pytest.raises(RuntimeError, match="does not use the expected"):
        recover_credentials.recover(tmp_path, approved=True)

    assert not (tmp_path / ".env.history").exists()
    assert not (tmp_path / ".env.history.kestra").exists()


def test_recovery_does_not_overwrite_a_partial_pair(tmp_path, monkeypatch):
    _mock_existing_database(monkeypatch)
    (tmp_path / ".env.history").write_text("existing=true\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="only runs when both paired files are absent"):
        recover_credentials.recover(tmp_path, approved=True)

    assert (tmp_path / ".env.history").read_text(encoding="utf-8") == "existing=true\n"
    assert not (tmp_path / ".env.history.kestra").exists()


def test_recovery_returns_fresh_path_when_no_database_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(recover_credentials, "_docker_json", lambda command: None)

    assert recover_credentials.recover(tmp_path, approved=True) is False
    assert not (tmp_path / ".env.history").exists()
    assert not (tmp_path / ".env.history.kestra").exists()


def test_docker_not_found_objects_select_fresh_setup(monkeypatch):
    responses = [
        subprocess.CompletedProcess(
            ["docker", "inspect", "uwflow-history-db"],
            1,
            stdout="",
            stderr="Error: No such object: uwflow-history-db",
        ),
        subprocess.CompletedProcess(
            ["docker", "volume", "inspect", "uwflow_history_pgdata"],
            1,
            stdout="",
            stderr="Error response from daemon: no such volume",
        ),
    ]
    monkeypatch.setattr(
        recover_credentials.subprocess, "run", lambda *args, **kwargs: responses.pop(0)
    )

    assert recover_credentials._existing_database_state() == (False, "55432")


def test_docker_inspection_permission_error_is_not_treated_as_fresh_setup(monkeypatch):
    monkeypatch.setattr(
        recover_credentials.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="permission denied while connecting to Docker"
        ),
    )

    with pytest.raises(RuntimeError, match="Docker inspection failed"):
        recover_credentials._existing_database_state()


def test_recovery_refuses_non_loopback_database_port_binding(tmp_path, monkeypatch):
    _mock_existing_database(monkeypatch)
    original = recover_credentials._docker_json

    def exposed_port(command):
        result = original(command)
        if command[:3] == ["docker", "inspect", "uwflow-history-db"]:
            result[0]["HostConfig"]["PortBindings"]["5432/tcp"][0]["HostIp"] = "0.0.0.0"
        return result

    monkeypatch.setattr(recover_credentials, "_docker_json", exposed_port)

    with pytest.raises(RuntimeError, match="not loopback"):
        recover_credentials.recover(tmp_path, approved=True)

    assert not (tmp_path / ".env.history").exists()
    assert not (tmp_path / ".env.history.kestra").exists()
