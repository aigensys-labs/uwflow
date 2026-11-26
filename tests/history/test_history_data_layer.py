"""Tests for historical dataset contracts and PostgreSQL/Parquet data layers."""

from __future__ import annotations

from datetime import date
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

from sqlalchemy import create_engine

from uwflow_history.canonical import update_case_digest
from uwflow_history.config import HistoryConfig, HistoryConfigurationError
from uwflow_history.connectors.postgres import (
    DatasetAlreadyExistsError,
    HistoryStoreError,
    PostgresHistoryStore,
)
from uwflow_history.contracts import DatasetManifest, HistoricalCase
from uwflow_history.generation.synthetic_portfolio import generate_cases, build_manifest
from tools.history.datasets import validate_dataset as validate_history_dataset


def _manifest(dataset_id: str = "test-history") -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        display_name="Test dataset",
        case_count=1,
        created_at="2026-11-22T10:00:00Z",
        as_of_timestamp="2026-11-22T23:59:59Z",
        history_start="2025-11-22T00:00:00Z",
        history_end="2026-11-22T23:59:59Z",
        synthetic=True,
        source_snapshot_semantics="SYNTHETIC_CONSENTED_FIXTURE_AVAILABILITY",
        outcome_definition="test only",
    )


def _case() -> HistoricalCase:
    return HistoricalCase(
        application_id="SYN-1",
        application_snapshot_id="APP-1",
        application_timestamp="2026-01-01T09:00:00Z",
        decision_timestamp="2026-01-01T10:00:00Z",
        application={"applicant_id": "SYN-1", "monthly_income": 1800.0},
        bureau_snapshot={"retrieved_at": "2026-01-01T09:55:00Z", "bureau_score": 680},
        alternative_data_snapshots=(
            {"source_id": "bd_registry", "retrieved_at": "2026-01-01T09:58:00Z", "score": 65},
        ),
        outcome_snapshot={
            "observed_at": "2026-11-22T23:59:59Z",
            "outcome_status": "MATURED",
            "default_12m": False,
            "label_type": "OBSERVED_BOOKED_LOAN",
        },
        segments={"employment_status": "FULL_TIME"},
    )


def test_historical_case_rejects_timezone_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone"):
        HistoricalCase(
            application_id="SYN-1",
            application_snapshot_id="APP-1",
            application_timestamp="2026-01-01T09:00:00",
            decision_timestamp="2026-01-01T10:00:00Z",
            application={"applicant_id": "SYN-1"},
            bureau_snapshot=None,
        )


def test_historical_case_rejects_post_decision_source_observations() -> None:
    with pytest.raises(ValueError, match="after the underwriting decision"):
        HistoricalCase(
            application_id="SYN-1",
            application_snapshot_id="APP-1",
            application_timestamp="2026-01-01T09:00:00Z",
            decision_timestamp="2026-01-01T10:00:00Z",
            application={"applicant_id": "SYN-1"},
            bureau_snapshot=None,
            alternative_data_snapshots=(
                {"source_id": "bd_registry", "retrieved_at": "2026-01-01T10:01:00Z"},
            ),
        )


def test_dataset_manifest_rejects_invalid_history_window() -> None:
    with pytest.raises(ValueError, match="history window"):
        DatasetManifest(
            dataset_id="invalid-window",
            display_name="Invalid",
            case_count=1,
            created_at="2026-11-22T10:00:00Z",
            as_of_timestamp="2026-11-22T23:59:59Z",
            history_start="2026-11-23T00:00:00Z",
            history_end="2026-11-22T23:59:59Z",
            synthetic=True,
            source_snapshot_semantics="OBSERVED_AT_ORIGINAL_DECISION",
            outcome_definition="test",
        )


