"""Environment-based configuration for swappable historical-data connectors."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


class HistoryConfigurationError(RuntimeError):
    """Raised when connector environment settings are incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """Validated configuration for the selected historical-data backend and access mode."""

    connector: str
    dsn: str | None
    root: Path | None
    batch_size: int
    schema_history: str
    schema_sources: str
    schema_outcomes: str
    schema_simulation: str

    @classmethod
    def from_env(cls, *, for_write: bool = False, for_admin: bool = False) -> "HistoryConfig":
        """Load and validate History configuration from environment variables."""
        connector = os.getenv("UWFLOW_HISTORY_CONNECTOR", "postgres").strip().lower()
        if connector not in {"postgres", "parquet"}:
            raise HistoryConfigurationError(
                "UWFLOW_HISTORY_CONNECTOR must be 'postgres' or 'parquet'"
            )
        batch_raw = os.getenv("UWFLOW_HISTORY_BATCH_SIZE", "2000")
        try:
            batch_size = int(batch_raw)
        except ValueError as exc:
            raise HistoryConfigurationError("UWFLOW_HISTORY_BATCH_SIZE must be an integer") from exc
        if not 1 <= batch_size <= 10_000:
            raise HistoryConfigurationError("UWFLOW_HISTORY_BATCH_SIZE must be between 1 and 10000")

        if for_write and for_admin:
            raise HistoryConfigurationError("Choose either a writer DSN or an admin DSN")

        if connector == "postgres":
            dsn_key = (
                "UWFLOW_HISTORY_ADMIN_DSN"
                if for_admin
                else "UWFLOW_HISTORY_WRITE_DSN"
                if for_write
                else "UWFLOW_HISTORY_DSN"
            )
            dsn = os.getenv(dsn_key)
            if not dsn:
                raise HistoryConfigurationError(f"{dsn_key} must be configured")
            if not dsn.startswith(("postgresql+psycopg://", "postgresql+psycopg2://")):
                raise HistoryConfigurationError(
                    f"{dsn_key} must use an explicit PostgreSQL driver URL, e.g. "
                    "postgresql+psycopg://..."
                )
            root = None
        else:
            root_value = os.getenv(
                "UWFLOW_HISTORY_WRITE_ROOT" if for_write else "UWFLOW_HISTORY_ROOT"
            )
            root_value = root_value or os.getenv("UWFLOW_HISTORY_ROOT")
            if not root_value:
                raise HistoryConfigurationError(
                    "UWFLOW_HISTORY_ROOT must be configured for parquet"
                )
            dsn = None
            root = Path(root_value).expanduser().resolve()

        return cls(
            connector=connector,
            dsn=dsn,
            root=root,
            batch_size=batch_size,
            schema_history=os.getenv("UWFLOW_HISTORY_SCHEMA_HISTORY", "history"),
            schema_sources=os.getenv("UWFLOW_HISTORY_SCHEMA_SOURCES", "sources"),
            schema_outcomes=os.getenv("UWFLOW_HISTORY_SCHEMA_OUTCOMES", "outcomes"),
            schema_simulation=os.getenv("UWFLOW_HISTORY_SCHEMA_SIMULATION", "simulation"),
        )


def require_write_approval(*, cli_flag: bool) -> None:
    """Require both an explicit CLI acknowledgement and an explicit env opt-in."""
    read_only = os.getenv("UWFLOW_HISTORY_READ_ONLY", "true").strip().lower()
    if read_only not in {"false", "0", "no"}:
        raise HistoryConfigurationError(
            "History storage is read-only by default. Set UWFLOW_HISTORY_READ_ONLY=false "
            "for this one-off writer process."
        )
    if not cli_flag:
        raise HistoryConfigurationError(
            "Dataset writes also require the explicit --allow-write command-line flag."
        )
