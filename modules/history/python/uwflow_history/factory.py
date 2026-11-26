"""Connector factory. Business logic depends only on the data contracts."""

from __future__ import annotations

from uwflow_history.config import HistoryConfig, HistoryConfigurationError, require_write_approval
from uwflow_history.contracts import HistoricalDataSink, HistoricalDataSource


def create_history_source(config: HistoryConfig | None = None) -> HistoricalDataSource:
    """Create the configured read-only historical-data connector."""
    config = config or HistoryConfig.from_env(for_write=False)
    if config.connector == "postgres":
        from uwflow_history.connectors.postgres import PostgresHistoryStore

        return PostgresHistoryStore(
            config.dsn,
            batch_size=config.batch_size,
            schemas={
                "history": config.schema_history,
                "sources": config.schema_sources,
                "outcomes": config.schema_outcomes,
                "simulation": config.schema_simulation,
            },
            read_only=True,
        )
    if config.connector == "parquet":
        from uwflow_history.connectors.parquet import ParquetHistoryStore

        assert config.root is not None
        return ParquetHistoryStore(config.root, read_only=True)
    raise HistoryConfigurationError(f"Unsupported connector: {config.connector}")


def create_history_sink(
    *, allow_write: bool, config: HistoryConfig | None = None
) -> HistoricalDataSink:
    """Create a history writer after the caller has explicitly authorized writes."""
    require_write_approval(cli_flag=allow_write)
    config = config or HistoryConfig.from_env(for_write=True)
    if config.connector == "postgres":
        from uwflow_history.connectors.postgres import PostgresHistoryStore

        return PostgresHistoryStore(
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
    if config.connector == "parquet":
        from uwflow_history.connectors.parquet import ParquetHistoryStore

        assert config.root is not None
        return ParquetHistoryStore(config.root, read_only=False)
    raise HistoryConfigurationError(f"Unsupported connector: {config.connector}")
