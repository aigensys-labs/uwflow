"""PostgreSQL historical-data store with write-once dataset snapshots.

SQLAlchemy is imported lazily so using the Parquet connector does not require
PostgreSQL dependencies. SQLite engines are accepted for connector contract
tests; production PostgreSQL uses the configured logical schemas.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import re
from typing import Any, Iterable, Iterator

from uwflow_history.canonical import canonical_json, update_case_digest, validate_dataset_id
from uwflow_history.config import HistoryConfigurationError
from uwflow_history.contracts import DatasetManifest, HistoricalCase


class DatasetAlreadyExistsError(RuntimeError):
    """Raised when a write attempts to replace an immutable dataset ID."""


class DatasetNotFoundError(LookupError):
    """Raised when a requested dataset snapshot is not present."""


class HistoryStoreError(RuntimeError):
    """Raised for invalid dataset storage or retrieval operations."""


class PostgresHistoryStore:
    """Read-only-by-default PostgreSQL adapter for historical case snapshots."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        batch_size: int = 2000,
        schemas: dict[str, str] | None = None,
        engine: Any | None = None,
        read_only: bool = True,
    ) -> None:
        try:
            from sqlalchemy import (
                JSON,
                Column,
                MetaData,
                PrimaryKeyConstraint,
                String,
                Table,
                Text,
                create_engine,
                event,
                select,
            )
            from sqlalchemy.dialects.postgresql import JSONB
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise HistoryConfigurationError(
                "PostgreSQL connector requires SQLAlchemy and psycopg. "
                'Install with: python -m pip install -e ".[history-postgres]"'
            ) from exc

        if engine is None and not dsn:
            raise HistoryConfigurationError("A PostgreSQL DSN is required")
        self.batch_size = batch_size
        self.read_only = read_only
        self._sa = {
            "Column": Column,
            "MetaData": MetaData,
            "PrimaryKeyConstraint": PrimaryKeyConstraint,
            "String": String,
            "Table": Table,
            "Text": Text,
            "select": select,
        }
        connect_args: dict[str, Any] = {}
        if engine is None and read_only:
            # Enforce read-only transaction defaults in the replay process.
            # This is defense in depth; production should also use a DB role
            # that has SELECT privileges only.
            connect_args["options"] = "-c default_transaction_read_only=on"
        self.engine = engine or create_engine(
            str(dsn),
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args=connect_args,
        )

        if self.engine.dialect.name == "sqlite":
            schema_map = {key: None for key in (schemas or {}).keys()}
            json_type = JSON()
        else:
            defaults = {
                "history": "history",
                "sources": "sources",
                "outcomes": "outcomes",
                "simulation": "simulation",
            }
            defaults.update(schemas or {})
            for schema_name in defaults.values():
                if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", str(schema_name)):
                    raise HistoryConfigurationError(
                        "PostgreSQL schema names must be lowercase identifiers using a-z, 0-9 and underscore"
                    )
            schema_map = defaults
            json_type = JSON().with_variant(JSONB(), "postgresql")

        self.schemas = schema_map
        meta = MetaData()
        col = Column
        primary = PrimaryKeyConstraint
        string = String
        text_type = Text
        table = Table
        self.datasets = table(
            "dataset_manifests",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("created_at", string(40), nullable=False),
            col("manifest_json", json_type, nullable=False),
            primary("dataset_id"),
            schema=schema_map.get("simulation"),
        )
        self.applications = table(
            "application_snapshots",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("application_id", string(128), nullable=False),
            col("snapshot_id", string(160), nullable=False),
            col("application_timestamp", string(40), nullable=False),
            col("decision_timestamp", string(40), nullable=False),
            col("payload", json_type, nullable=False),
            col("segments", json_type, nullable=False),
            primary("dataset_id", "application_id"),
            schema=schema_map.get("history"),
        )
        self.bureau = table(
            "bureau_snapshots",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("application_id", string(128), nullable=False),
            col("snapshot_id", string(160), nullable=False),
            col("observed_at", string(40), nullable=False),
            col("payload", json_type, nullable=False),
            primary("dataset_id", "application_id"),
            schema=schema_map.get("sources"),
        )
        self.alternative = table(
            "alternative_data_snapshots",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("application_id", string(128), nullable=False),
            col("source_id", string(128), nullable=False),
            col("snapshot_id", string(160), nullable=False),
            col("observed_at", string(40), nullable=False),
            col("payload", json_type, nullable=False),
            primary("dataset_id", "application_id", "source_id"),
            schema=schema_map.get("sources"),
        )
        self.outcomes = table(
            "credit_outcomes",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("application_id", string(128), nullable=False),
            col("outcome_id", string(160), nullable=False),
            col("observed_at", string(40), nullable=False),
            col("payload", json_type, nullable=False),
            primary("dataset_id", "application_id"),
            schema=schema_map.get("outcomes"),
        )
        self.recorded_decisions = table(
            "decision_snapshots",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("application_id", string(128), nullable=False),
            col("decision_timestamp", string(40), nullable=False),
            col("payload", json_type, nullable=False),
            primary("dataset_id", "application_id"),
            schema=schema_map.get("history"),
        )
        # Keep the exact canonical case JSON alongside the query-friendly
        # decomposed tables. PostgreSQL JSONB is semantically stable but its
        # serialization can differ from Python's JSON representation. The
        # canonical text is the authoritative replay/checksum payload, while
        # the other tables remain available for relational access and audit.
        self.canonical_cases = table(
            "canonical_case_payloads",
            meta,
            col("dataset_id", string(128), nullable=False),
            col("application_id", string(128), nullable=False),
            col("payload_json", text_type, nullable=False),
            primary("dataset_id", "application_id"),
            schema=schema_map.get("history"),
        )
        self.metadata = meta
        self._select = select
        self._event = event
        self._read_only_listener_installed = False
        if engine is not None and not read_only and self.engine.dialect.name != "sqlite":
            self._install_read_only_guard_if_requested()

    def _install_read_only_guard_if_requested(self) -> None:
        return

    def initialize(self) -> None:
        """Create required schemas/tables. This is an explicit admin operation."""
        if self.read_only:
            raise HistoryStoreError("Cannot initialize schema using a read-only connector")
        if self.engine.dialect.name != "sqlite":
            from sqlalchemy import text

            with self.engine.begin() as connection:
                for schema in self.schemas.values():
                    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        self.metadata.create_all(self.engine)

    def list_datasets(self) -> list[DatasetManifest]:
        """List validated dataset manifests from the PostgreSQL history schema."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                self._select(self.datasets.c.manifest_json).order_by(
                    self.datasets.c.created_at.desc()
                )
            ).scalars()
            return [DatasetManifest.from_dict(dict(row)) for row in rows]

    def get_manifest(self, dataset_id: str) -> DatasetManifest:
        """Load one dataset manifest from PostgreSQL."""
        validate_dataset_id(dataset_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                self._select(self.datasets.c.manifest_json).where(
                    self.datasets.c.dataset_id == dataset_id
                )
            ).scalar_one_or_none()
        if row is None:
            raise DatasetNotFoundError(f"Historical dataset not found: {dataset_id}")
        return DatasetManifest.from_dict(dict(row))

    def iter_cases(
        self,
        dataset_id: str,
        *,
        batch_size: int = 5000,
        offset: int = 0,
        limit: int | None = None,
    ) -> Iterator[HistoricalCase]:
        """Yield historical cases from PostgreSQL in deterministic sequence order."""
        validate_dataset_id(dataset_id)
        if batch_size < 1 or batch_size > 10_000 or offset < 0 or (limit is not None and limit < 1):
            raise ValueError(
                "PostgreSQL batch_size must be between 1 and 10000; "
                "offset non-negative; limit positive or None"
            )
        manifest = self.get_manifest(dataset_id)
        canonical_format = manifest.metadata.get("canonical_payload_format")
        if canonical_format != "json-v1":
            raise HistoryStoreError(
                "Dataset manifest must declare canonical_payload_format=json-v1; "
                "reconstructed historical cases are not supported"
            )
        query = (
            self._select(self.applications)
            .where(self.applications.c.dataset_id == dataset_id)
            .order_by(self.applications.c.application_id)
            .offset(offset)
        )
        if limit is not None:
            query = query.limit(limit)

        with self.engine.connect() as connection:
            result = connection.execution_options(stream_results=True).execute(query).mappings()
            while application_rows := result.fetchmany(batch_size):
                application_ids = [str(row["application_id"]) for row in application_rows]
                canonical_rows = (
                    connection.execute(
                        self._select(self.canonical_cases).where(
                            self.canonical_cases.c.dataset_id == dataset_id,
                            self.canonical_cases.c.application_id.in_(application_ids),
                        )
                    )
                    .mappings()
                    .all()
                )
                canonical_payloads = {
                    str(row["application_id"]): str(row["payload_json"]) for row in canonical_rows
                }
                if len(canonical_payloads) != len(application_rows):
                    raise HistoryStoreError(
                        "Dataset has an incomplete canonical payload set; "
                        "all application rows must have canonical JSON payloads"
                    )

                # Read the decomposed tables too. The canonical text payload is
                # the checksum/replay source of truth, while these rows remain
                # query-friendly projections. Verify that both representations
                # still describe the same case before returning the canonical
                # record to replay workers.
                bureau_rows = (
                    connection.execute(
                        self._select(self.bureau).where(
                            self.bureau.c.dataset_id == dataset_id,
                            self.bureau.c.application_id.in_(application_ids),
                        )
                    )
                    .mappings()
                    .all()
                )
                source_rows = (
                    connection.execute(
                        self._select(self.alternative)
                        .where(
                            self.alternative.c.dataset_id == dataset_id,
                            self.alternative.c.application_id.in_(application_ids),
                        )
                        .order_by(self.alternative.c.application_id, self.alternative.c.source_id)
                    )
                    .mappings()
                    .all()
                )
                outcome_rows = (
                    connection.execute(
                        self._select(self.outcomes).where(
                            self.outcomes.c.dataset_id == dataset_id,
                            self.outcomes.c.application_id.in_(application_ids),
                        )
                    )
                    .mappings()
                    .all()
                )
                decision_rows = (
                    connection.execute(
                        self._select(self.recorded_decisions).where(
                            self.recorded_decisions.c.dataset_id == dataset_id,
                            self.recorded_decisions.c.application_id.in_(application_ids),
                        )
                    )
                    .mappings()
                    .all()
                )

                bureaus = {str(row["application_id"]): dict(row["payload"]) for row in bureau_rows}
                sources: dict[str, list[dict[str, Any]]] = {}
                for row in source_rows:
                    sources.setdefault(str(row["application_id"]), []).append(dict(row["payload"]))
                outcomes = {
                    str(row["application_id"]): dict(row["payload"]) for row in outcome_rows
                }
                recorded_decisions = {
                    str(row["application_id"]): dict(row["payload"]) for row in decision_rows
                }

                for row in application_rows:
                    app_id = str(row["application_id"])
                    relational_case = HistoricalCase(
                        application_id=app_id,
                        application_snapshot_id=str(row["snapshot_id"]),
                        application_timestamp=str(row["application_timestamp"]),
                        decision_timestamp=str(row["decision_timestamp"]),
                        application=dict(row["payload"]),
                        bureau_snapshot=bureaus.get(app_id),
                        alternative_data_snapshots=tuple(sources.get(app_id, [])),
                        outcome_snapshot=outcomes.get(app_id),
                        recorded_decision_snapshot=recorded_decisions.get(app_id),
                        segments={str(k): str(v) for k, v in dict(row["segments"]).items()},
                        case_schema_version=manifest.case_schema_version,
                    )
                    try:
                        payload = json.loads(canonical_payloads[app_id])
                    except (KeyError, json.JSONDecodeError) as exc:
                        raise HistoryStoreError(
                            f"Canonical historical payload is invalid for application {app_id}"
                        ) from exc
                    if not isinstance(payload, dict):
                        raise HistoryStoreError(
                            f"Canonical historical payload is not an object for application {app_id}"
                        )
                    canonical_case = HistoricalCase.from_dict(payload)
                    if canonical_case.to_dict() != relational_case.to_dict():
                        raise HistoryStoreError(
                            "Canonical payload and decomposed historical rows disagree for "
                            f"application {app_id}; dataset integrity check failed"
                        )
                    yield canonical_case

    def write_dataset(
        self,
        manifest: DatasetManifest,
        cases: Iterable[HistoricalCase],
        *,
        batch_size: int = 1000,
    ) -> DatasetManifest:
        """Persist a new immutable dataset and its cases in PostgreSQL."""
        if self.read_only:
            raise HistoryStoreError("Dataset writes are disabled for this read-only connector")
        validate_dataset_id(manifest.dataset_id)
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        # Schema creation is an explicit admin-only operation (`init_history_db.py`).
        # The dataset writer role has INSERT/SELECT only and cannot run DDL.
        digest = hashlib.sha256()
        observed = 0
        app_rows: list[dict[str, Any]] = []
        bureau_rows: list[dict[str, Any]] = []
        source_rows: list[dict[str, Any]] = []
        outcome_rows: list[dict[str, Any]] = []
        decision_rows: list[dict[str, Any]] = []
        canonical_rows: list[dict[str, Any]] = []
        final_manifest: DatasetManifest | None = None
        previous_application_id: str | None = None

        with self.engine.begin() as connection:
            existing = connection.execute(
                self._select(self.datasets.c.dataset_id).where(
                    self.datasets.c.dataset_id == manifest.dataset_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise DatasetAlreadyExistsError(
                    f"Dataset {manifest.dataset_id!r} already exists; dataset snapshots are immutable"
                )

            def flush() -> None:
                if app_rows:
                    connection.execute(self.applications.insert(), list(app_rows))
                    app_rows.clear()
                if bureau_rows:
                    connection.execute(self.bureau.insert(), list(bureau_rows))
                    bureau_rows.clear()
                if source_rows:
                    connection.execute(self.alternative.insert(), list(source_rows))
                    source_rows.clear()
                if outcome_rows:
                    connection.execute(self.outcomes.insert(), list(outcome_rows))
                    outcome_rows.clear()
                if decision_rows:
                    connection.execute(self.recorded_decisions.insert(), list(decision_rows))
                    decision_rows.clear()
                if canonical_rows:
                    connection.execute(self.canonical_cases.insert(), list(canonical_rows))
                    canonical_rows.clear()

            for case in cases:
                if (
                    previous_application_id is not None
                    and case.application_id <= previous_application_id
                ):
                    raise HistoryStoreError(
                        "Dataset cases must be supplied in strictly increasing application_id order"
                    )
                previous_application_id = case.application_id
                if case.case_schema_version != manifest.case_schema_version:
                    raise HistoryStoreError(
                        f"Case schema version {case.case_schema_version} does not match dataset manifest "
                        f"version {manifest.case_schema_version}"
                    )
                case_payload = case.to_dict()
                payload_json = canonical_json(case_payload)
                update_case_digest(digest, case_payload)
                canonical_rows.append(
                    {
                        "dataset_id": manifest.dataset_id,
                        "application_id": case.application_id,
                        "payload_json": payload_json,
                    }
                )
                observed += 1
                app_rows.append(
                    {
                        "dataset_id": manifest.dataset_id,
                        "application_id": case.application_id,
                        "snapshot_id": case.application_snapshot_id,
                        "application_timestamp": case.application_timestamp,
                        "decision_timestamp": case.decision_timestamp,
                        "payload": case.application,
                        "segments": case.segments,
                    }
                )
                if case.bureau_snapshot is not None:
                    bureau_rows.append(
                        {
                            "dataset_id": manifest.dataset_id,
                            "application_id": case.application_id,
                            "snapshot_id": str(
                                case.bureau_snapshot.get("snapshot_id", "bureau-unknown")
                            ),
                            "observed_at": str(
                                case.bureau_snapshot.get("retrieved_at", case.decision_timestamp)
                            ),
                            "payload": case.bureau_snapshot,
                        }
                    )
                for source in case.alternative_data_snapshots:
                    source_rows.append(
                        {
                            "dataset_id": manifest.dataset_id,
                            "application_id": case.application_id,
                            "source_id": str(source["source_id"]),
                            "snapshot_id": str(
                                source.get("snapshot_id", f"{source['source_id']}-unknown")
                            ),
                            "observed_at": str(source.get("retrieved_at", case.decision_timestamp)),
                            "payload": source,
                        }
                    )
                if case.outcome_snapshot is not None:
                    outcome_rows.append(
                        {
                            "dataset_id": manifest.dataset_id,
                            "application_id": case.application_id,
                            "outcome_id": str(
                                case.outcome_snapshot.get("outcome_id", "outcome-unknown")
                            ),
                            "observed_at": str(
                                case.outcome_snapshot.get("observed_at", manifest.as_of_timestamp)
                            ),
                            "payload": case.outcome_snapshot,
                        }
                    )
                if case.recorded_decision_snapshot is not None:
                    decision_rows.append(
                        {
                            "dataset_id": manifest.dataset_id,
                            "application_id": case.application_id,
                            "decision_timestamp": case.decision_timestamp,
                            "payload": case.recorded_decision_snapshot,
                        }
                    )
                if observed % batch_size == 0:
                    flush()

            flush()
            if observed != manifest.case_count:
                raise HistoryStoreError(
                    f"Manifest case_count={manifest.case_count}, but writer received {observed} cases"
                )
            final_manifest = replace(
                manifest,
                data_sha256=digest.hexdigest(),
                metadata={
                    **manifest.metadata,
                    "canonical_payload_format": "json-v1",
                },
            )
            connection.execute(
                self.datasets.insert().values(
                    dataset_id=final_manifest.dataset_id,
                    created_at=final_manifest.created_at,
                    manifest_json=final_manifest.to_dict(),
                )
            )
        assert final_manifest is not None
        return final_manifest

    def close(self) -> None:
        """Dispose of the SQLAlchemy resources owned by the store."""
        self.engine.dispose()
