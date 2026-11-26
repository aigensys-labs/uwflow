"""Tests for safe History database credential handling and configuration."""

from __future__ import annotations

import subprocess

from sqlalchemy.exc import OperationalError

from tools.history.database import check_connection, reconcile_owner_password


class _Connection:
    def __init__(self, result=("uwflow_history_owner", "uwflow_history"), error=None):
        self.result = result
        self.error = error

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *args):
        return False

    def exec_driver_sql(self, statement):
        class _Result:
            def one(self_nonlocal):
                return self.result

        return _Result()


class _Engine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def _admin_env(monkeypatch):
    monkeypatch.setenv(
        "UWFLOW_HISTORY_ADMIN_DSN",
        "postgresql+psycopg://uwflow_history_owner:abc123@127.0.0.1:55432/uwflow_history",
    )
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_USER", "uwflow_history_owner")
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_PASSWORD", "abc123")
    monkeypatch.setenv("UWFLOW_HISTORY_DB", "uwflow_history")


def test_admin_connection_preflight_accepts_matching_credentials(monkeypatch, capsys):
    _admin_env(monkeypatch)
    engine = _Engine(_Connection())
    monkeypatch.setattr(check_connection, "create_engine", lambda *args, **kwargs: engine)

    assert check_connection.main() == 0
    assert engine.disposed
    assert "credentials verified" in capsys.readouterr().out


def test_admin_connection_classifies_password_mismatch_for_guarded_repair(monkeypatch, capsys):
    _admin_env(monkeypatch)
    error = OperationalError(
        None, None, Exception("FATAL: password authentication failed for user")
    )
    engine = _Engine(_Connection(error=error))
    monkeypatch.setattr(check_connection, "create_engine", lambda *args, **kwargs: engine)

    assert check_connection.main() == 3
    assert engine.disposed
    captured = capsys.readouterr()
    assert "HISTORY_ADMIN_AUTH_MISMATCH" in captured.err
    assert "No data has been changed" in captured.err
    assert "abc123" not in captured.out + captured.err


def test_admin_connection_rejects_internal_dsn_password_mismatch_without_connecting(
    monkeypatch, capsys
):
    _admin_env(monkeypatch)
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_PASSWORD", "different")
    monkeypatch.setattr(
        check_connection,
        "create_engine",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not connect")),
    )

    assert check_connection.main() == 2
    assert "internally inconsistent" in capsys.readouterr().err


def test_reconciliation_sql_only_alters_the_owner_login_password():
    sql = reconcile_owner_password._build_reconciliation_sql(
        "uwflow_history_owner", "new-secret'value"
    )
    assert 'ALTER ROLE "uwflow_history_owner" WITH LOGIN PASSWORD' in sql
    assert "'new-secret''value'" in sql
    assert "DROP" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()
    assert "DELETE" not in sql.upper()


def test_reconciliation_requires_expected_container_volume(monkeypatch, capsys):
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_USER", "uwflow_history_owner")
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_PASSWORD", "abc123")
    monkeypatch.setenv("UWFLOW_HISTORY_DB", "uwflow_history")
    monkeypatch.setattr(
        reconcile_owner_password, "_run", lambda command: "running|healthy|wrong_volume"
    )
    monkeypatch.setattr(
        reconcile_owner_password.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("psql must not run")),
    )

    assert reconcile_owner_password.main() == 2
    assert "not the expected 'uwflow_history_pgdata'" in capsys.readouterr().err


def test_reconciliation_changes_only_owner_password_and_never_prints_it(monkeypatch, capsys):
    secret = "safe-secret-123"
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_USER", "uwflow_history_owner")
    monkeypatch.setenv("UWFLOW_HISTORY_OWNER_PASSWORD", secret)
    monkeypatch.setenv("UWFLOW_HISTORY_DB", "uwflow_history")
    monkeypatch.setattr(
        reconcile_owner_password,
        "_run",
        lambda command: "running|healthy|uwflow_history_pgdata",
    )
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs["input"]
        return subprocess.CompletedProcess(command, 0, stdout="ALTER ROLE\n", stderr="")

    monkeypatch.setattr(reconcile_owner_password.subprocess, "run", fake_run)
    assert reconcile_owner_password.main() == 0
    assert 'ALTER ROLE "uwflow_history_owner"' in seen["input"]
    assert secret in seen["input"]
    assert "--user" in seen["command"] and "postgres" in seen["command"]
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "schemas, datasets and volume were untouched" in captured.out


def test_credential_generator_refuses_to_mint_passwords_for_existing_database(tmp_path):
    from pathlib import Path
    import os
    import shutil

    source_root = Path(__file__).resolve().parents[2]
    test_root = tmp_path / "UWflow checkout with spaces"
    generator = test_root / "tools/guides/workflow/lib/create-history-env.sh"
    generator.parent.mkdir(parents=True)
    shutil.copy2(source_root / "tools/guides/workflow/lib/create-history-env.sh", generator)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(generator)], capture_output=True, text=True, env=env, check=False
    )

    assert result.returncode == 1
    assert "Refusing to generate new passwords" in result.stderr
    assert not (test_root / ".env.history").exists()
    assert not (test_root / ".env.history.kestra").exists()