def test_postgres_adapter_roundtrips_immutable_dataset_through_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    manifest = _manifest()
    case = replace(
        _case(),
        recorded_decision_snapshot={
            "application_id": "SYN-1",
            "decision_timestamp": "2026-01-01T10:00:00Z",
            "decision": "APPROVED",
            "policy_version": "UW-POLICY-2026-01",
            "runtime_release": "2.0.0",
            "model_version": "AIDFLOW-1.0",
            "source_snapshot_ids": {"bureau": "BUR-1"},
        },
    )
    stored = writer.write_dataset(manifest, [case])

    assert stored.data_sha256 is not None
    reader = PostgresHistoryStore(engine=engine, read_only=True)
    assert reader.get_manifest("test-history").data_sha256 == stored.data_sha256
    assert reader.list_datasets()[0].dataset_id == "test-history"
    cases = list(reader.iter_cases("test-history", batch_size=1))
    assert len(cases) == 1
    readback_digest = sha256()
    for case in cases:
        update_case_digest(readback_digest, case.to_dict())
    assert readback_digest.hexdigest() == stored.data_sha256
    assert cases[0].application["monthly_income"] == 1800.0
    assert cases[0].alternative_data_snapshots[0]["source_id"] == "bd_registry"
    assert cases[0].outcome_snapshot["label_type"] == "OBSERVED_BOOKED_LOAN"
    assert cases[0].recorded_decision_snapshot["decision"] == "APPROVED"
    assert cases[0].recorded_decision_snapshot["policy_version"] == "UW-POLICY-2026-01"

    with pytest.raises(DatasetAlreadyExistsError):
        writer.write_dataset(manifest, [_case()])
    reader.close()
    writer.close()


def test_5000_case_postgres_adapter_roundtrip_preserves_canonical_checksum() -> None:
    """Regression for the exact 5,000-case synthetic workflow dataset."""
    as_of = date(2026, 11, 23)
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    manifest = build_manifest(
        dataset_id="checksum-roundtrip-5000",
        count=5000,
        seed=17,
        as_of_date=as_of,
        history_months=36,
    )
    stored = writer.write_dataset(
        manifest,
        generate_cases(count=5000, seed=17, as_of_date=as_of, history_months=36),
        batch_size=500,
    )

    reader = PostgresHistoryStore(engine=engine, read_only=True)
    readback_digest = sha256()
    count = 0
    for case in reader.iter_cases("checksum-roundtrip-5000", batch_size=500):
        update_case_digest(readback_digest, case.to_dict())
        count += 1

    assert count == 5000
    assert readback_digest.hexdigest() == stored.data_sha256
    assert stored.metadata["canonical_payload_format"] == "json-v1"
    reader.close()
    writer.close()


def test_postgres_schema_initialization_adds_canonical_table_idempotently() -> None:
    engine = create_engine("sqlite:///:memory:")
    store = PostgresHistoryStore(engine=engine, read_only=False)
    store.initialize()
    store.canonical_cases.drop(engine)

    # Mirrors an existing installation whose schema predates canonical payloads.
    store.initialize()

    from sqlalchemy import inspect

    assert inspect(engine).has_table("canonical_case_payloads")
    store.close()


def test_postgres_missing_canonical_payloads_fail_closed() -> None:
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    writer.write_dataset(_manifest(), [_case()])

    with engine.begin() as connection:
        connection.execute(
            writer.canonical_cases.delete().where(
                writer.canonical_cases.c.dataset_id == "test-history"
            )
        )

    reader = PostgresHistoryStore(engine=engine, read_only=True)
    with pytest.raises(HistoryStoreError, match="incomplete canonical payload set"):
        list(reader.iter_cases("test-history"))
    reader.close()
    writer.close()


def test_postgres_dataset_without_canonical_payload_contract_is_rejected() -> None:
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    writer.write_dataset(_manifest(), [_case()])

    with engine.begin() as connection:
        manifest = connection.execute(
            writer._select(writer.datasets.c.manifest_json).where(
                writer.datasets.c.dataset_id == "test-history"
            )
        ).scalar_one()
        manifest["metadata"].pop("canonical_payload_format", None)
        connection.execute(
            writer.datasets.update()
            .where(writer.datasets.c.dataset_id == "test-history")
            .values(manifest_json=manifest)
        )

    reader = PostgresHistoryStore(engine=engine, read_only=True)
    with pytest.raises(HistoryStoreError, match="must declare canonical_payload_format=json-v1"):
        list(reader.iter_cases("test-history"))
    reader.close()
    writer.close()


def test_postgres_canonical_payload_is_authoritative_and_projection_tampering_is_detected() -> None:
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    stored = writer.write_dataset(_manifest(), [_case()])

    assert stored.metadata["canonical_payload_format"] == "json-v1"
    with engine.connect() as connection:
        payload_count = connection.execute(
            writer._select(writer.canonical_cases.c.application_id).where(
                writer.canonical_cases.c.dataset_id == "test-history"
            )
        ).all()
    assert len(payload_count) == 1

    # The JSONB-backed projection tables are not the checksum source. They are
    # still checked against the immutable canonical text payload on every read.
    with engine.begin() as connection:
        connection.execute(
            writer.applications.update()
            .where(
                writer.applications.c.dataset_id == "test-history",
                writer.applications.c.application_id == "SYN-1",
            )
            .values(payload={"applicant_id": "SYN-1", "monthly_income": 999.0})
        )

    reader = PostgresHistoryStore(engine=engine, read_only=True)
    with pytest.raises(
        HistoryStoreError, match="Canonical payload and decomposed historical rows disagree"
    ):
        list(reader.iter_cases("test-history"))
    reader.close()
    writer.close()


