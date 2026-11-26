"""Validate dataset manifest, row count, content digest and temporal boundaries."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
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

from uwflow_history.canonical import update_case_digest  # noqa: E402
from uwflow_history.factory import create_history_source  # noqa: E402


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(dataset_id: str, *, verify_checksum: bool = True) -> dict:
    """Validate a dataset manifest, digest and case count against stored evidence."""
    source = create_history_source()
    try:
        manifest = source.get_manifest(dataset_id)
        digest = hashlib.sha256()
        count = 0
        history_start = _parse(manifest.history_start)
        history_end = _parse(manifest.history_end)
        as_of = _parse(manifest.as_of_timestamp)
        matured = 0
        immature = 0
        matured_targets: dict[str, int] = {}
        for case in source.iter_cases(dataset_id, batch_size=2000):
            count += 1
            application_at = _parse(case.application_timestamp)
            decision_at = _parse(case.decision_timestamp)
            if application_at < history_start or application_at > history_end:
                raise ValueError(
                    f"Application snapshot is outside the dataset history window: {case.application_id}"
                )
            if decision_at < application_at:
                raise ValueError(f"Application timestamp is after decision: {case.application_id}")
            if decision_at > as_of:
                raise ValueError(
                    f"Decision timestamp is after dataset as-of time: {case.application_id}"
                )
            if case.bureau_snapshot:
                retrieved = case.bureau_snapshot.get("retrieved_at")
                if retrieved and _parse(str(retrieved)) > decision_at:
                    raise ValueError(f"Bureau snapshot is post-decision: {case.application_id}")
            for snapshot in case.alternative_data_snapshots:
                retrieved = snapshot.get("retrieved_at")
                if retrieved and _parse(str(retrieved)) > decision_at:
                    raise ValueError(
                        f"Alternative-data snapshot {snapshot.get('source_id')} is post-decision: {case.application_id}"
                    )
            if case.outcome_snapshot:
                observed = case.outcome_snapshot.get("observed_at")
                observed_at = _parse(str(observed)) if observed else None
                if observed_at and observed_at < decision_at:
                    raise ValueError(f"Outcome timestamp precedes decision: {case.application_id}")
                if observed_at and observed_at > as_of:
                    raise ValueError(
                        f"Outcome timestamp is after dataset as-of time: {case.application_id}"
                    )
                if case.outcome_snapshot.get("outcome_status") == "MATURED":
                    matured += 1
                    outcome = case.outcome_snapshot
                    target_name = str(
                        outcome.get("target_name")
                        or manifest.metadata.get("target_name")
                        or ("default_12m" if "default_12m" in outcome else "")
                    )
                    if target_name == "FSTPD30":
                        target = outcome.get("FSTPD30")
                        if not isinstance(target, (bool, int)) or int(target) not in (0, 1):
                            raise ValueError(
                                f"Matured FSTPD30 outcome requires a binary 0/1 label: {case.application_id}"
                            )
                        payment_dpd = (
                            outcome.get("first_payment_days_past_due"),
                            outcome.get("second_payment_days_past_due"),
                            outcome.get("third_payment_days_past_due"),
                        )
                        if any(not isinstance(value, int) or value < 0 for value in payment_dpd):
                            raise ValueError(
                                f"Matured FSTPD30 outcome requires three non-negative payment DPD values: {case.application_id}"
                            )
                        expected = int(any(value >= 30 for value in payment_dpd))
                        if int(target) != expected:
                            raise ValueError(
                                f"FSTPD30 does not match payment-level DPD values: {case.application_id}"
                            )
                    elif target_name == "default_12m":
                        if not isinstance(outcome.get("default_12m"), bool):
                            raise ValueError(
                                f"Matured outcome requires a boolean default_12m label: {case.application_id}"
                            )
                    else:
                        raise ValueError(
                            f"Matured outcome has no supported target label (target_name={target_name!r}): {case.application_id}"
                        )
                    matured_targets[target_name] = matured_targets.get(target_name, 0) + 1
                else:
                    immature += 1
            update_case_digest(digest, case.to_dict())
        if count != manifest.case_count:
            raise ValueError(
                f"Manifest has {manifest.case_count} cases, connector returned {count}"
            )
        actual_digest = digest.hexdigest()
        if verify_checksum and manifest.data_sha256 != actual_digest:
            raise ValueError(
                f"Dataset content checksum mismatch: expected {manifest.data_sha256}, got {actual_digest}"
            )
        return {
            "dataset_id": dataset_id,
            "case_count": count,
            "data_sha256": actual_digest,
            "checksum_verified": bool(verify_checksum),
            "matured_outcomes": matured,
            "matured_outcomes_by_target": dict(sorted(matured_targets.items())),
            "immature_outcomes": immature,
            "target_name": manifest.metadata.get("target_name"),
            "synthetic": manifest.synthetic,
            "source_snapshot_semantics": manifest.source_snapshot_semantics,
            "status": "VALID",
        }
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()


def main() -> int:
    """Validate the selected historical dataset from the command line."""
    parser = argparse.ArgumentParser(description="Validate a point-in-time UWflow dataset")
    parser.add_argument("--dataset-id", default=os.getenv("UWFLOW_HISTORY_DATASET_ID"))
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--skip-checksum", action="store_true")
    args = parser.parse_args()
    if not args.dataset_id:
        parser.error("--dataset-id or UWFLOW_HISTORY_DATASET_ID is required")
    try:
        result = validate(args.dataset_id, verify_checksum=not args.skip_checksum)
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
