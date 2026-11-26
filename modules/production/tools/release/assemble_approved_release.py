"""Assemble an immutable production release from an evaluated DEV candidate.

The approval file is an explicit governance attestation supplied by the approval
process; this tool verifies it and never performs deployment or contacts Kestra.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
import yaml
from tools.kestra.yaml import dump_kestra_yaml

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
DIGEST_REF = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


class ReleaseAssemblyError(RuntimeError):
    """Raised when candidate, evidence or approval provenance is invalid."""

    pass


def sha(data: bytes) -> str:
    """Return the SHA-256 digest of a byte payload."""
    return hashlib.sha256(data).hexdigest()


def _artifact_path(base: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ReleaseAssemblyError("Artifact manifest contains an invalid relative path")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
        raise ReleaseAssemblyError(f"Artifact manifest contains an unsafe path: {relative!r}")
    path = (base / Path(*posix.parts)).resolve()
    if base.resolve() not in path.parents:
        raise ReleaseAssemblyError(f"Artifact path escapes its bundle: {relative!r}")
    return path


def assemble_approved_release(
    repository_root: Path | str,
    candidate_id: str,
    release_id: str,
    approval_file: Path | str,
    image_reference: str,
) -> dict[str, Any]:
    """Assemble an immutable deployable package from an evaluated and approved candidate."""
    root = Path(repository_root).resolve()
    if not re.fullmatch(r"dev-[0-9a-f]{16}", candidate_id):
        raise ReleaseAssemblyError("Invalid candidate ID")
    if not re.fullmatch(r"\d+\.\d+\.\d+", release_id):
        raise ReleaseAssemblyError("Release ID must be MAJOR.MINOR.PATCH")
    if not DIGEST_REF.fullmatch(image_reference):
        raise ReleaseAssemblyError("Production image must be pinned by immutable @sha256 digest")
    candidate = root / "var/artifacts/candidates" / candidate_id
    manifest_path = candidate / "release-manifest.json"
    if not manifest_path.is_file():
        raise ReleaseAssemblyError("Candidate artifact not found")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        manifest.get("manifest_format") != 1
        or manifest.get("candidate_id") != candidate_id
        or manifest.get("environment") != "DEV"
    ):
        raise ReleaseAssemblyError("Candidate manifest identity/format/environment mismatch")
    if manifest.get("core_source_tree_status") != "clean":
        raise ReleaseAssemblyError(
            "Candidate was not built from a verified clean Git tree; rebuild from a reviewed commit"
        )
    artifact_manifest_path = candidate / "candidate-artifact-manifest.json"
    if not artifact_manifest_path.is_file():
        raise ReleaseAssemblyError("Candidate artifact manifest is missing")
    artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))
    if (
        artifact_manifest.get("artifact_format") != 1
        or artifact_manifest.get("candidate_id") != candidate_id
        or artifact_manifest.get("release_manifest_sha256") != sha(manifest_bytes)
    ):
        raise ReleaseAssemblyError("Candidate artifact manifest identity/format mismatch")
    artifact_files = artifact_manifest.get("files")
    required_artifacts = {
        "release-manifest.json",
        "candidate-flow.yaml",
        "production-flow-template.yaml",
        "policy-specs/stage1_hard_gates.json",
        "policy-specs/stage3_source_plan.json",
    }
    if not isinstance(artifact_files, dict) or not required_artifacts.issubset(artifact_files):
        raise ReleaseAssemblyError(
            "Candidate artifact manifest is incomplete for the current v2 contract"
        )
    for relative, expected in artifact_files.items():
        path = _artifact_path(candidate, relative)
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ReleaseAssemblyError(f"Candidate artifact checksum mismatch: {relative}")
    if not (candidate / "candidate-flow.yaml").is_file():
        raise ReleaseAssemblyError("Candidate flow is missing")
    runtime_files = {
        p.name: p.read_bytes()
        for p in candidate.iterdir()
        if p.is_file() and p.name in manifest.get("files", {})
    }
    if {n: sha(b) for n, b in sorted(runtime_files.items())} != manifest.get("files"):
        raise ReleaseAssemblyError("Candidate runtime hashes do not match its manifest")
    for filename, expected in manifest.get("policy_specs", {}).items():
        path = candidate / "policy-specs" / filename
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ReleaseAssemblyError(f"Candidate policy hash mismatch: {filename}")
    approval_path = Path(approval_file).resolve()
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    required = {
        "status": "approved",
        "candidate_id": candidate_id,
        "candidate_manifest_sha256": sha(manifest_bytes),
    }
    for key, value in required.items():
        if approval.get(key) != value:
            raise ReleaseAssemblyError(f"Approval attestation mismatch for {key}")
    if (
        not approval.get("approved_by")
        or not approval.get("approved_at")
        or not approval.get("evaluation_id")
    ):
        raise ReleaseAssemblyError("Approval must identify approver, timestamp and evaluation_id")
    evaluation_id = approval.get("evaluation_id")
    if not isinstance(evaluation_id, str) or not re.fullmatch(
        r"eval-[a-z0-9][a-z0-9-]{2,60}", evaluation_id
    ):
        raise ReleaseAssemblyError("Approval evaluation_id is invalid")
    evaluation = root / "var/artifacts/evaluations" / evaluation_id
    if not evaluation.is_dir():
        raise ReleaseAssemblyError("Referenced evaluation artifact does not exist")
    evaluation_manifest_path = evaluation / "evaluation-manifest.json"
    if not evaluation_manifest_path.is_file():
        raise ReleaseAssemblyError("Evaluation artifact has no immutable evaluation-manifest.json")
    evaluation_manifest = json.loads(evaluation_manifest_path.read_text(encoding="utf-8"))
    if (
        evaluation_manifest.get("evaluation_format") != 1
        or evaluation_manifest.get("evaluation_id") != evaluation_id
    ):
        raise ReleaseAssemblyError("Evaluation manifest identity/format mismatch")
    if evaluation_manifest.get("candidate_id") != candidate_id:
        raise ReleaseAssemblyError("Evaluation was not run for this exact candidate")
    if evaluation_manifest.get("candidate_manifest_sha256") != sha(manifest_bytes):
        raise ReleaseAssemblyError("Evaluation references a different candidate manifest")
    if evaluation_manifest.get("baseline_release") != manifest.get("based_on_production_release"):
        raise ReleaseAssemblyError(
            "Evaluation baseline differs from the candidate's declared baseline"
        )
    evaluation_files = evaluation_manifest.get("files")
    if not isinstance(evaluation_files, dict) or not evaluation_files:
        raise ReleaseAssemblyError("Evaluation artifact lacks evidence files or dataset identity")
    for relative, expected in evaluation_files.items():
        path = _artifact_path(evaluation, relative)
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ReleaseAssemblyError(f"Evaluation evidence checksum mismatch: {relative}")
    if not evaluation_manifest.get("dataset_id"):
        raise ReleaseAssemblyError("Evaluation artifact lacks evidence files or dataset identity")
    target = root / "var/releases/approved" / release_id
    if target.exists():
        raise ReleaseAssemblyError(f"Approved release already exists and is immutable: {target}")
    template_path = candidate / "production-flow-template.yaml"
    if not template_path.is_file():
        raise ReleaseAssemblyError("Candidate production-flow template is missing")
    template_bytes = template_path.read_bytes()
    if sha(template_bytes) != manifest.get("production_flow_template_sha256"):
        raise ReleaseAssemblyError("Candidate production-flow template hash mismatch")
    flow = yaml.safe_load(template_bytes)
    flow["id"] = "uwflow_production_underwriting"
    flow["namespace"] = "com.ai.credit.production"
    flow.setdefault("labels", {}).update(
        {
            "system.readOnly": "true",
            "environment": "production",
            "runtime-release": release_id,
            "candidate-id": candidate_id,
            "candidate-manifest-sha256": sha(manifest_bytes),
        }
    )
    tasks = []

    def walk(items):
        """Recursively enumerate release payload files in stable relative-path order."""
        for task in items or []:
            if task.get("type") in {
                "io.kestra.plugin.scripts.python.Script",
                "io.kestra.plugin.scripts.python.Commands",
            }:
                tasks.append(task)
            walk(task.get("tasks"))
            walk(task.get("then"))
            walk(task.get("else"))

    walk(flow.get("tasks"))
    if len(tasks) != 7:
        raise ReleaseAssemblyError(f"Expected seven Core Python tasks, found {len(tasks)}")
    namespace_files = {
        "enabled": True,
        "include": [f"runtime/releases/{release_id}/**"],
        "ifExists": "FAIL",
    }
    for task in tasks:
        task["namespaceFiles"] = namespace_files
        task["containerImage"] = image_reference
        env = task.setdefault("env", {})
        env["APP_RUNTIME_PATH"] = f"runtime/releases/{release_id}"
        env["APP_RUNTIME_MANIFEST_SHA256"] = "PENDING_RUNTIME_MANIFEST_HASH"
        env["APP_TASK_IMAGE"] = image_reference
        env["APP_RUNTIME_ARTIFACT_TYPE"] = "uwflow-kestra-runtime"
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{release_id}.", dir=target.parent if target.parent.exists() else root
        )
    )
    try:
        runtime_dir = stage / "runtime"
        runtime_dir.mkdir()
        for name, content in runtime_files.items():
            (runtime_dir / name).write_bytes(content)
        runtime_manifest = {
            "artifact_type": "uwflow-kestra-runtime",
            "manifest_format": 1,
            "release_version": release_id,
            "candidate_id": candidate_id,
            "files": {n: sha(b) for n, b in sorted(runtime_files.items())},
        }
        runtime_manifest_bytes = (
            json.dumps(runtime_manifest, indent=2, sort_keys=True) + "\n"
        ).encode()
        (runtime_dir / "release-manifest.json").write_bytes(runtime_manifest_bytes)
        runtime_digest = sha(runtime_manifest_bytes)
        for task in tasks:
            task["env"]["APP_RUNTIME_MANIFEST_SHA256"] = runtime_digest
        production_flow_bytes = dump_kestra_yaml(flow).encode("utf-8")
        (stage / "production-flow.yaml").write_bytes(production_flow_bytes)
        shutil.copytree(candidate / "policy-specs", stage / "policy-specs")
        shutil.copyfile(manifest_path, stage / "candidate-manifest.json")
        shutil.copyfile(artifact_manifest_path, stage / "candidate-artifact-manifest.json")
        evaluation_reference_bytes = (
            json.dumps(
                {
                    "evaluation_id": approval["evaluation_id"],
                    "evaluation_manifest_sha256": sha(evaluation_manifest_path.read_bytes()),
                    "files": evaluation_files,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        (stage / "evaluation-reference.json").write_bytes(evaluation_reference_bytes)
        approval_bytes = approval_path.read_bytes()
        shutil.copyfile(approval_path, stage / "approval-reference.json")
        release_manifest = {
            "release_format": 1,
            "release_id": release_id,
            "candidate_id": candidate_id,
            "candidate_manifest_sha256": sha(manifest_bytes),
            "candidate_artifact_manifest_sha256": sha(artifact_manifest_path.read_bytes()),
            "runtime_manifest_sha256": runtime_digest,
            "evaluation_manifest_sha256": sha(evaluation_manifest_path.read_bytes()),
            "image_reference": image_reference,
            "evaluation_id": approval["evaluation_id"],
            "approval_sha256": sha(approval_bytes),
            "evaluation_reference_sha256": sha(evaluation_reference_bytes),
            "production_flow_sha256": sha(production_flow_bytes),
            "evaluation_files": evaluation_files,
            "approved_by": approval["approved_by"],
            "approved_at": approval["approved_at"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "core_runtime": manifest.get("core_runtime"),
            "strategy_workspace_id": manifest.get("workspace_id"),
        }
        (stage / "release-manifest.json").write_text(
            json.dumps(release_manifest, indent=2, sort_keys=True) + "\n"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.replace(target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "release_id": release_id,
        "candidate_id": candidate_id,
        "path": target.relative_to(root).as_posix(),
        "release_manifest_sha256": sha((target / "release-manifest.json").read_bytes()),
        "image_reference": image_reference,
    }


def main() -> int:
    """Validate approval inputs and assemble the requested approved production release."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--approval", required=True, type=Path)
    parser.add_argument("--image-reference", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            assemble_approved_release(
                ROOT, args.candidate, args.release_id, args.approval, args.image_reference
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