def test_synthetic_generator_is_deterministic_and_point_in_time_correct() -> None:
    first = list(
        generate_cases(count=32, seed=99, as_of_date=date(2026, 11, 22), history_months=36)
    )
    second = list(
        generate_cases(count=32, seed=99, as_of_date=date(2026, 11, 22), history_months=36)
    )
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert all(item.application_timestamp <= item.decision_timestamp for item in first)
    assert all(
        item.bureau_snapshot["retrieved_at"] <= item.decision_timestamp
        for item in first
        if item.bureau_snapshot
    )
    assert all(
        snapshot["retrieved_at"] <= item.decision_timestamp
        for item in first
        for snapshot in item.alternative_data_snapshots
    )
    assert all(
        item.outcome_snapshot["label_type"]
        == "SYNTHETIC_COUNTERFACTUAL_FSTPD30_NOT_BOOKED_LOAN_PERFORMANCE"
        for item in first
    )
    manifest = build_manifest(
        dataset_id="deterministic-32",
        count=32,
        seed=99,
        as_of_date=date(2026, 11, 22),
        history_months=36,
    )
    assert manifest.synthetic is True
    assert manifest.metadata["outcomes_are_counterfactual"] is True
    assert manifest.case_count == 32


def test_history_connector_is_selected_by_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("UWFLOW_HISTORY_CONNECTOR", "parquet")
    monkeypatch.setenv("UWFLOW_HISTORY_ROOT", str(tmp_path))
    config = HistoryConfig.from_env()
    assert config.connector == "parquet"
    assert config.root == tmp_path.resolve()


def test_postgres_config_requires_explicit_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UWFLOW_HISTORY_CONNECTOR", "postgres")
    monkeypatch.setenv("UWFLOW_HISTORY_DSN", "postgresql://user:password@localhost/db")
    with pytest.raises(HistoryConfigurationError, match="explicit PostgreSQL driver"):
        HistoryConfig.from_env()


def test_postgres_admin_and_writer_dsns_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UWFLOW_HISTORY_CONNECTOR", "postgres")
    monkeypatch.setenv("UWFLOW_HISTORY_ADMIN_DSN", "postgresql+psycopg://owner:secret@localhost/db")
    monkeypatch.setenv(
        "UWFLOW_HISTORY_WRITE_DSN", "postgresql+psycopg://writer:secret@localhost/db"
    )
    assert HistoryConfig.from_env(for_admin=True).dsn.startswith("postgresql+psycopg://owner")
    assert HistoryConfig.from_env(for_write=True).dsn.startswith("postgresql+psycopg://writer")


def test_multirecord_dataset_checksum_is_stable_and_validates_after_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = list(generate_cases(count=24, seed=311, as_of_date=date(2026, 11, 22)))
    assert [case.application_id for case in cases] == sorted(case.application_id for case in cases)
    manifest = build_manifest(
        dataset_id="ordered-multi-case",
        count=len(cases),
        seed=311,
        as_of_date=date(2026, 11, 22),
        history_months=36,
    )
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    stored = writer.write_dataset(manifest, cases, batch_size=5)
    reader = PostgresHistoryStore(engine=engine, read_only=True)
    restored = list(reader.iter_cases("ordered-multi-case", batch_size=7))
    assert len(restored) == len(cases)
    monkeypatch.setattr(validate_history_dataset, "create_history_source", lambda: reader)
    result = validate_history_dataset.validate("ordered-multi-case")
    assert result["checksum_verified"] is True
    assert result["data_sha256"] == stored.data_sha256
    assert result["target_name"] == "FSTPD30"
    assert result["matured_outcomes_by_target"]["FSTPD30"] == result["matured_outcomes"]
    reader.close()
    writer.close()


