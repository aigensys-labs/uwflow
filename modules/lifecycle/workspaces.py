"""Strategy workspaces and strict source selection for the UWflow v2 lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_FILES = {
    "stage_1_hard_gates": "stage1_hard_gates.json",
    "stage_3_source_plan": "stage3_source_plan.json",
}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_CANDIDATE_ID = re.compile(r"^dev-[0-9a-f]{16}$")
_RELEASE_ID = re.compile(r"^\d+\.\d+\.\d+$")


class WorkspaceError(ValueError):
    """Invalid workspace operation or source artifact."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"{label} is missing or invalid: {path}") from exc
    if not isinstance(value, dict):
        raise WorkspaceError(f"{label} must contain a JSON object: {path}")
    return value


def _safe_artifact_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise WorkspaceError("Artifact manifest contains an invalid relative path")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
        raise WorkspaceError(f"Artifact manifest contains an unsafe path: {relative!r}")
    path = (root / Path(*posix.parts)).resolve()
    if root.resolve() not in path.parents:
        raise WorkspaceError(f"Artifact path escapes its source directory: {relative!r}")
    return path


class WorkspaceStore:
    """Store mutable analyst copies and fork only verified v2 source artifacts."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.directory = self.root / "var" / "workspaces" / "strategies"
        self.core_policies = self.root / "core" / "underwriting" / "policies" / "stages"
        self.core_flow_template = (
            self.root / "core" / "kestra" / "flows" / "uwflow_production_underwriting.yaml"
        )

    def _path(self, workspace_id: str) -> Path:
        if not _ID.fullmatch(workspace_id):
            raise WorkspaceError("Invalid workspace ID")
        path = (self.directory / workspace_id).resolve()
        if self.directory.resolve() not in path.parents:
            raise WorkspaceError("Workspace path escapes its storage directory")
        return path

    def _verify_candidate(self, source_id: str) -> tuple[Path, dict[str, Any], bytes]:
        if not _CANDIDATE_ID.fullmatch(source_id):
            raise WorkspaceError("Invalid candidate ID")
        source = self.root / "var" / "artifacts" / "candidates" / source_id
        manifest_path = source / "release-manifest.json"
        artifact_manifest_path = source / "candidate-artifact-manifest.json"
        if (
            not source.is_dir()
            or not manifest_path.is_file()
            or not artifact_manifest_path.is_file()
        ):
            raise WorkspaceError(f"Candidate is not a complete v2 artifact: {source_id}")

        manifest_bytes = manifest_path.read_bytes()
        manifest = _read_json(manifest_path, "Candidate release manifest")
        artifact = _read_json(artifact_manifest_path, "Candidate artifact manifest")
        if (
            manifest.get("manifest_format") != 1
            or manifest.get("candidate_id") != source_id
            or manifest.get("environment") != "DEV"
        ):
            raise WorkspaceError(f"Candidate identity/format/environment mismatch: {source_id}")
        if artifact.get("artifact_format") != 1 or artifact.get("candidate_id") != source_id:
            raise WorkspaceError(f"Candidate artifact manifest identity mismatch: {source_id}")
        if artifact.get("release_manifest_sha256") != _sha(manifest_bytes):
            raise WorkspaceError(f"Candidate release manifest checksum mismatch: {source_id}")

        files = artifact.get("files")
        if not isinstance(files, dict) or not files:
            raise WorkspaceError(f"Candidate artifact manifest has no file checksums: {source_id}")
        required_files = {
            "release-manifest.json",
            "candidate-flow.yaml",
            "production-flow-template.yaml",
            *(f"policy-specs/{name}" for name in POLICY_FILES.values()),
        }
        if not required_files.issubset(files):
            missing = sorted(required_files - set(files))
            raise WorkspaceError(
                f"Candidate {source_id} is missing required v2 artifacts: {missing}"
            )
        for relative, expected in files.items():
            path = _safe_artifact_file(source, relative)
            if not path.is_file() or _sha(path.read_bytes()) != expected:
                raise WorkspaceError(
                    f"Candidate artifact checksum mismatch: {source_id}/{relative}"
                )

        template = source / "production-flow-template.yaml"
        if _sha(template.read_bytes()) != manifest.get("production_flow_template_sha256"):
            raise WorkspaceError(f"Candidate production-flow template hash mismatch: {source_id}")
        declared_policies = manifest.get("policy_specs")
        if not isinstance(declared_policies, dict):
            raise WorkspaceError(f"Candidate has no canonical policy hash map: {source_id}")
        for filename in POLICY_FILES.values():
            expected = declared_policies.get(filename)
            path = source / "policy-specs" / filename
            if not expected or not path.is_file() or _sha(path.read_bytes()) != expected:
                raise WorkspaceError(
                    f"Candidate policy specification is invalid: {source_id}/{filename}"
                )
        return source, manifest, manifest_bytes

    def _verify_approved_release(self, source_id: str) -> tuple[Path, dict[str, Any], bytes]:
        if not _RELEASE_ID.fullmatch(source_id):
            raise WorkspaceError("Invalid approved release ID")
        source = self.root / "var" / "releases" / "approved" / source_id
        manifest_path = source / "release-manifest.json"
        if not source.is_dir() or not manifest_path.is_file():
            raise WorkspaceError(f"Approved release not found: {source_id}")
        manifest_bytes = manifest_path.read_bytes()
        manifest = _read_json(manifest_path, "Approved release manifest")
        if manifest.get("release_id") != source_id or manifest.get("release_format") != 1:
            raise WorkspaceError(f"Approved release identity/format mismatch: {source_id}")

        runtime_manifest_path = source / "runtime" / "release-manifest.json"
        production_flow_path = source / "production-flow.yaml"
        if not runtime_manifest_path.is_file() or not production_flow_path.is_file():
            raise WorkspaceError(f"Approved release is incomplete: {source_id}")
        runtime_manifest_bytes = runtime_manifest_path.read_bytes()
        runtime_manifest = _read_json(runtime_manifest_path, "Approved runtime manifest")
        if (
            runtime_manifest.get("artifact_type") != "uwflow-kestra-runtime"
            or runtime_manifest.get("manifest_format") != 1
            or runtime_manifest.get("release_version") != source_id
        ):
            raise WorkspaceError(f"Approved runtime identity/format mismatch: {source_id}")
        if manifest.get("runtime_manifest_sha256") != _sha(runtime_manifest_bytes):
            raise WorkspaceError(f"Approved runtime manifest checksum mismatch: {source_id}")
        if manifest.get("production_flow_sha256") != _sha(production_flow_path.read_bytes()):
            raise WorkspaceError(f"Approved production flow checksum mismatch: {source_id}")

        candidate_manifest_path = source / "candidate-manifest.json"
        candidate_artifact_manifest_path = source / "candidate-artifact-manifest.json"
        if not candidate_manifest_path.is_file() or not candidate_artifact_manifest_path.is_file():
            raise WorkspaceError(f"Approved release is missing candidate provenance: {source_id}")
        candidate_manifest_bytes = candidate_manifest_path.read_bytes()
        candidate_manifest = _read_json(candidate_manifest_path, "Approved candidate manifest")
        candidate_artifact_manifest_bytes = candidate_artifact_manifest_path.read_bytes()
        candidate_artifact_manifest = _read_json(
            candidate_artifact_manifest_path, "Approved candidate artifact manifest"
        )
        if manifest.get("candidate_manifest_sha256") != _sha(
            candidate_manifest_bytes
        ) or candidate_manifest.get("candidate_id") != manifest.get("candidate_id"):
            raise WorkspaceError(
                f"Approved candidate manifest identity/checksum mismatch: {source_id}"
            )
        if (
            manifest.get("candidate_artifact_manifest_sha256")
            != _sha(candidate_artifact_manifest_bytes)
            or candidate_artifact_manifest.get("candidate_id") != manifest.get("candidate_id")
            or candidate_artifact_manifest.get("release_manifest_sha256")
            != _sha(candidate_manifest_bytes)
        ):
            raise WorkspaceError(
                f"Approved candidate artifact manifest identity/checksum mismatch: {source_id}"
            )

        runtime_files = runtime_manifest.get("files")
        if not isinstance(runtime_files, dict) or not runtime_files:
            raise WorkspaceError(f"Approved runtime manifest has no file checksums: {source_id}")
        for relative, expected in runtime_files.items():
            path = _safe_artifact_file(source / "runtime", relative)
            if not path.is_file() or _sha(path.read_bytes()) != expected:
                raise WorkspaceError(f"Approved runtime checksum mismatch: {source_id}/{relative}")
        declared_policies = candidate_manifest.get("policy_specs")
        if not isinstance(declared_policies, dict):
            raise WorkspaceError(f"Approved candidate manifest has no policy hash map: {source_id}")
        for filename in POLICY_FILES.values():
            policy_path = source / "policy-specs" / filename
            expected = declared_policies.get(filename)
            if (
                not expected
                or not policy_path.is_file()
                or _sha(policy_path.read_bytes()) != expected
            ):
                raise WorkspaceError(
                    f"Approved policy specification checksum mismatch: {source_id}/{filename}"
                )

        approval_path = source / "approval-reference.json"
        evaluation_reference_path = source / "evaluation-reference.json"
        if not approval_path.is_file() or not evaluation_reference_path.is_file():
            raise WorkspaceError(
                f"Approved release is missing approval/evaluation references: {source_id}"
            )
        approval_bytes = approval_path.read_bytes()
        evaluation_reference_bytes = evaluation_reference_path.read_bytes()
        if manifest.get("approval_sha256") != _sha(approval_bytes):
            raise WorkspaceError(
                f"Approved release approval-reference checksum mismatch: {source_id}"
            )
        if manifest.get("evaluation_reference_sha256") != _sha(evaluation_reference_bytes):
            raise WorkspaceError(
                f"Approved release evaluation-reference checksum mismatch: {source_id}"
            )

        approval = _read_json(approval_path, "Approved release approval reference")
        evaluation_reference = _read_json(
            evaluation_reference_path, "Approved release evaluation reference"
        )
        candidate_id = manifest.get("candidate_id")
        evaluation_id = manifest.get("evaluation_id")
        if (
            approval.get("status") != "approved"
            or approval.get("candidate_id") != candidate_id
            or approval.get("candidate_manifest_sha256")
            != manifest.get("candidate_manifest_sha256")
            or approval.get("evaluation_id") != evaluation_id
            or not approval.get("approved_by")
            or not approval.get("approved_at")
        ):
            raise WorkspaceError(f"Approved release approval identity/status mismatch: {source_id}")
        if (
            evaluation_reference.get("evaluation_id") != evaluation_id
            or evaluation_reference.get("evaluation_manifest_sha256")
            != manifest.get("evaluation_manifest_sha256")
            or evaluation_reference.get("files") != manifest.get("evaluation_files")
        ):
            raise WorkspaceError(f"Approved release evaluation reference mismatch: {source_id}")
        evaluation_files = manifest.get("evaluation_files")
        if not isinstance(evaluation_files, dict) or not evaluation_files:
            raise WorkspaceError(
                f"Approved release has no evaluation evidence file map: {source_id}"
            )
        if not manifest.get("candidate_manifest_sha256") or not manifest.get(
            "candidate_artifact_manifest_sha256"
        ):
            raise WorkspaceError(
                f"Approved release has incomplete candidate provenance: {source_id}"
            )
        return source, manifest, manifest_bytes

    def create(
        self,
        name: str = "Default strategy",
        *,
        source_type: str = "core-default",
        source_id: str = "core-default",
        source_manifest_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Create an independent mutable workspace from Core default policies."""
        workspace_id = f"strategy-{uuid.uuid4().hex[:12]}"
        target = self._path(workspace_id)
        target.mkdir(parents=True, exist_ok=False)
        policy_dir = target / "policy-specs"
        policy_dir.mkdir()
        for filename in POLICY_FILES.values():
            source = self.core_policies / filename
            if not source.is_file():
                raise WorkspaceError(f"Core default policy is missing: {filename}")
            shutil.copyfile(source, policy_dir / filename)
        if not self.core_flow_template.is_file():
            raise WorkspaceError("Core production-flow template is missing")
        metadata = {
            "workspace_format": 1,
            "workspace_id": workspace_id,
            "name": name.strip()[:120] or "Untitled strategy",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "type": source_type,
                "id": source_id,
                "manifest_sha256": source_manifest_sha256,
            },
            "parent_workspace_id": None,
            "core_runtime": {
                "selection": "core-working-tree",
                "runtime_source_path": "core/python/runtime",
            },
            "flow_template_source_path": "core/kestra/flows/uwflow_production_underwriting.yaml",
        }
        (target / "workspace.json").write_bytes(_json(metadata))
        return metadata

    def ensure_default(self) -> dict[str, Any]:
        """Return the default workspace, creating it lazily when necessary."""
        for item in self.list():
            if item.get("source", {}).get("type") == "core-default":
                return item
        return self.create()

    def list(self) -> list[dict[str, Any]]:
        """List available analyst workspaces with their source ancestry."""
        if not self.directory.exists():
            return []
        items = []
        for path in sorted(self.directory.glob("*/workspace.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    items.append(value)
            except (OSError, json.JSONDecodeError):
                continue
        return items

    def get(self, workspace_id: str) -> dict[str, Any]:
        """Load one workspace and validate its metadata and policy inventory."""
        path = self._path(workspace_id)
        try:
            metadata = json.loads((path / "workspace.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"Workspace not found or invalid: {workspace_id}") from exc
        if not isinstance(metadata, dict) or metadata.get("workspace_id") != workspace_id:
            raise WorkspaceError(f"Workspace metadata identity mismatch: {workspace_id}")
        return metadata

    def policy_path(self, workspace_id: str, stage_id: str) -> Path:
        """Resolve the workspace-owned policy file for a supported stage."""
        filename = POLICY_FILES.get(stage_id)
        if filename is None:
            raise WorkspaceError("This stage is protected or unavailable")
        return self._path(workspace_id) / "policy-specs" / filename

    def sources(self) -> list[dict[str, str]]:
        """List only verified DEV candidates and approved releases that can seed a workspace."""
        result: list[dict[str, str]] = []
        candidates = self.root / "var" / "artifacts" / "candidates"
        if candidates.is_dir():
            for path in sorted(candidates.iterdir()):
                if not path.is_dir():
                    continue
                try:
                    self._verify_candidate(path.name)
                except WorkspaceError:
                    continue
                result.append(
                    {
                        "source_type": "candidate",
                        "source_id": path.name,
                        "label": f"DEV candidate · {path.name}",
                    }
                )

        current_release = os.environ.get("UWFLOW_CURRENT_PROD_RELEASE") or None
        current_path = self.root / "var" / "deployments" / "production" / "current.json"
        if current_release is None and current_path.is_file():
            try:
                current_release = json.loads(current_path.read_text(encoding="utf-8")).get(
                    "release_id"
                )
            except (OSError, json.JSONDecodeError):
                current_release = None
        approved = self.root / "var" / "releases" / "approved"
        if approved.is_dir():
            for path in sorted(approved.iterdir()):
                if not path.is_dir():
                    continue
                try:
                    self._verify_approved_release(path.name)
                except WorkspaceError:
                    continue
                label = (
                    f"Currently deployed PROD · {path.name}"
                    if path.name == current_release
                    else f"Approved release · {path.name}"
                )
                result.append(
                    {"source_type": "approved-release", "source_id": path.name, "label": label}
                )
        return result

    def fork(self, source_type: str, source_id: str, name: str) -> dict[str, Any]:
        """Create a workspace from a fully verified candidate or approved release."""
        if source_type == "candidate":
            source, manifest, manifest_bytes = self._verify_candidate(source_id)
            core_runtime = {
                **manifest.get("core_runtime", {}),
                "runtime_source_path": f"var/artifacts/candidates/{source_id}",
            }
            flow_template = source / "production-flow-template.yaml"
            flow_template_path = (
                f"var/artifacts/candidates/{source_id}/production-flow-template.yaml"
            )
        elif source_type == "approved-release":
            source, manifest, manifest_bytes = self._verify_approved_release(source_id)
            core_runtime = {
                **(manifest.get("core_runtime") or {}),
                "runtime_source_path": f"var/releases/approved/{source_id}/runtime",
            }
            flow_template = source / "production-flow.yaml"
            flow_template_path = f"var/releases/approved/{source_id}/production-flow.yaml"
        else:
            raise WorkspaceError("source_type must be candidate or approved-release")

        source_policies = source / "policy-specs"
        workspace = self.create(
            name,
            source_type=source_type,
            source_id=source_id,
            source_manifest_sha256=_sha(manifest_bytes),
        )
        workspace_root = self._path(workspace["workspace_id"])
        target = workspace_root / "policy-specs"
        for filename in POLICY_FILES.values():
            shutil.copyfile(source_policies / filename, target / filename)
        workspace["parent_workspace_id"] = manifest.get("workspace_id") or manifest.get(
            "strategy_workspace_id"
        )
        workspace["core_runtime"] = core_runtime
        workspace["flow_template_source_path"] = flow_template_path
        workspace["updated_at"] = datetime.now(timezone.utc).isoformat()
        (workspace_root / "workspace.json").write_bytes(_json(workspace))
        return workspace
