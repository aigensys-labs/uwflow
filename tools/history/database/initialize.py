"""Initialize PostgreSQL history schemas and least-privilege access roles.

Run only with the dedicated database-owner/admin DSN. This is an explicit,
manual bootstrap command and is never invoked by Kestra replay tasks.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys


def _history_package_root() -> Path:
    """Return the import root for source and immutable Namespace Files layouts.

    Source checkouts keep ``uwflow_history`` under ``modules/history/python``. The history-tools
    bundle deliberately maps it to ``scripts/uwflow_history`` to preserve the
    existing Kestra artifact path contract.
    """
    for candidate in Path(__file__).resolve().parents:
        source_package = candidate / "modules" / "history" / "python" / "uwflow_history"
        if (source_package / "__init__.py").is_file():
            return source_package.parent
        bundled_scripts = candidate / "scripts"
        if (bundled_scripts / "uwflow_history" / "__init__.py").is_file():
            return bundled_scripts
    raise RuntimeError(
        "Cannot locate uwflow_history in the source tree or scripts/ Namespace Files layout"
    )


ROOT = _history_package_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uwflow_history.config import HistoryConfig, HistoryConfigurationError, require_write_approval  # noqa: E402
from uwflow_history.connectors.postgres import PostgresHistoryStore  # noqa: E402

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise HistoryConfigurationError(
            f"{label} must be a lowercase PostgreSQL identifier (a-z, 0-9, underscore)"
        )
    return f'"{value}"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ensure_role(connection, name: str, password: str, *, can_login: bool = True) -> None:
    quoted = _identifier(name, "Database role")
    if not password:
        raise HistoryConfigurationError(f"Password for database role {name!r} is required")
    exists = connection.exec_driver_sql(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)
    ).scalar_one_or_none()
    login = "LOGIN" if can_login else "NOLOGIN"
    least_privilege = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    if exists:
        connection.exec_driver_sql(
            f"ALTER ROLE {quoted} {login} {least_privilege} PASSWORD {_literal(password)}"
        )
    else:
        connection.exec_driver_sql(
            f"CREATE ROLE {quoted} {login} {least_privilege} PASSWORD {_literal(password)}"
        )


def initialize_roles_and_grants(store: PostgresHistoryStore) -> None:
    """Create tables as owner and grant narrowly scoped reader/writer access."""
    schemas = tuple(store.schemas.values())
    quoted_schemas = [_identifier(schema, "History schema") for schema in schemas]
    reader = os.getenv("UWFLOW_HISTORY_READ_USER", "uwflow_history_reader")
    reader_password = os.getenv("UWFLOW_HISTORY_READ_PASSWORD", "")
    writer = os.getenv("UWFLOW_HISTORY_WRITE_USER", "uwflow_history_writer")
    writer_password = os.getenv("UWFLOW_HISTORY_WRITE_PASSWORD", "")
    reader_q = _identifier(reader, "Reader role")
    writer_q = _identifier(writer, "Writer role")

    with store.engine.begin() as connection:
        owner = str(connection.exec_driver_sql("SELECT current_user").scalar_one())
        owner_q = _identifier(owner, "Database owner role")
        database = str(connection.exec_driver_sql("SELECT current_database()").scalar_one())
        database_q = _identifier(database, "Database name")

        _ensure_role(connection, reader, reader_password)
        _ensure_role(connection, writer, writer_password)

        connection.exec_driver_sql(
            f"GRANT CONNECT ON DATABASE {database_q} TO {reader_q}, {writer_q}"
        )
        for schema_q in quoted_schemas:
            connection.exec_driver_sql(f"REVOKE ALL ON SCHEMA {schema_q} FROM PUBLIC")
            connection.exec_driver_sql(
                f"GRANT USAGE ON SCHEMA {schema_q} TO {reader_q}, {writer_q}"
            )
            connection.exec_driver_sql(
                f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema_q} TO {reader_q}"
            )
            connection.exec_driver_sql(
                f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA {schema_q} TO {writer_q}"
            )
            connection.exec_driver_sql(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_q} IN SCHEMA {schema_q} "
                f"GRANT SELECT ON TABLES TO {reader_q}"
            )
            connection.exec_driver_sql(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_q} IN SCHEMA {schema_q} "
                f"GRANT SELECT, INSERT ON TABLES TO {writer_q}"
            )
        # Neither application role receives schema ownership, DDL, UPDATE or DELETE.
        connection.exec_driver_sql(f"REVOKE CREATE ON SCHEMA public FROM {reader_q}, {writer_q}")


def main() -> int:
    """Initialize the local History database schemas and role permissions."""
    parser = argparse.ArgumentParser(
        description="Initialize UWflow historical PostgreSQL schemas and least-privilege roles"
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="Acknowledge that this command creates schemas/tables and configures roles",
    )
    args = parser.parse_args()
    store = None
    try:
        require_write_approval(cli_flag=args.allow_write)
        config = HistoryConfig.from_env(for_admin=True)
        if config.connector != "postgres":
            raise HistoryConfigurationError(
                "init_history_db.py only initializes the PostgreSQL connector"
            )
        store = PostgresHistoryStore(
            config.dsn,
            batch_size=config.batch_size,
            schemas={
                "history": config.schema_history,
                "sources": config.schema_sources,
                "outcomes": config.schema_outcomes,
                "simulation": config.schema_simulation,
            },
            read_only=False,
        )
        store.initialize()
        initialize_roles_and_grants(store)
    except (HistoryConfigurationError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    finally:
        if store is not None:
            store.close()
    print("Initialized UWflow historical-data schemas and tables.")
    print("Configured read-only and insert-only application roles.")
    print("No application data was inserted or modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