def test_fstpd30_validator_checks_payment_level_label_consistency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = list(generate_cases(count=200, seed=919, as_of_date=date(2026, 11, 22)))
    target_index = next(
        index
        for index, case in enumerate(cases)
        if case.outcome_snapshot and case.outcome_snapshot.get("outcome_status") == "MATURED"
    )
    selected = cases[target_index]
    altered_outcome = dict(selected.outcome_snapshot or {})
    altered_outcome["FSTPD30"] = 1 - int(altered_outcome["FSTPD30"])
    cases[target_index] = replace(selected, outcome_snapshot=altered_outcome)

    manifest = build_manifest(
        dataset_id="fstpd30-invalid-payment-label",
        count=len(cases),
        seed=919,
        as_of_date=date(2026, 11, 22),
        history_months=36,
    )
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    writer.write_dataset(manifest, cases, batch_size=40)
    reader = PostgresHistoryStore(engine=engine, read_only=True)
    monkeypatch.setattr(validate_history_dataset, "create_history_source", lambda: reader)
    with pytest.raises(ValueError, match="FSTPD30 does not match payment-level DPD values"):
        validate_history_dataset.validate("fstpd30-invalid-payment-label")
    reader.close()
    writer.close()


def test_dataset_writer_rejects_unordered_cases() -> None:
    cases = list(generate_cases(count=3, seed=77, as_of_date=date(2026, 11, 22)))
    manifest = build_manifest(
        dataset_id="unordered-cases",
        count=len(cases),
        seed=77,
        as_of_date=date(2026, 11, 22),
    )
    engine = create_engine("sqlite:///:memory:")
    writer = PostgresHistoryStore(engine=engine, read_only=False)
    writer.initialize()
    with pytest.raises(Exception, match="strictly increasing application_id order"):
        writer.write_dataset(manifest, [cases[1], cases[0], cases[2]])
    writer.close()


def test_recorded_decision_snapshot_is_versioned_and_point_in_time() -> None:
    from dataclasses import replace

    case = _case()
    recorded = {
        "application_id": case.application_id,
        "decision_timestamp": case.decision_timestamp,
        "decision": "APPROVED",
        "policy_version": "UW-POLICY-2026-01",
        "runtime_release": "2.0.0",
        "runtime_manifest_sha256": "a" * 64,
        "model_version": "AIDFLOW-1.0",
        "source_snapshot_ids": {"bureau": "BUR-1", "telco_stability": "SRC-1"},
    }
    recorded_case = replace(case, recorded_decision_snapshot=recorded)
    assert recorded_case.to_dict()["recorded_decision_snapshot"] == recorded
    assert recorded_case.case_schema_version == 2

    with pytest.raises(ValueError, match="must match application_id"):
        replace(case, recorded_decision_snapshot={**recorded, "application_id": "SYN-OTHER"})
    with pytest.raises(ValueError, match="must match the original decision_timestamp"):
        replace(
            case,
            recorded_decision_snapshot={**recorded, "decision_timestamp": "2026-01-01T10:01:00Z"},
        )


def test_parquet_adapter_roundtrips_optional_recorded_decision_snapshot(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    from uwflow_history.connectors.parquet import ParquetHistoryStore

    case = replace(
        _case(),
        recorded_decision_snapshot={
            "application_id": "SYN-1",
            "decision_timestamp": "2026-01-01T10:00:00Z",
            "decision": "REFER",
            "policy_version": "UW-POLICY-2026-01",
            "source_snapshot_ids": {"bureau": "BUR-1"},
        },
    )
    writer = ParquetHistoryStore(tmp_path, read_only=False)
    writer.write_dataset(_manifest(), [case])
    reader = ParquetHistoryStore(tmp_path, read_only=True)
    read_case = next(reader.iter_cases("test-history"))
    assert read_case.recorded_decision_snapshot == case.recorded_decision_snapshot


def test_historical_case_rejects_unsupported_schema_version() -> None:
    current = _case().to_dict()
    current["case_schema_version"] = 1
    with pytest.raises(ValueError, match="Unsupported historical case schema version"):
        HistoricalCase.from_dict(current)


def test_historical_case_requires_explicit_schema_version() -> None:
    current = _case().to_dict()
    current.pop("case_schema_version")
    with pytest.raises(ValueError, match="missing required case_schema_version"):
        HistoricalCase.from_dict(current)


def test_dataset_manifest_rejects_unsupported_case_schema_version() -> None:
    manifest = _manifest().to_dict()
    manifest["case_schema_version"] = 1
    with pytest.raises(ValueError, match="Unsupported historical case schema version"):
        DatasetManifest.from_dict(manifest)


def test_dataset_manifest_requires_explicit_schema_versions() -> None:
    manifest = _manifest().to_dict()
    manifest.pop("case_schema_version")
    with pytest.raises(ValueError, match="missing required schema fields"):
        DatasetManifest.from_dict(manifest)
