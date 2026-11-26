"""Immutable Parquet dataset connector with atomic directory publication."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any, Iterable, Iterator

from uwflow_history.canonical import update_case_digest, validate_dataset_id
from uwflow_history.config import HistoryConfigurationError
from uwflow_history.contracts import DatasetManifest, HistoricalCase
from uwflow_history.connectors.postgres import (
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
    HistoryStoreError,
)


class ParquetHistoryStore:
    """Parquet-backed historical snapshots; pyarrow is loaded only when used."""

    def __init__(self, root: Path | str, *, read_only: bool = True) -> None:
        self.root = Path(root).expanduser().resolve()
        self.read_only = read_only
        self._pa = None
        self._pq = None

    def _load_arrow(self) -> tuple[Any, Any]:
        if self._pa is not None and self._pq is not None:
            return self._pa, self._pq
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise HistoryConfigurationError(
                "Parquet connector requires PyArrow. Install with: "
                'python -m pip install -e ".[history-parquet]"'
            ) from exc
        self._pa, self._pq = pa, pq
        return pa, pq

    def initialize(self) -> None:
        """Create the local Parquet dataset area when write access is enabled."""
        if self.read_only:
            raise HistoryStoreError("Cannot initialize Parquet storage using a read-only connector")
        self.root.mkdir(parents=True, exist_ok=True)

    def list_datasets(self) -> list[DatasetManifest]:
        """List validated dataset manifests available in the Parquet store."""
        if not self.root.exists():
            return []
        manifests: list[DatasetManifest] = []
        for path in self.root.iterdir():
            manifest_path = path / "manifest.json"
            if path.is_dir() and manifest_path.is_file():
                manifests.append(
                    DatasetManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
                )
        return sorted(manifests, key=lambda item: item.created_at, reverse=True)

    def get_manifest(self, dataset_id: str) -> DatasetManifest:
        """Load the manifest for one dataset or raise when it is absent or invalid."""
        validate_dataset_id(dataset_id)
        path = self.root / dataset_id / "manifest.json"
        if not path.is_file():
            raise DatasetNotFoundError(f"Historical dataset not found: {dataset_id}")
        return DatasetManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def iter_cases(
        self,
        dataset_id: str,
        *,
        batch_size: int = 5000,
        offset: int = 0,
        limit: int | None = None,
    ) -> Iterator[HistoricalCase]:
        """Yield validated historical cases from a dataset in deterministic order."""
        validate_dataset_id(dataset_id)
        if batch_size < 1 or offset < 0 or (limit is not None and limit < 1):
            raise ValueError(
                "batch_size must be positive; offset non-negative; limit positive or None"
            )
        manifest = self.get_manifest(dataset_id)
        _, pq = self._load_arrow()
        parquet_file = pq.ParquetFile(self.root / dataset_id / "cases.parquet")
        skipped = 0
        emitted = 0
        for batch in parquet_file.iter_batches(batch_size=batch_size):
            for row in batch.to_pylist():
                if skipped < offset:
                    skipped += 1
                    continue
                if limit is not None and emitted >= limit:
                    return
                emitted += 1
                yield HistoricalCase.from_dict(
                    {
                        "application_id": row["application_id"],
                        "application_snapshot_id": row["application_snapshot_id"],
                        "application_timestamp": row["application_timestamp"],
                        "decision_timestamp": row["decision_timestamp"],
                        "application": json.loads(row["application_json"]),
                        "bureau_snapshot": json.loads(row["bureau_json"])
                        if row["bureau_json"]
                        else None,
                        "alternative_data_snapshots": json.loads(row["alternative_data_json"]),
                        "outcome_snapshot": json.loads(row["outcome_json"])
                        if row["outcome_json"]
                        else None,
                        "recorded_decision_snapshot": (
                            json.loads(row["recorded_decision_json"])
                            if row["recorded_decision_json"]
                            else None
                        ),
                        "segments": json.loads(row["segments_json"]),
                        "case_schema_version": manifest.case_schema_version,
                    }
                )

    def write_dataset(
        self,
        manifest: DatasetManifest,
        cases: Iterable[HistoricalCase],
        *,
        batch_size: int = 1000,
    ) -> DatasetManifest:
        """Write a new immutable dataset and its manifest to Parquet storage."""
        if self.read_only:
            raise HistoryStoreError("Dataset writes are disabled for this read-only connector")
        validate_dataset_id(manifest.dataset_id)
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        pa, pq = self._load_arrow()
        self.initialize()
        target = self.root / manifest.dataset_id
        if target.exists():
            raise DatasetAlreadyExistsError(
                f"Dataset {manifest.dataset_id!r} already exists; dataset snapshots are immutable"
            )
        temporary = self.root / f".{manifest.dataset_id}.tmp-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True, exist_ok=False)
        schema = pa.schema(
            [
                ("application_id", pa.string()),
                ("application_snapshot_id", pa.string()),
                ("application_timestamp", pa.string()),
                ("decision_timestamp", pa.string()),
                ("application_json", pa.string()),
                ("bureau_json", pa.string()),
                ("alternative_data_json", pa.string()),
                ("outcome_json", pa.string()),
                ("recorded_decision_json", pa.string()),
                ("segments_json", pa.string()),
            ]
        )
        writer = None
        digest = hashlib.sha256()
        observed = 0
        previous_application_id: str | None = None
        buffer: list[dict[str, str | None]] = []
        try:
            writer = pq.ParquetWriter(
                temporary / "cases.parquet", schema=schema, compression="zstd"
            )
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
                update_case_digest(digest, case.to_dict())
                observed += 1
                buffer.append(
                    {
                        "application_id": case.application_id,
                        "application_snapshot_id": case.application_snapshot_id,
                        "application_timestamp": case.application_timestamp,
                        "decision_timestamp": case.decision_timestamp,
                        "application_json": json.dumps(
                            case.application, ensure_ascii=False, sort_keys=True
                        ),
                        "bureau_json": json.dumps(
                            case.bureau_snapshot, ensure_ascii=False, sort_keys=True
                        )
                        if case.bureau_snapshot is not None
                        else None,
                        "alternative_data_json": json.dumps(
                            list(case.alternative_data_snapshots),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "outcome_json": json.dumps(
                            case.outcome_snapshot, ensure_ascii=False, sort_keys=True
                        )
                        if case.outcome_snapshot is not None
                        else None,
                        "recorded_decision_json": (
                            json.dumps(
                                case.recorded_decision_snapshot, ensure_ascii=False, sort_keys=True
                            )
                            if case.recorded_decision_snapshot is not None
                            else None
                        ),
                        "segments_json": json.dumps(
                            case.segments, ensure_ascii=False, sort_keys=True
                        ),
                    }
                )
                if len(buffer) >= batch_size:
                    writer.write_table(pa.Table.from_pylist(buffer, schema=schema))
                    buffer.clear()
            if buffer:
                writer.write_table(pa.Table.from_pylist(buffer, schema=schema))
            writer.close()
            writer = None
            if observed != manifest.case_count:
                raise HistoryStoreError(
                    f"Manifest case_count={manifest.case_count}, but writer received {observed} cases"
                )
            final_manifest = DatasetManifest.from_dict(
                {
                    **manifest.to_dict(),
                    "data_sha256": digest.hexdigest(),
                }
            )
            (temporary / "manifest.json").write_text(
                json.dumps(final_manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            # Atomic rename ensures readers see either no dataset or a complete one.
            os.rename(temporary, target)
            return final_manifest
        except Exception:
            if writer is not None:
                writer.close()
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def close(self) -> None:
        """Release resources owned by the Parquet history store."""
        return
