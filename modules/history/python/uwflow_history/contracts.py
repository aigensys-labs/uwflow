"""Stable contracts shared by historical-data connectors and replay workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Protocol, runtime_checkable


MANIFEST_SCHEMA_VERSION = 1
CASE_SCHEMA_VERSION = 2


def _timestamp(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Immutable metadata describing one logical historical dataset snapshot."""

    dataset_id: str
    display_name: str
    case_count: int
    created_at: str
    as_of_timestamp: str
    history_start: str
    history_end: str
    synthetic: bool
    source_snapshot_semantics: str
    outcome_definition: str
    data_sha256: str | None = None
    manifest_schema_version: int = MANIFEST_SCHEMA_VERSION
    case_schema_version: int = CASE_SCHEMA_VERSION
    generator_name: str | None = None
    generator_version: str | None = None
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dataset_id or len(self.dataset_id) > 128:
            raise ValueError("dataset_id must contain 1-128 characters")
        if self.case_count < 1:
            raise ValueError("case_count must be at least 1")
        if self.manifest_schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported dataset manifest schema version")
        if self.case_schema_version != CASE_SCHEMA_VERSION:
            raise ValueError("Unsupported historical case schema version")
        if self.source_snapshot_semantics not in {
            "OBSERVED_AT_ORIGINAL_DECISION",
            "SYNTHETIC_CONSENTED_FIXTURE_AVAILABILITY",
        }:
            raise ValueError("Unsupported source_snapshot_semantics")
        if self.data_sha256 is not None and (
            len(self.data_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.data_sha256)
        ):
            raise ValueError("data_sha256 must be a lowercase SHA-256 hex digest")
        history_start = _timestamp(self.history_start, "history_start")
        history_end = _timestamp(self.history_end, "history_end")
        as_of = _timestamp(self.as_of_timestamp, "as_of_timestamp")
        _timestamp(self.created_at, "created_at")
        if history_start > history_end or history_end > as_of:
            raise ValueError(
                "Dataset history window must satisfy history_start <= history_end <= as_of"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the validated dataset manifest to its canonical mapping representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DatasetManifest":
        """Validate and construct a dataset manifest from a decoded mapping."""
        required = {"manifest_schema_version", "case_schema_version"}
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"Dataset manifest is missing required schema fields: {missing}")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class HistoricalCase:
    """One point-in-time application view plus separately observed outcomes."""

    application_id: str
    application_snapshot_id: str
    application_timestamp: str
    decision_timestamp: str
    application: dict[str, Any]
    bureau_snapshot: dict[str, Any] | None
    alternative_data_snapshots: tuple[dict[str, Any], ...] = ()
    outcome_snapshot: dict[str, Any] | None = None
    recorded_decision_snapshot: dict[str, Any] | None = None
    segments: dict[str, str] = field(default_factory=dict)
    case_schema_version: int = CASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.case_schema_version != CASE_SCHEMA_VERSION:
            raise ValueError("Unsupported historical case schema version")
        if not self.application_id:
            raise ValueError("application_id is required")
        if str(self.application.get("applicant_id", "")) != self.application_id:
            raise ValueError("application.applicant_id must match application_id")
        application_at = _timestamp(self.application_timestamp, "application_timestamp")
        decision_at = _timestamp(self.decision_timestamp, "decision_timestamp")
        if decision_at < application_at:
            raise ValueError("decision_timestamp cannot precede application_timestamp")
        if self.bureau_snapshot:
            observed_at = self.bureau_snapshot.get("retrieved_at") or self.bureau_snapshot.get(
                "observed_at"
            )
            if not observed_at:
                raise ValueError("Bureau snapshot must carry its retrieval/observation timestamp")
            if _timestamp(str(observed_at), "bureau snapshot timestamp") > decision_at:
                raise ValueError(
                    "Bureau snapshot cannot be observed after the underwriting decision"
                )
        for item in self.alternative_data_snapshots:
            observed_at = item.get("retrieved_at") or item.get("observed_at")
            if not observed_at:
                raise ValueError(
                    "Every alternative-data snapshot must carry its retrieval/observation timestamp"
                )
            if _timestamp(str(observed_at), "alternative-data snapshot timestamp") > decision_at:
                raise ValueError(
                    "Alternative-data snapshot cannot be observed after the underwriting decision"
                )
        if self.outcome_snapshot:
            observed_at = self.outcome_snapshot.get("observed_at")
            if not observed_at:
                raise ValueError("Outcome snapshot must carry its observation timestamp")
            if _timestamp(str(observed_at), "outcome timestamp") < decision_at:
                raise ValueError("Outcome observation cannot precede the underwriting decision")
        if self.recorded_decision_snapshot is not None:
            recorded = self.recorded_decision_snapshot
            if recorded.get("application_id") != self.application_id:
                raise ValueError("Recorded decision application_id must match application_id")
            recorded_at = recorded.get("decision_timestamp")
            if not recorded_at:
                raise ValueError("Recorded decision snapshot must carry decision_timestamp")
            if _timestamp(str(recorded_at), "recorded decision timestamp") != decision_at:
                raise ValueError(
                    "Recorded decision timestamp must match the original decision_timestamp"
                )
            if recorded.get("decision") not in {"APPROVED", "COUNTEROFFER", "REFER", "DECLINED"}:
                raise ValueError(
                    "Recorded decision must be APPROVED, COUNTEROFFER, REFER or DECLINED"
                )
            if (
                not isinstance(recorded.get("policy_version"), str)
                or not recorded["policy_version"].strip()
            ):
                raise ValueError("Recorded decision snapshot must include policy_version")
            manifest_hash = recorded.get("runtime_manifest_sha256")
            if manifest_hash is not None and (
                not isinstance(manifest_hash, str)
                or len(manifest_hash) != 64
                or any(char not in "0123456789abcdef" for char in manifest_hash)
            ):
                raise ValueError(
                    "Recorded decision runtime_manifest_sha256 must be a lowercase SHA-256 digest"
                )
            source_refs = recorded.get("source_snapshot_ids", {})
            if not isinstance(source_refs, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in source_refs.items()
            ):
                raise ValueError(
                    "Recorded decision source_snapshot_ids must be a string-to-string mapping"
                )
        source_ids = [str(item.get("source_id", "")) for item in self.alternative_data_snapshots]
        if any(not item for item in source_ids):
            raise ValueError("Every alternative-data snapshot must have a source_id")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Duplicate alternative-data source snapshots are not allowed")

    def to_dict(self) -> dict[str, Any]:
        # Source row order is not semantically meaningful. Canonicalize it so
        # that connector iteration order cannot change the dataset checksum.
        """Serialize the historical case and its evidence snapshots to a mapping."""
        ordered_sources = sorted(
            self.alternative_data_snapshots,
            key=lambda item: str(item.get("source_id", "")),
        )
        payload = {
            "application_id": self.application_id,
            "application_snapshot_id": self.application_snapshot_id,
            "application_timestamp": self.application_timestamp,
            "decision_timestamp": self.decision_timestamp,
            "application": self.application,
            "bureau_snapshot": self.bureau_snapshot,
            "alternative_data_snapshots": ordered_sources,
            "outcome_snapshot": self.outcome_snapshot,
            "recorded_decision_snapshot": self.recorded_decision_snapshot,
            "segments": self.segments,
            "case_schema_version": self.case_schema_version,
        }
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "HistoricalCase":
        """Validate and construct a historical case from a decoded mapping."""
        if "case_schema_version" not in value:
            raise ValueError("Historical case is missing required case_schema_version")
        return cls(
            application_id=str(value["application_id"]),
            application_snapshot_id=str(value["application_snapshot_id"]),
            application_timestamp=str(value["application_timestamp"]),
            decision_timestamp=str(value["decision_timestamp"]),
            application=dict(value["application"]),
            bureau_snapshot=(
                dict(value["bureau_snapshot"]) if value.get("bureau_snapshot") else None
            ),
            alternative_data_snapshots=tuple(
                dict(item) for item in value.get("alternative_data_snapshots", [])
            ),
            outcome_snapshot=(
                dict(value["outcome_snapshot"]) if value.get("outcome_snapshot") else None
            ),
            recorded_decision_snapshot=(
                dict(value["recorded_decision_snapshot"])
                if value.get("recorded_decision_snapshot")
                else None
            ),
            segments={str(k): str(v) for k, v in value.get("segments", {}).items()},
            case_schema_version=int(value["case_schema_version"]),
        )


@runtime_checkable
class HistoricalDataSource(Protocol):
    """Read-only connector; iter_cases must return application_id order."""

    def list_datasets(self) -> list[DatasetManifest]:
        """Return the dataset manifests available from this read-only source."""
        ...

    def get_manifest(self, dataset_id: str) -> DatasetManifest:
        """Return the manifest for the requested dataset identifier."""
        ...

    def iter_cases(
        self,
        dataset_id: str,
        *,
        batch_size: int = 5000,
        offset: int = 0,
        limit: int | None = None,
    ) -> Iterator[HistoricalCase]:
        """Iterate the requested dataset's cases in stable sequence order."""
        ...


@runtime_checkable
class HistoricalDataSink(Protocol):
    """Write-once connector; cases must be supplied in strict application_id order."""

    def initialize(self) -> None:
        """Prepare the destination for immutable historical dataset writes."""
        ...

    def write_dataset(
        self,
        manifest: DatasetManifest,
        cases: Iterable[HistoricalCase],
        *,
        batch_size: int = 1000,
    ) -> DatasetManifest:
        """Write one complete dataset and its manifest to the destination."""
        ...
