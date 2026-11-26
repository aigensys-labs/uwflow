"""Rebuild local history credential files for an existing UWflow database.

The recovery flow intentionally rotates database login passwords instead of
trying to recover plaintext passwords from PostgreSQL. It preserves the
existing named volume and all database contents. The owner password is
synchronized later through the container's local administrative socket;
reader and writer roles are synchronized by the normal idempotent database
initialization step.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

CONTAINER = "uwflow-history-db"
VOLUME = "uwflow_history_pgdata"
DATABASE = "uwflow_history"
OWNER = "uwflow_history_owner"
READER = "uwflow_history_reader"
WRITER = "uwflow_history_writer"
DEFAULT_PORT = "55432"


def _docker_json(command: list[str]) -> dict | list | None:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        normalized = detail.lower()
        missing_object = (
            "no such object" in normalized
            or "no such volume" in normalized
            or "not found" in normalized
        )
        if missing_object:
            return None
        raise RuntimeError(
            f"Docker inspection failed for {command[-1]!r}: {detail or 'unknown error'}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker returned invalid inspection data.") from exc


def _existing_database_state() -> tuple[bool, str]:
    """Return whether the named DB container/volume exists and its host port."""
    container_result = _docker_json(["docker", "inspect", CONTAINER])
    volume_result = _docker_json(["docker", "volume", "inspect", VOLUME])
    container_exists = isinstance(container_result, list) and bool(container_result)
    volume_exists = isinstance(volume_result, list) and bool(volume_result)

    if not container_exists and not volume_exists:
        return False, DEFAULT_PORT

    if container_exists:
        container = container_result[0]
        mounts = container.get("Mounts") or []
        matching = [
            mount
            for mount in mounts
            if mount.get("Destination") == "/var/lib/postgresql/data"
            and mount.get("Type") == "volume"
        ]
        if len(matching) != 1 or matching[0].get("Name") != VOLUME:
            attached = matching[0].get("Name") if matching else "no named history volume"
            raise RuntimeError(
                f"Container {CONTAINER!r} does not use the expected {VOLUME!r} volume "
                f"(found {attached!r}). No credentials or database state were changed."
            )

        env_values = {}
        for entry in (container.get("Config") or {}).get("Env") or []:
            key, separator, value = entry.partition("=")
            if separator:
                env_values[key] = value
        configured_user = env_values.get("POSTGRES_USER")
        configured_database = env_values.get("POSTGRES_DB")
        if configured_user != OWNER or configured_database != DATABASE:
            raise RuntimeError(
                f"Existing container uses database identity {configured_user!r}/"
                f"{configured_database!r}; expected {OWNER!r}/{DATABASE!r}. "
                "Restore the matching credential configuration before continuing."
            )

        ports = ((container.get("HostConfig") or {}).get("PortBindings") or {}).get(
            "5432/tcp"
        ) or []
        if not ports:
            ports = ((container.get("NetworkSettings") or {}).get("Ports") or {}).get(
                "5432/tcp"
            ) or []
        if ports:
            host_ip = str(ports[0].get("HostIp") or "")
            if host_ip != "127.0.0.1":
                raise RuntimeError(
                    f"The existing PostgreSQL port is bound to {host_ip!r}, not loopback. "
                    "Review the port exposure before credential recovery."
                )
            host_port = str(ports[0].get("HostPort") or DEFAULT_PORT)
        else:
            raise RuntimeError(
                "The existing PostgreSQL container has no published host port mapping. "
                "Restore its matching connection configuration before continuing."
            )
        if not host_port.isdigit() or not 1 <= int(host_port) <= 65535:
            raise RuntimeError(
                "The existing PostgreSQL container has an invalid host port mapping."
            )
        return True, host_port

    # A volume without a container is an existing database installation. The
    # repository's standard host mapping is used when Step 06 recreates the
    # container against this same named volume.
    return True, DEFAULT_PORT


def _double_quoted(value: str) -> str:
    """Quote a path for both Bash sourcing and Docker Compose env-file parsing."""
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    )
    return f'"{escaped}"'


def _render_files(root: Path, port: str) -> tuple[str, str]:
    owner_password = secrets.token_hex(24)
    read_password = secrets.token_hex(24)
    write_password = secrets.token_hex(24)
    history_root = str((root / "var" / "data" / "history").resolve())

    admin_dsn = f"postgresql+psycopg://{OWNER}:{owner_password}@127.0.0.1:{port}/{DATABASE}"
    read_dsn = f"postgresql+psycopg://{READER}:{read_password}@127.0.0.1:{port}/{DATABASE}"
    write_dsn = f"postgresql+psycopg://{WRITER}:{write_password}@127.0.0.1:{port}/{DATABASE}"
    kestra_read_dsn = (
        f"postgresql+psycopg://{READER}:{read_password}@uwflow-history-db:5432/{DATABASE}"
    )

    history = "\n".join(
        [
            "# Local-only historical store credentials. Never commit this file.",
            "UWFLOW_HISTORY_CONNECTOR=postgres",
            f"UWFLOW_HISTORY_DB={DATABASE}",
            f"UWFLOW_HISTORY_PORT={port}",
            f"UWFLOW_HISTORY_OWNER_USER={OWNER}",
            f"UWFLOW_HISTORY_OWNER_PASSWORD={owner_password}",
            f"UWFLOW_HISTORY_READ_USER={READER}",
            f"UWFLOW_HISTORY_READ_PASSWORD={read_password}",
            f"UWFLOW_HISTORY_WRITE_USER={WRITER}",
            f"UWFLOW_HISTORY_WRITE_PASSWORD={write_password}",
            f"UWFLOW_HISTORY_ADMIN_DSN={admin_dsn}",
            f"UWFLOW_HISTORY_DSN={read_dsn}",
            f"UWFLOW_HISTORY_WRITE_DSN={write_dsn}",
            f"UWFLOW_HISTORY_ROOT={_double_quoted(history_root)}",
            f"UWFLOW_HISTORY_WRITE_ROOT={_double_quoted(history_root)}",
            f"UWFLOW_HISTORY_DOCKER_ROOT={_double_quoted(history_root)}",
            "UWFLOW_HISTORY_BATCH_SIZE=2000",
            "UWFLOW_HISTORY_READ_ONLY=true",
            "",
        ]
    )

    def encoded(value: str) -> str:
        return base64.b64encode(value.encode("utf-8")).decode("ascii")

    kestra = "\n".join(
        [
            "# Kestra OSS secret variables are Base64-encoded.",
            f"SECRET_UWFLOW_HISTORY_CONNECTOR={encoded('postgres')}",
            f"SECRET_UWFLOW_HISTORY_DSN={encoded(kestra_read_dsn)}",
            f"SECRET_UWFLOW_HISTORY_ROOT={encoded('/data/uwflow/history')}",
            "",
        ]
    )
    return history, kestra


def _write_pair(root: Path, history_content: str, kestra_content: str) -> None:
    history_path = root / ".env.history"
    kestra_path = root / ".env.history.kestra"
    if history_path.exists() or kestra_path.exists():
        raise RuntimeError(
            "A history credential file appeared during recovery. No existing file was overwritten."
        )

    created: list[Path] = []
    try:
        for path, content in (
            (history_path, history_content),
            (kestra_path, kestra_content),
        ):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _confirm_recovery() -> bool:
    print(
        "An existing UWflow history database was found, but both local credential files are missing.\n"
        "The original plaintext passwords cannot be recovered from PostgreSQL.\n\n"
        "Continuing will create new owner, reader and writer passwords. The workflow will:\n"
        "  • update only the owner login password through PostgreSQL's local admin socket;\n"
        "  • update/create the reader and writer roles during database initialization;\n"
        "  • regenerate Kestra's read-only secret file and reload the local Kestra container.\n\n"
        f"The existing {VOLUME} volume and all database contents will be preserved.\n"
        "No database, schema or volume will be deleted.\n"
    )
    try:
        answer = input("Reconcile the history credentials and continue? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    return answer in {"y", "yes"}


def recover(root: Path, *, approved: bool | None = None) -> bool:
    """Create replacement credentials after confirming the existing DB identity."""
    root = root.resolve()
    history_path = root / ".env.history"
    kestra_path = root / ".env.history.kestra"
    if history_path.exists() or kestra_path.exists():
        raise RuntimeError("Credential recovery only runs when both paired files are absent.")

    exists, port = _existing_database_state()
    if not exists:
        return False
    if approved is None:
        approved = _confirm_recovery()
    if not approved:
        print("No credentials or database state were changed.", file=sys.stderr)
        raise PermissionError("Credential reconciliation was not approved.")

    still_exists, current_port = _existing_database_state()
    if not still_exists or current_port != port:
        raise RuntimeError(
            "The existing database container/volume changed during confirmation. "
            "No credential files were written. Re-run Step 04 and inspect the database state."
        )

    history_content, kestra_content = _render_files(root, port)
    state = root / "var/operator-state"
    owner_marker = state / "history-owner-password-reconcile-approved"
    kestra_marker = state / "history-kestra-secrets-reload"
    files_written: list[Path] = []
    try:
        _write_pair(root, history_content, kestra_content)
        files_written.extend([root / ".env.history", root / ".env.history.kestra"])
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        for marker, value in (
            (owner_marker, "approved\n"),
            (kestra_marker, "required\n"),
        ):
            marker.write_text(value, encoding="utf-8")
            os.chmod(marker, 0o600)
    except Exception:
        for path in files_written:
            path.unlink(missing_ok=True)
        owner_marker.unlink(missing_ok=True)
        kestra_marker.unlink(missing_ok=True)
        raise

    print("Paired history credential files were recreated with replacement credentials.")
    print(
        "Step 06 will synchronize the owner login; Step 10 will synchronize reader and writer roles."
    )
    print("Kestra will be reloaded with the new read-only secret during Step 07.")
    print(f"The existing database volume {VOLUME} was not modified or recreated.")
    return True


def main(argv: list[str] | None = None) -> int:
    """Recover the local History credential pair while preserving database and workflow state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        recovered = recover(args.root)
        if not recovered:
            print(
                "No existing history container or volume was found; use the fresh-install credential generator."
            )
            return 3
        return 0
    except PermissionError:
        return 1
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: history credential recovery stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
