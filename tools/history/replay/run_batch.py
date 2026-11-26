"""Run one pinned UWflow runtime over a bounded batch of historical snapshots.

Kestra invokes this same vendor-neutral command once for the baseline bundle and
once for the candidate bundle. The process loads exactly one runtime root, so
Python module caching cannot mix baseline and candidate implementations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


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

from uwflow_history.factory import create_history_source  # noqa: E402
from uwflow_history.contracts import HistoricalCase  # noqa: E402


class HistoryReplayError(RuntimeError):
    """Raised when a historical batch cannot be safely evaluated."""


def verify_runtime_bundle(
    runtime_root: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify that a local replay runtime matches its immutable release manifest."""
    runtime_root = runtime_root.resolve()
    manifest_path = runtime_root / "release-manifest.json"
    if not manifest_path.is_file():
        raise HistoryReplayError(f"Runtime manifest is missing: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 and manifest_sha256 != expected_manifest_sha256:
        raise HistoryReplayError(
            "Runtime manifest differs from the SHA-256 pinned by the DEV replay flow"
        )
    manifest = json.loads(manifest_bytes)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise HistoryReplayError("Runtime manifest has no file checksum map")
    for name, expected_sha in files.items():
        relative = Path(str(name))
        if relative.is_absolute() or ".." in relative.parts:
            raise HistoryReplayError(f"Unsafe runtime manifest path: {name}")
        path = (runtime_root / relative).resolve()
        if not path.is_relative_to(runtime_root):
            raise HistoryReplayError(f"Runtime manifest path escapes its bundle: {name}")
        if not path.is_file():
            raise HistoryReplayError(f"Runtime module is missing: {path}")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise HistoryReplayError(f"Runtime checksum mismatch for {name}")
    return {
        "runtime_release": str(manifest.get("release_version", runtime_root.name)),
        "runtime_source_ref": str(manifest.get("source_ref", "UNKNOWN")),
        "runtime_manifest_sha256": manifest_sha256,
        "runtime_module_count": len(files),
    }


def load_runtime(
    runtime_root: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Load one pinned runtime bundle into this process."""
    runtime_root = runtime_root.resolve()
    if not runtime_root.is_dir():
        raise HistoryReplayError(f"Runtime directory does not exist: {runtime_root}")
    metadata = verify_runtime_bundle(
        runtime_root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if str(runtime_root) in sys.path:
        sys.path.remove(str(runtime_root))
    sys.path.insert(0, str(runtime_root))

    # A process normally loads one runtime. Removing these names also makes the
    # helper deterministic when called repeatedly from a unit test.
    for name in (
        "common",
        "policy_generated",
        "hard_gates",
        "bureau_client",
        "alternative_data",
        "aidflow_scoring",
        "uwflow_engine",
    ):
        sys.modules.pop(name, None)

    import importlib

    modules = {
        "hard_gates": importlib.import_module("hard_gates"),
        "bureau_client": importlib.import_module("bureau_client"),
        "policy_generated": importlib.import_module("policy_generated"),
        "aidflow_scoring": importlib.import_module("aidflow_scoring"),
        "uwflow_engine": importlib.import_module("uwflow_engine"),
    }
    return {**metadata, "modules": modules}


def _unavailable_bureau(
    application_id: str,
    recorded_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Missing/failed historical bureau evidence must never be interpreted as a
    # pass. REFER is the fail-closed outcome understood by the existing engine.
    original_reasons = (recorded_snapshot or {}).get("reason_codes", [])
    reasons = ["HISTORICAL_BUREAU_SNAPSHOT_UNAVAILABLE"]
    if isinstance(original_reasons, list):
        reasons.extend(str(item) for item in original_reasons if isinstance(item, str))
    return {
        "stage": "CREDIT_BUREAU",
        "status": "UNAVAILABLE",
        "decision_status": "REFER",
        "passed": False,
        "applicant_id": application_id,
        "bureau_score": None,
        "reason_codes": list(dict.fromkeys(reasons)),
        "historical_snapshot_missing": True,
        "historical_snapshot_id": (recorded_snapshot or {}).get("snapshot_id"),
    }


def _validated_bureau_snapshot(case: HistoricalCase) -> tuple[dict[str, Any], bool]:
    snapshot = case.bureau_snapshot
    if snapshot is None:
        return _unavailable_bureau(case.application_id), False

    snapshot = dict(snapshot)
    recorded_applicant_id = snapshot.get("applicant_id")
    if recorded_applicant_id is not None and recorded_applicant_id != case.application_id:
        raise HistoryReplayError(
            f"Historical bureau snapshot applicant_id does not match {case.application_id}"
        )
    snapshot.setdefault("applicant_id", case.application_id)
    if snapshot.get("status") in {"FAILED", "UNAVAILABLE", "ERROR", "TIMEOUT", "NOT_FOUND"}:
        return _unavailable_bureau(case.application_id, snapshot), False
    if snapshot.get("status") != "SUCCESS":
        raise HistoryReplayError(
            f"Historical bureau snapshot for {case.application_id} has an unsupported status"
        )
    decision_status = snapshot.get("decision_status")
    if decision_status not in {"PASS", "REFER", "DECLINE"}:
        raise HistoryReplayError(
            f"Historical bureau snapshot for {case.application_id} has unsupported decision_status"
        )
    reason_codes = snapshot.get("reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(item, str) for item in reason_codes
    ):
        raise HistoryReplayError(
            f"Historical bureau snapshot for {case.application_id} must contain string reason_codes"
        )
    try:
        reported_debt = float(snapshot["reported_monthly_debt_payments"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoryReplayError(
            f"Historical bureau snapshot for {case.application_id} is missing normalized reported_monthly_debt_payments"
        ) from exc
    if not math.isfinite(reported_debt) or reported_debt < 0:
        raise HistoryReplayError(
            f"Historical bureau reported_monthly_debt_payments is invalid for {case.application_id}"
        )
    if "passed" in snapshot and bool(snapshot["passed"]) != (decision_status == "PASS"):
        raise HistoryReplayError(
            f"Historical bureau passed flag conflicts with decision_status for {case.application_id}"
        )
    return snapshot, True


def _stage(outcome: str, *, reached: bool, **details: Any) -> dict[str, Any]:
    return {"outcome": outcome, "reached": reached, **details}


def _final_replay_row(
    case: HistoricalCase,
    *,
    decision: dict[str, Any],
    gates: dict[str, Any],
    bureau: dict[str, Any],
    aidflow: dict[str, Any],
    source_plan: dict[str, Any],
    source_results: list[dict[str, Any]],
    stage_results: dict[str, dict[str, Any]],
    bureau_snapshot_used: bool,
) -> dict[str, Any]:
    return {
        "application_id": case.application_id,
        "application_snapshot_id": case.application_snapshot_id,
        "application_timestamp": case.application_timestamp,
        "decision_timestamp": case.decision_timestamp,
        "decision": decision.get("decision"),
        "decision_status": decision.get("decision_status"),
        "profile_score": decision.get("complex_customer_profile_score"),
        "approved_amount": decision.get("approved_amount"),
        "offered_apr_percent": decision.get("offered_apr_percent"),
        "risk_tier": decision.get("risk_tier"),
        "reason_codes": decision.get("reason_codes", []),
        "hard_gate_passed": bool(gates.get("passed", False)),
        "hard_gate_reason_codes": gates.get("reason_codes", []),
        "hard_gate_trace": gates.get("policy_trace", []),
        "bureau_status": bureau.get("status"),
        "bureau_decision_status": bureau.get("decision_status"),
        "bureau_reason_codes": bureau.get("reason_codes", []),
        "bureau_snapshot_missing": bool(bureau.get("historical_snapshot_missing", False)),
        "bureau_snapshot_used": bureau_snapshot_used,
        "bureau_snapshot_id": bureau.get("snapshot_id") if bureau_snapshot_used else None,
        "bureau_score": bureau.get("bureau_score") if bureau_snapshot_used else None,
        "bureau_historical_defaults_5y": bureau.get("historical_defaults_5y"),
        "bureau_historical_delinquencies_24m": bureau.get("historical_delinquencies_24m"),
        "bureau_open_loans": bureau.get("open_loans"),
        "source_plan_action": source_plan.get("action"),
        "source_plan_ids": source_plan.get("source_ids", []),
        "source_plan_trace": source_plan.get("trace", []),
        "source_snapshot_count_available": len(case.alternative_data_snapshots),
        "source_result_count_used": len(source_results),
        "aidflow_status": aidflow.get("scoring_status"),
        "aidflow_input_scores": aidflow.get("input_scores", []),
        "segments": case.segments,
        "stage_results": stage_results,
        "outcome": case.outcome_snapshot,
        "recorded_decision_snapshot": case.recorded_decision_snapshot,
    }


def evaluate_case(case: HistoricalCase, runtime: dict[str, Any]) -> dict[str, Any]:
    """Replay one application and retain an analyst-readable outcome at each stage.

    Stage outcomes represent the business funnel, not merely whether a Kestra
    task container started. An upstream rejection therefore marks downstream
    stages NOT_REACHED even where the live Kestra DAG executes a no-op task.
    """
    modules = runtime["modules"]
    application = dict(case.application)
    outcome = case.outcome_snapshot or {}
    withdrawal_stage = outcome.get("synthetic_withdrawal_stage")
    stage_results: dict[str, dict[str, Any]] = {
        "stage1_hard_gates": _stage("NOT_REACHED", reached=False),
        "stage2_bureau": _stage("NOT_REACHED", reached=False),
        "stage3_source_plan": _stage("NOT_REACHED", reached=False),
        "stage4_data_collection": _stage("NOT_REACHED", reached=False),
        "stage5_aidflow": _stage("NOT_REACHED", reached=False),
        "stage6_uwflow": _stage("NOT_REACHED", reached=False),
    }

    def cancelled_result(
        cancelled_stage: str,
        gates: dict[str, Any],
        bureau: dict[str, Any],
        aidflow: dict[str, Any],
        source_plan: dict[str, Any],
        source_results: list[dict[str, Any]],
        bureau_snapshot_used: bool,
    ) -> dict[str, Any]:
        stage_results[cancelled_stage] = _stage(
            "CANCELLED", reached=True, reason="SYNTHETIC_OR_RECORDED_APPLICATION_WITHDRAWAL"
        )
        decision = {
            "decision": "CANCELLED",
            "decision_status": "WITHDRAWN",
            "complex_customer_profile_score": aidflow.get("complex_customer_profile_score"),
            "approved_amount": 0.0,
            "reason_codes": ["APPLICATION_WITHDRAWN"],
            "risk_tier": "NOT_ASSESSED",
        }
        return _final_replay_row(
            case,
            decision=decision,
            gates=gates,
            bureau=bureau,
            aidflow=aidflow,
            source_plan=source_plan,
            source_results=source_results,
            stage_results=stage_results,
            bureau_snapshot_used=bureau_snapshot_used,
        )

    empty_plan = {
        "action": "SKIP_SOURCE_COLLECTION",
        "source_ids": [],
        "loop_values": [],
        "planned_count": 0,
        "reason": "NOT_REACHED",
        "trace": [],
    }
    empty_bureau = {
        "stage": "CREDIT_BUREAU",
        "status": "SKIPPED",
        "decision_status": "NOT_ASSESSED",
        "passed": False,
        "applicant_id": case.application_id,
        "reason_codes": ["NOT_REACHED_AFTER_UPSTREAM_STOP"],
        "historical_snapshot_missing": False,
    }
    empty_aidflow = modules["aidflow_scoring"].score_customer_profile([])

    # A withdrawal before the first gate is retained as an explicit funnel exit.
    if withdrawal_stage == "STAGE_1_HARD_GATES":
        gates = {
            "passed": False,
            "status": "CANCELLED",
            "reason_codes": ["APPLICATION_WITHDRAWN"],
            "policy_trace": [],
        }
        stage_results["stage1_hard_gates"] = _stage("CANCELLED", reached=True)
        return cancelled_result(
            "stage1_hard_gates", gates, empty_bureau, empty_aidflow, empty_plan, [], False
        )

    gates = modules["hard_gates"].evaluate_hard_gates(application)
    stage_results["stage1_hard_gates"] = _stage(
        "PASSED" if gates.get("passed", False) else "REJECTED",
        reached=True,
        reason_codes=gates.get("reason_codes", []),
        checks=gates.get("checks", []),
    )

    # The production Kestra flow may still invoke the final-decision task to
    # emit a consistent response, but the business decision funnel did not
    # reach Stage 6. Attribute the rejection to Stage 1 only.
    if not gates.get("passed", False):
        decision = modules["uwflow_engine"].run_uwflow_decision(
            application,
            gates,
            empty_bureau,
            empty_aidflow,
            [],
        )
        return _final_replay_row(
            case,
            decision=decision,
            gates=gates,
            bureau=empty_bureau,
            aidflow=empty_aidflow,
            source_plan=empty_plan,
            source_results=[],
            stage_results=stage_results,
            bureau_snapshot_used=False,
        )

    if withdrawal_stage == "STAGE_2_BUREAU":
        stage_results["stage2_bureau"] = _stage("CANCELLED", reached=True)
        return cancelled_result(
            "stage2_bureau", gates, empty_bureau, empty_aidflow, empty_plan, [], False
        )

    bureau_snapshot_used = False
    bureau, bureau_snapshot_used = _validated_bureau_snapshot(case)
    bureau_status = str(bureau.get("decision_status", "REFER"))
    bureau_outcome = {"PASS": "PASSED", "DECLINE": "REJECTED", "REFER": "REFERRED"}.get(
        bureau_status, "REFERRED"
    )
    stage_results["stage2_bureau"] = _stage(
        bureau_outcome,
        reached=True,
        reason_codes=bureau.get("reason_codes", []),
        bureau_score=bureau.get("bureau_score"),
        historical_defaults_5y=bureau.get("historical_defaults_5y"),
        historical_delinquencies_24m=bureau.get("historical_delinquencies_24m"),
        open_loans=bureau.get("open_loans"),
    )

    if bureau_status == "DECLINE":
        # Bureau rejection is attributed to Stage 2. The final decision task
        # can still render the response, but Stage 6 is not a reached funnel stage.
        decision = modules["uwflow_engine"].run_uwflow_decision(
            application,
            gates,
            bureau,
            empty_aidflow,
            [],
        )
        return _final_replay_row(
            case,
            decision=decision,
            gates=gates,
            bureau=bureau,
            aidflow=empty_aidflow,
            source_plan=empty_plan,
            source_results=[],
            stage_results=stage_results,
            bureau_snapshot_used=bureau_snapshot_used,
        )

    if withdrawal_stage == "STAGE_3_SOURCE_PLAN":
        stage_results["stage3_source_plan"] = _stage("CANCELLED", reached=True)
        return cancelled_result(
            "stage3_source_plan", gates, bureau, empty_aidflow, empty_plan, [], bureau_snapshot_used
        )

    source_plan = modules["policy_generated"].build_stage3_source_plan(
        {
            "hard_gates_passed": True,
            "bureau_decision_status": bureau_status,
            "data_sharing_consent": bool(application.get("data_sharing_consent", False)),
        }
    )
    source_plan_action = str(source_plan.get("action"))
    collecting = source_plan_action == "COLLECT_SOURCES"
    stage3_outcome = "ROUTED_TO_COLLECTION" if collecting else "SKIPPED_NO_CONSENT"
    stage_results["stage3_source_plan"] = _stage(
        stage3_outcome,
        reached=True,
        action=source_plan_action,
        reason=source_plan.get("reason"),
        trace=source_plan.get("trace", []),
    )

    if withdrawal_stage == "STAGE_4_DATA_COLLECTION" and collecting:
        stage_results["stage4_data_collection"] = _stage("CANCELLED", reached=True)
        return cancelled_result(
            "stage4_data_collection",
            gates,
            bureau,
            empty_aidflow,
            source_plan,
            [],
            bureau_snapshot_used,
        )

    normalized_sources: list[dict[str, Any]] = []
    for source in case.alternative_data_snapshots:
        normalized = dict(source)
        recorded_applicant_id = normalized.get("applicant_id")
        if recorded_applicant_id is not None and recorded_applicant_id != case.application_id:
            raise HistoryReplayError(
                f"Historical source snapshot {source.get('source_id')} applicant_id does not match {case.application_id}"
            )
        normalized.setdefault("applicant_id", case.application_id)
        normalized_sources.append(normalized)

    available = {
        str(item.get("source_id")): item for item in normalized_sources if item.get("source_id")
    }
    source_ids = list(source_plan.get("source_ids", []))
    source_results = [available[source_id] for source_id in source_ids if source_id in available]
    source_statuses = {
        source_id: (
            "MISSING"
            if source_id not in available
            else "SUCCESS"
            if available[source_id].get("status") == "SUCCESS"
            else "FAILED"
        )
        for source_id in source_ids
    }
    successful_sources = sum(value == "SUCCESS" for value in source_statuses.values())
    if not collecting:
        stage4_outcome = "SKIPPED_NO_CONSENT"
    elif successful_sources == len(source_ids) == 10:
        stage4_outcome = "COMPLETE"
    elif successful_sources > 0:
        stage4_outcome = "PARTIAL"
    else:
        stage4_outcome = "FAILED"
    stage_results["stage4_data_collection"] = _stage(
        stage4_outcome,
        reached=True,
        planned_source_count=len(source_ids),
        successful_source_count=successful_sources,
        source_outcomes=source_statuses,
    )

    if withdrawal_stage == "STAGE_5_AIDFLOW":
        stage_results["stage5_aidflow"] = _stage("CANCELLED", reached=True)
        return cancelled_result(
            "stage5_aidflow",
            gates,
            bureau,
            empty_aidflow,
            source_plan,
            source_results,
            bureau_snapshot_used,
        )

    aidflow = modules["aidflow_scoring"].score_customer_profile(source_results)
    stage5_outcome = "SCORED" if aidflow.get("scoring_status") == "SCORED" else "INCOMPLETE"
    stage_results["stage5_aidflow"] = _stage(
        stage5_outcome,
        reached=True,
        scoring_status=aidflow.get("scoring_status"),
        profile_score=aidflow.get("complex_customer_profile_score"),
        input_score_count=aidflow.get("input_score_count", 0),
        expected_input_count=aidflow.get("expected_input_count", 10),
        missing_source_ids=aidflow.get("missing_source_ids", []),
    )

    if withdrawal_stage == "STAGE_6_UWFLOW":
        stage_results["stage6_uwflow"] = _stage("CANCELLED", reached=True)
        return cancelled_result(
            "stage6_uwflow",
            gates,
            bureau,
            aidflow,
            source_plan,
            source_results,
            bureau_snapshot_used,
        )

    decision = modules["uwflow_engine"].run_uwflow_decision(
        application,
        gates,
        bureau,
        aidflow,
        source_results,
    )
    decision_outcome = {
        "APPROVED": "APPROVED",
        "COUNTEROFFER": "COUNTEROFFER",
        "REFER": "REFERRED",
        "DECLINED": "REJECTED",
        "CANCELLED": "CANCELLED",
    }.get(str(decision.get("decision")), "REJECTED")
    stage_results["stage6_uwflow"] = _stage(
        decision_outcome,
        reached=True,
        reason_codes=decision.get("reason_codes", []),
        approved_amount=decision.get("approved_amount", 0.0),
        offered_apr_percent=decision.get("offered_apr_percent"),
        risk_tier=decision.get("risk_tier"),
    )
    return _final_replay_row(
        case,
        decision=decision,
        gates=gates,
        bureau=bureau,
        aidflow=aidflow,
        source_plan=source_plan,
        source_results=source_results,
        stage_results=stage_results,
        bureau_snapshot_used=bureau_snapshot_used,
    )


def run_batch(
    *,
    dataset_id: str,
    runtime_root: Path,
    output_path: Path,
    batch_size: int = 2000,
    offset: int = 0,
    max_cases: int | None = None,
) -> dict[str, Any]:
    """Run a deterministic batch of historical applications through the selected Core runtime."""
    if not 1 <= batch_size <= 10_000:
        raise HistoryReplayError("batch_size must be between 1 and 10000")
    if offset < 0:
        raise HistoryReplayError("offset must be non-negative")
    if max_cases is not None and max_cases < 0:
        raise HistoryReplayError("max_cases must be zero (all cases) or a positive integer")
    runtime = load_runtime(
        runtime_root,
        expected_manifest_sha256=os.getenv("UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"),
    )
    source = create_history_source()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        manifest = source.get_manifest(dataset_id)
        if not manifest.data_sha256:
            raise HistoryReplayError(
                "Dataset manifest has no content checksum; run dataset validation and recreate the snapshot"
            )
        with output_path.open("w", encoding="utf-8") as handle:
            for case in source.iter_cases(
                dataset_id,
                batch_size=batch_size,
                offset=offset,
                limit=None if max_cases is None or max_cases <= 0 else max_cases,
            ):
                result = evaluate_case(case, runtime)
                result["dataset_id"] = dataset_id
                result["dataset_sha256"] = manifest.data_sha256
                result["runtime_release"] = runtime["runtime_release"]
                result["runtime_manifest_sha256"] = runtime["runtime_manifest_sha256"]
                handle.write(
                    json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
                )
                count += 1
        if count == 0:
            raise HistoryReplayError("No historical cases were selected for replay")
        metadata = {
            "dataset_id": dataset_id,
            "dataset_sha256": manifest.data_sha256,
            "dataset_case_count": manifest.case_count,
            "batch_offset": offset,
            "batch_count": count,
            "runtime_release": runtime["runtime_release"],
            "runtime_source_ref": runtime["runtime_source_ref"],
            "runtime_manifest_sha256": runtime["runtime_manifest_sha256"],
            "output_file": output_path.name,
            "history_connector": os.getenv("UWFLOW_HISTORY_CONNECTOR", "postgres"),
        }
        metadata_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return metadata
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()


def main() -> int:
    """Execute a historical batch replay and write case-level outputs and metadata."""
    parser = argparse.ArgumentParser(
        description="Replay a historical dataset batch on one pinned runtime"
    )
    parser.add_argument("--dataset-id", default=os.getenv("UWFLOW_HISTORY_DATASET_ID"))
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=os.getenv("UWFLOW_HISTORY_RUNTIME_ROOT"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path(os.getenv("UWFLOW_HISTORY_OUTPUT", "batch.jsonl"))
    )
    parser.add_argument(
        "--batch-size", type=int, default=os.getenv("UWFLOW_HISTORY_BATCH_SIZE", "2000")
    )
    parser.add_argument("--offset", type=int, default=os.getenv("UWFLOW_HISTORY_OFFSET", "0"))
    parser.add_argument(
        "--max-cases",
        type=int,
        default=os.getenv("UWFLOW_HISTORY_MAX_CASES"),
        help="Optional smoke-test limit; 0 means all",
    )
    args = parser.parse_args()
    if not args.dataset_id:
        parser.error("--dataset-id or UWFLOW_HISTORY_DATASET_ID is required")
    if args.runtime_root is None:
        parser.error("--runtime-root or UWFLOW_HISTORY_RUNTIME_ROOT is required")
    try:
        metadata = run_batch(
            dataset_id=args.dataset_id,
            runtime_root=args.runtime_root,
            output_path=args.output,
            batch_size=args.batch_size,
            offset=args.offset,
            max_cases=args.max_cases,
        )
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
