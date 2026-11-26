"""Check the host admin DSN against the running historical PostgreSQL instance.

Exit status 3 is reserved for password authentication failures so the operator
workflow can offer a narrowly scoped credential reconciliation.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError


def main() -> int:
    """Check connectivity and permissions for the configured History database roles."""
    dsn = os.getenv("UWFLOW_HISTORY_ADMIN_DSN", "")
    owner = os.getenv("UWFLOW_HISTORY_OWNER_USER", "uwflow_history_owner")
    expected_password = os.getenv("UWFLOW_HISTORY_OWNER_PASSWORD", "")
    database = os.getenv("UWFLOW_HISTORY_DB", "uwflow_history")
    if not dsn or not expected_password:
        print("ERROR: admin DSN or owner password is missing from .env.history.", file=sys.stderr)
        return 2

    try:
        url = make_url(dsn)
    except Exception:
        print("ERROR: UWFLOW_HISTORY_ADMIN_DSN is not a valid SQLAlchemy URL.", file=sys.stderr)
        return 2

    if url.username != owner or url.password != expected_password or url.database != database:
        print(
            "ERROR: .env.history is internally inconsistent: the admin DSN does not "
            "match its owner username/password/database settings. No database changes made.",
            file=sys.stderr,
        )
        return 2

    engine = None
    try:
        engine = create_engine(dsn, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        with engine.connect() as connection:
            current_user, current_database = connection.exec_driver_sql(
                "SELECT current_user, current_database()"
            ).one()
        if current_user != owner or current_database != database:
            print(
                "ERROR: the configured admin DSN connected to an unexpected database role "
                "or database. No database changes made.",
                file=sys.stderr,
            )
            return 2
    except OperationalError as exc:
        detail = str(getattr(exc, "orig", exc)).lower()
        if "password authentication failed" in detail:
            print(
                "HISTORY_ADMIN_AUTH_MISMATCH: PostgreSQL is healthy, but the owner password "
                "in .env.history does not match the password stored in the existing database.\n"
                "No data has been changed. The workflow can offer to synchronize the owner "
                "role password to the protected .env.history value.",
                file=sys.stderr,
            )
            return 3
        print(
            "ERROR: could not verify the historical PostgreSQL connection. "
            f"PostgreSQL reported: {getattr(exc, 'orig', exc)}",
            file=sys.stderr,
        )
        return 2
    except SQLAlchemyError as exc:
        print(f"ERROR: could not verify historical PostgreSQL: {exc}", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()

    print(f"Historical PostgreSQL credentials verified (database={database}, role={owner}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
