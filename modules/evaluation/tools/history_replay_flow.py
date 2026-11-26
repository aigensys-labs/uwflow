"""Generate a manual DEV Kestra flow for paired historical baseline/candidate replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import re
import tomllib

import yaml

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)

from modules.history.tools.history_tools_bundle import build_bundle
from tools.kestra.yaml import dump_kestra_yaml


def _manifest_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_core_runtime_snapshot(snapshot: Path, release_version: str) -> dict:
    """Verify one exact Core-owned runtime snapshot; never search alternate paths."""
    manifest_path = snapshot / "release-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Core runtime snapshot manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("artifact_type") != "uwflow-kestra-runtime"
        or manifest.get("manifest_format") != 1
        or manifest.get("release_version") != release_version
    ):
        raise ValueError(f"Core runtime snapshot identity/format mismatch: {snapshot}")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError(f"Core runtime snapshot has no file checksum map: {snapshot}")
    root = snapshot.resolve()
    if not root.is_relative_to(snapshot.parent.resolve()):
        raise ValueError(
            f"Core runtime snapshot escapes its declared release directory: {snapshot}"
        )
    declared = set()
    for relative, expected in files.items():
        rel = PurePosixPath(str(relative))
        if (
            rel.is_absolute()
            or not rel.parts
            or any(part in {"", ".", ".."} for part in rel.parts)
            or "\\" in str(relative)
        ):
            raise ValueError(f"Unsafe path in Core runtime manifest: {relative!r}")
        path = (root / Path(*rel.parts)).resolve()
        if not path.is_relative_to(root) or not path.is_file() or _manifest_sha(path) != expected:
            raise ValueError(f"Core runtime snapshot checksum mismatch: {relative}")
        declared.add(rel.as_posix())
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "release-manifest.json"
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix != ".pyc"
    }
    if actual != declared:
        raise ValueError(
            "Core runtime snapshot file set does not match its manifest: "
            f"unexpected={sorted(actual - declared)}, missing={sorted(declared - actual)}"
        )
    return manifest


def build_flow(
    candidate_id: str,
    baseline_release: str,
    *,
    parquet_host_root: Path | None = None,
    image_reference: str | None = None,
    repository_root: Path | str | None = None,
) -> Path:
    """Build a paired Kestra replay flow for one verified candidate and baseline release."""
    root = Path(repository_root).resolve() if repository_root is not None else ROOT
    if not re.fullmatch(r"dev-[0-9a-f]{16}", candidate_id):
        raise ValueError(
            "candidate_id must be a content-addressed dev-<16 lowercase hex> identifier"
        )
    if not re.fullmatch(r"\d+\.\d+\.\d+", baseline_release):
        raise ValueError("baseline_release must be a semantic MAJOR.MINOR.PATCH version")
    candidate_root = root / "var" / "artifacts" / "candidates" / candidate_id
    approved_root = root / "var" / "releases" / "approved" / baseline_release
    core_baseline_root = (
        root / "core" / "kestra" / "namespace-files" / "runtime" / "releases" / baseline_release
    )
    from modules.lifecycle.workspaces import WorkspaceError, WorkspaceStore

    store = WorkspaceStore(root)
    try:
        candidate_root, candidate_manifest, _candidate_manifest_bytes = store._verify_candidate(
            candidate_id
        )
    except WorkspaceError as exc:
        raise ValueError(f"Candidate is not a complete verified v2 artifact: {exc}") from exc
    candidate_parent = candidate_manifest.get("based_on_production_release")
    if candidate_parent != baseline_release:
        raise ValueError(
            f"Candidate was built from baseline {candidate_parent!r}, not {baseline_release!r}; "
            "rebuild the candidate from the intended frozen baseline before replay."
        )

    if approved_root.exists() or approved_root.is_symlink():
        try:
            approved_source, _approved_manifest, _approved_manifest_bytes = (
                store._verify_approved_release(baseline_release)
            )
        except WorkspaceError as exc:
            raise ValueError(
                f"Approved baseline {baseline_release} is not a complete verified release: {exc}"
            ) from exc
        baseline_root = approved_source / "runtime"
        production_flow_path = approved_source / "production-flow.yaml"
    elif core_baseline_root.is_dir():
        # Explicit Core-owned bootstrap/reference baseline before the first governed v2 release.
        baseline_root = core_baseline_root
        baseline_manifest = _verify_core_runtime_snapshot(baseline_root, baseline_release)
        production_flow_path = (
            root / "core" / "kestra" / "flows" / "uwflow_production_underwriting.yaml"
        )
    else:
        raise FileNotFoundError(
            f"Baseline {baseline_release} is neither an approved release nor a checked-in Core runtime snapshot"
        )
    if not (baseline_root / "release-manifest.json").is_file():
        raise FileNotFoundError(f"Baseline runtime manifest not found: {baseline_root}")
    if approved_root.exists() or approved_root.is_symlink():
        baseline_manifest = json.loads(
            (baseline_root / "release-manifest.json").read_text(encoding="utf-8")
        )
    if baseline_manifest.get("artifact_type") != "uwflow-kestra-runtime":
        raise ValueError("Baseline path does not contain a UWflow runtime bundle")
    if baseline_manifest.get("release_version") != baseline_release:
        raise ValueError("Baseline manifest release_version does not match its directory")
    if not production_flow_path.is_file():
        raise FileNotFoundError(f"Baseline production flow is missing: {production_flow_path}")
    tools_id, _ = build_bundle(repository_root=root)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    project_version = str(project["version"])
    production_flow = yaml.safe_load(production_flow_path.read_text(encoding="utf-8"))
    production_python_tasks = [
        task
        for task in production_flow.get("tasks", [])
        if task.get("type") == "io.kestra.plugin.scripts.python.Script"
    ]
    if not production_python_tasks:
        raise ValueError(
            "Production flow has no Python Script task from which to resolve the Core runtime"
        )
    # Replay tasks import History/Evaluation dependencies, so they use the optional
    # platform image. The production flow is consulted only to validate the Core
    # task structure; its minimal image is not sufficient for database/Parquet work.
    task_image = (
        image_reference
        or os.getenv("UWFLOW_TASK_IMAGE_REFERENCE")
        or f"ai/uwflow-runtime:{project_version}"
    )
    if not isinstance(task_image, str) or not task_image.strip():
        raise ValueError("A prebuilt Python task image reference is required")
    if any(
        task.get("containerImage") != production_python_tasks[0].get("containerImage")
        for task in production_python_tasks
    ):
        raise ValueError(
            "Production Python tasks do not share one Core task image; align the flow before replay"
        )
    baseline_sha = _manifest_sha(baseline_root / "release-manifest.json")
    candidate_sha = _manifest_sha(candidate_root / "release-manifest.json")
    flow_identity = json.dumps(
        {
            "candidate_id": candidate_id,
            "baseline_release": baseline_release,
            "history_tools_id": tools_id,
            "image_reference": task_image,
            "parquet_host_root": str(parquet_host_root) if parquet_host_root is not None else None,
        },
        sort_keys=True,
    )
    flow_id = f"uwflow_dev_history_replay_{hashlib.sha256(flow_identity.encode()).hexdigest()[:10]}"

    docker_runner = {
        "type": "io.kestra.plugin.scripts.runner.docker.Docker",
        "networkMode": "uwflow-local",
        **(
            {"volumes": [f"{parquet_host_root}:/data/uwflow/history:ro"]}
            if parquet_host_root is not None
            else {}
        ),
    }

    def python_task(
        task_id: str,
        runtime_path: str | None,
        command: str,
        output_files: list[str] | None = None,
    ) -> dict:
        """Create a materialized Python task pinned to the selected runtime and image."""
        task = {
            "id": task_id,
            "type": "io.kestra.plugin.scripts.python.Commands",
            "namespaceFiles": {
                "enabled": True,
                "include": [
                    f"history-tools/{tools_id}/**",
                    *([f"{runtime_path}/**"] if runtime_path else []),
                ],
                "ifExists": "FAIL",
            },
            "pythonVersion": "3.11",
            "containerImage": task_image,
            "taskRunner": docker_runner,
            "env": {
                "APP_TASK_IMAGE": task_image,
                # Connector choice is environment/secret-driven; the task never
                # branches on a storage implementation.
                "UWFLOW_HISTORY_CONNECTOR": "{{ secret('UWFLOW_HISTORY_CONNECTOR') }}",
                "UWFLOW_HISTORY_DSN": "{{ secret('UWFLOW_HISTORY_DSN') }}",
                "UWFLOW_HISTORY_ROOT": "{{ secret('UWFLOW_HISTORY_ROOT') }}",
                "UWFLOW_HISTORY_BATCH_SIZE": "{{ inputs.batch_size }}",
                "UWFLOW_HISTORY_DATASET_ID": "{{ inputs.dataset_id }}",
                "UWFLOW_HISTORY_OFFSET": "{{ inputs.offset }}",
                "UWFLOW_HISTORY_MAX_CASES": "{{ inputs.max_cases }}",
            },
            "commands": [command],
        }
        if output_files:
            task["outputFiles"] = output_files
        return task

    tool_prefix = f"history-tools/{tools_id}"
    validation = python_task(
        "validate_dataset",
        None,
        f"python {tool_prefix}/tools/validate_history_dataset.py --output dataset-validation.json",
        ["dataset-validation.json"],
    )
    baseline = python_task(
        "baseline_replay",
        f"runtime/releases/{baseline_release}",
        f"python {tool_prefix}/tools/run_history_batch.py --output baseline.jsonl",
        ["baseline.jsonl", "baseline.jsonl.manifest.json"],
    )
    baseline["env"]["UWFLOW_HISTORY_RUNTIME_ROOT"] = f"runtime/releases/{baseline_release}"
    baseline["env"]["UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"] = baseline_sha
    candidate = python_task(
        "candidate_replay",
        f"runtime/candidates/{candidate_id}",
        f"python {tool_prefix}/tools/run_history_batch.py --output candidate.jsonl",
        ["candidate.jsonl", "candidate.jsonl.manifest.json"],
    )
    candidate["env"]["UWFLOW_HISTORY_RUNTIME_ROOT"] = f"runtime/candidates/{candidate_id}"
    candidate["env"]["UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"] = candidate_sha
    comparison_runner = {
        "type": "io.kestra.plugin.scripts.runner.docker.Docker",
        "networkMode": "uwflow-local",
    }
    comparison = {
        "id": "compare_replays",
        "type": "io.kestra.plugin.scripts.python.Commands",
        "inputFiles": {
            "baseline.jsonl": "{{ outputs.baseline_replay.outputFiles['baseline.jsonl'] }}",
            "candidate.jsonl": "{{ outputs.candidate_replay.outputFiles['candidate.jsonl'] }}",
        },
        "namespaceFiles": {
            "enabled": True,
            "include": [f"history-tools/{tools_id}/**"],
            "ifExists": "FAIL",
        },
        "pythonVersion": "3.11",
        "containerImage": task_image,
        "taskRunner": comparison_runner,
        "env": {"APP_TASK_IMAGE": task_image},
        "commands": [
            f"python {tool_prefix}/tools/compare_history_batches.py "
            "--baseline baseline.jsonl --candidate candidate.jsonl --output-dir comparison"
        ],
        "outputFiles": [
            "comparison/comparison.json",
            "comparison/case_comparison.csv",
            "comparison/decision_migrations.csv",
            "comparison/stage_comparison.csv",
            "comparison/score_deciles.csv",
            "comparison/segment_impact.csv",
            "comparison/source_coverage.csv",
            "comparison/champion_challenger_report.html",
            "comparison/champion_challenger_report.pdf",
        ],
    }

    flow = {
        "id": flow_id,
        "namespace": "com.ai.credit.dev",
        "description": (
            "DEV-only paired historical replay. Kestra orchestrates dataset validation, "
            "baseline/candidate batch tasks and artifact comparison; Python owns all data "
            "access and underwriting calculations. No production execution or mutation."
        ),
        "labels": {
            "app": "uwflow",
            "domain": "underwriting",
            "environment": "dev-historical-replay",
            "baseline-release": baseline_release,
            "candidate-id": candidate_id,
            "history-tools-bundle": tools_id,
            "baseline-manifest-sha256": baseline_sha,
            "candidate-manifest-sha256": candidate_sha,
        },
        "inputs": [
            {"id": "dataset_id", "type": "STRING", "required": True},
            {"id": "batch_size", "type": "INT", "defaults": 2000},
            {"id": "offset", "type": "INT", "defaults": 0},
            {"id": "max_cases", "type": "INT", "defaults": 0},
        ],
        # Kestra executes top-level task lists in order. The Parallel flowable
        # starts the independent baseline/candidate jobs only after validation,
        # and the following comparison waits for both branches to finish.
        "tasks": [
            validation,
            {
                "id": "replay_pair",
                "type": "io.kestra.plugin.core.flow.Parallel",
                "concurrent": 2,
                "onChildFailure": "FAIL",
                "tasks": [baseline, candidate],
            },
            comparison,
        ],
    }
    destination = root / "var" / "artifacts" / "replay-flows" / f"{flow_id}.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered_flow = dump_kestra_yaml(flow).encode("utf-8")
    if destination.exists() and destination.read_bytes() != rendered_flow:
        raise ValueError(f"Refusing to overwrite immutable replay flow: {destination}")
    if not destination.exists():
        destination.write_bytes(rendered_flow)
    print(f"Created DEV historical replay flow: {destination}")
    print(f"REPLAY_FLOW_ID={flow_id}")
    print(f"Baseline runtime: {baseline_release} (manifest {baseline_sha})")
    print(f"Candidate runtime: {candidate_id} (manifest {candidate_sha})")
    print(f"History tooling: {tools_id}")
    print("Next step: publish/reuse immutable bundles and deploy the replay flow:")
    print("  bash tools/guides/workflow/14-publish-history-replay-flow.sh")
    print(
        "The workflow uploads only missing Namespace Files paths, verifies each upload, and never overwrites an existing immutable bundle."
    )
    if parquet_host_root is not None:
        print(
            "Parquet host mount configured. Enable volume-enabled: true for the Kestra Docker Task Runner."
        )
    return destination


def main() -> int:
    """Generate and validate a content-addressed historical replay flow."""
    parser = argparse.ArgumentParser(
        description="Generate a manual DEV historical replay flow for a candidate"
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--baseline-release",
        required=True,
        help="Exact immutable release currently deployed to PROD; never guess this value",
    )
    parser.add_argument(
        "--image-reference",
        default=os.getenv("UWFLOW_TASK_IMAGE_REFERENCE"),
        help="Optional exact prebuilt OCI image reference; defaults to the production flow task image",
    )
    parser.add_argument(
        "--parquet-host-root",
        type=Path,
        help="Optional absolute host path mounted read-only at /data/uwflow/history for Parquet replay",
    )
    args = parser.parse_args()
    try:
        build_flow(
            args.candidate_id,
            args.baseline_release,
            parquet_host_root=args.parquet_host_root,
            image_reference=args.image_reference,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
