"""Synchronize only the PostgreSQL owner-role password with .env.history.

The command requires the expected running container and named data volume. It
uses the official PostgreSQL container's local administrative socket, changes
no schemas or application rows, and never prints the password.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

_CONTAINER = "uwflow-history-db"
_EXPECTED_VOLUME = "uwflow_history_pgdata"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase PostgreSQL identifier")
    return f'"{value}"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_reconciliation_sql(owner: str, password: str) -> str:
    owner_sql = _identifier(owner, "Owner role")
    if not password:
        raise ValueError("UWFLOW_HISTORY_OWNER_PASSWORD is missing from .env.history")
    return (
        "DO $uwflow$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper) "
        "THEN RAISE EXCEPTION 'connected local role is not a PostgreSQL superuser'; END IF; "
        "END $uwflow$;\n"
        f"ALTER ROLE {owner_sql} WITH LOGIN PASSWORD {_literal(password)};\n"
        "SELECT current_user, current_database();\n"
    )


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(detail)
    return result.stdout.strip()


def main() -> int:
    """Reconcile the local History database owner password without replacing its data volume."""
    try:
        owner = os.getenv("UWFLOW_HISTORY_OWNER_USER", "uwflow_history_owner")
        password = os.getenv("UWFLOW_HISTORY_OWNER_PASSWORD", "")
        database = os.getenv("UWFLOW_HISTORY_DB", "uwflow_history")
        _identifier(database, "Database")
        sql = _build_reconciliation_sql(owner, password)

        state = _run(
            [
                "docker",
                "inspect",
                "--format",
                '{{.State.Status}}|{{.State.Health.Status}}|{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}',
                _CONTAINER,
            ]
        )
        parts = state.split("|", 2)
        if len(parts) != 3:
            raise RuntimeError("Could not inspect the PostgreSQL container state and volume")
        container_state, health_state, volume = parts
        if container_state != "running" or health_state != "healthy":
            raise RuntimeError(
                f"PostgreSQL container must be running and healthy (state={container_state}, "
                f"health={health_state})"
            )
        if volume != _EXPECTED_VOLUME:
            raise RuntimeError(
                f"Refusing credential repair: {_CONTAINER} uses volume {volume!r}, "
                f"not the expected {_EXPECTED_VOLUME!r}"
            )

        # The official postgres image configures local socket access for its
        # bootstrap administrator. We deliberately avoid TCP and the broken DSN.
        output = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "--user",
                "postgres",
                _CONTAINER,
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "--no-password",
                "--username",
                owner,
                "--dbname",
                database,
            ],
            input=sql,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if output.returncode:
            detail = output.stderr.strip() or output.stdout.strip() or "psql failed"
            raise RuntimeError(
                "Could not update the PostgreSQL owner password through the local container "
                f"administrative socket. No data rows were modified. Detail: {detail}"
            )
        print("Synchronized the PostgreSQL owner-role password with .env.history.")
        print(
            "Only the database login password was changed; schemas, datasets and volume were untouched."
        )
        print("The workflow will now verify the TCP admin DSN before continuing.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: credential reconciliation was not completed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
