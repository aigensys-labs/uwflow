"""Loopback-only FastAPI service for the UWflow Policy & Routing Studio.

The service validates and saves workspace-owned policy JSON and generated preview
code, and can prepare a content-addressed DEV candidate locally. Core's default
policy and runtime source are read-only to this service. It never calls Kestra,
executes underwriting, writes an approved release, or deploys production.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from modules.lifecycle.workspaces import WorkspaceError, WorkspaceStore

from tools.policy.compiler import (
    PolicyValidationError,
    render_module,
    validate_policy_spec,
)

PROJECT_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
EDITABLE_POLICIES = {
    "stage_1_hard_gates": {
        "file": "stage1_hard_gates.json",
        "kind": "dmn_table",
        "label": "Hard gates",
        "description": "Stage 1 eligibility checks and their reason codes.",
    },
    "stage_3_source_plan": {
        "file": "stage3_source_plan.json",
        "kind": "routing_dag",
        "label": "Alternative-data source planning",
        "description": "Stage 3 source eligibility and the source plan handed to Kestra.",
    },
}

STAGES = [
    {
        "id": "stage_1_hard_gates",
        "number": 1,
        "label": "Hard gates",
        "description": "Eligibility checks and immediate policy failures.",
        "editable": True,
        "editor": "dmn_table",
        "status": "editable",
    },
    {
        "id": "stage_2_bureau",
        "number": 2,
        "label": "Bureau assessment",
        "description": "Bureau adapter and decision logic remain runtime-owned in this phase.",
        "editable": False,
        "editor": None,
        "status": "protected",
    },
    {
        "id": "stage_3_source_plan",
        "number": 3,
        "label": "Source planning",
        "description": "Consent and eligibility routing that produces a typed source plan.",
        "editable": True,
        "editor": "routing_dag",
        "status": "editable",
    },
    {
        "id": "stage_4_alternative_data",
        "number": 4,
        "label": "Alternative-data execution",
        "description": "Kestra owns fanout and adapter execution; the studio cannot edit it.",
        "editable": False,
        "editor": None,
        "status": "protected",
    },
    {
        "id": "stage_5_aidflow",
        "number": 5,
        "label": "AIDflow scoring",
        "description": "Protected inference boundary: ten normalized inputs to one profile score.",
        "editable": False,
        "editor": None,
        "status": "protected",
    },
    {
        "id": "stage_6_policy_decision",
        "number": 6,
        "label": "Underwriting decision",
        "description": "The existing UWflow decision engine owns affordability, pricing and outcomes; not externalized yet.",
        "editable": False,
        "editor": None,
        "status": "planned",
    },
    {
        "id": "stage_7_reporting",
        "number": 7,
        "label": "Reporting",
        "description": "Presentation-only output; it does not recalculate underwriting decisions.",
        "editable": False,
        "editor": None,
        "status": "protected",
    },
]


class PolicyRequest(BaseModel):
    """Request payload for validating, previewing or saving a typed policy specification."""

    spec: dict[str, Any]
    expected_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class BuildCandidateRequest(BaseModel):
    """Request payload identifying the workspace used to build a DEV candidate."""

    baseline_release: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    workspace_id: str | None = None


class CreateWorkspaceRequest(BaseModel):
    """Request payload for creating a named analyst workspace."""

    name: str = "Untitled strategy"


class ForkWorkspaceRequest(BaseModel):
    """Request payload for forking a verified candidate or approved release."""

    source_type: str
    source_id: str
    name: str = "Forked strategy"


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def create_app(repository_root: Path | str = PROJECT_ROOT) -> FastAPI:
    """Create the loopback-only Policy Studio API bound to the supplied repository root."""
    root = Path(repository_root).resolve()
    workspace_store = WorkspaceStore(root)
    default_workspace: dict[str, Any] | None = None
    catalog_path = root / "core" / "underwriting" / "policies" / "schema" / "fields.json"
    write_lock = threading.RLock()

    app = FastAPI(
        title="UWflow Policy Studio API",
        version="2.0.0",
        description=(
            "Local policy authoring, validation, Python preview and immutable DEV candidate preparation. "
            "This API does not execute underwriting, call Kestra or publish production releases."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    def load_catalog() -> dict[str, Any]:
        """Load the field and source catalog used by policy validation."""
        try:
            value = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Cannot read field catalogue: {exc}"
            ) from exc
        return value

    def get_default_workspace() -> dict[str, Any]:
        """Resolve or lazily create the Studio's default analyst workspace."""
        nonlocal default_workspace
        if default_workspace is None:
            default_workspace = workspace_store.ensure_default()
        return default_workspace

    def policy_path(stage_id: str, workspace_id: str | None = None) -> Path:
        """Resolve a supported stage policy path inside the selected workspace."""
        entry = EDITABLE_POLICIES.get(stage_id)
        if entry is None:
            raise HTTPException(
                status_code=403,
                detail="This stage is protected or not yet available in the studio.",
            )
        try:
            selected_workspace = workspace_id or get_default_workspace()["workspace_id"]
            return workspace_store.policy_path(selected_workspace, stage_id)
        except WorkspaceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def read_policy(stage_id: str, workspace_id: str | None = None) -> tuple[dict[str, Any], bytes]:
        """Read a workspace policy and its content hash for optimistic concurrency."""
        path = policy_path(stage_id, workspace_id)
        try:
            raw = path.read_bytes()
            spec = json.loads(raw)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=500, detail=f"Policy source is missing: {path.name}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500, detail=f"Policy source is invalid JSON: {path.name}"
            ) from exc
        return spec, raw

    def build_candidate_module(
        replacement_stage: str, replacement_spec: dict[str, Any], workspace_id: str | None = None
    ) -> tuple[str, bytes]:
        """Compile a saved workspace policy preview without changing Core runtime source."""
        catalog = load_catalog()
        replacement_bytes = _json_bytes(replacement_spec)
        specs: list[dict[str, Any]] = []
        spec_bytes: dict[str, bytes] = {}
        for stage_id, entry in EDITABLE_POLICIES.items():
            path = policy_path(stage_id, workspace_id)
            try:
                current_raw = path.read_bytes()
                current_spec = json.loads(current_raw)
            except (OSError, json.JSONDecodeError) as exc:
                raise PolicyValidationError(f"Cannot load policy {entry['file']}: {exc}") from exc
            if stage_id == replacement_stage:
                spec = replacement_spec
                # Preserve original bytes for an unchanged policy. This keeps a
                # no-op preview byte-for-byte identical to the checked-in module.
                raw = current_raw if replacement_spec == current_spec else replacement_bytes
            else:
                raw = current_raw
                spec = current_spec
            if spec.get("stage") != stage_id or spec.get("kind") != entry["kind"]:
                raise PolicyValidationError(
                    f"Policy must retain stage={stage_id!r} and kind={entry['kind']!r}."
                )
            validate_policy_spec(spec, catalog)
            specs.append(spec)
            spec_bytes[stage_id] = raw
        specs.sort(key=lambda item: item["stage"])
        return render_module(specs, spec_bytes), replacement_bytes

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Return the API readiness status."""
        return {"status": "ok", "mode": "local-authoring-only"}

    @app.get("/api/stages")
    def get_stages() -> list[dict[str, Any]]:
        """Return the supported seven-stage Studio catalogue."""
        return STAGES

    @app.get("/api/catalog/{stage_id}")
    def get_catalog(stage_id: str) -> dict[str, Any]:
        """Return the field/source catalog for a requested editable stage."""
        catalog = load_catalog()
        stage_fields = {
            name: {"type": item["type"], "description": item.get("description", "")}
            for name, item in catalog.get("fields", {}).items()
            if stage_id in item.get("stages", [])
        }
        if not stage_fields:
            raise HTTPException(
                status_code=403, detail="This stage has no editable policy field catalogue."
            )
        return {
            "stage": stage_id,
            "fields": stage_fields,
            "source_ids": catalog.get("source_ids", [])
            if stage_id == "stage_3_source_plan"
            else [],
        }

    @app.get("/api/workspaces")
    def list_workspaces() -> dict[str, Any]:
        """List analyst workspaces available to the current local Studio instance."""
        default = get_default_workspace()
        return {"items": workspace_store.list(), "default_workspace_id": default["workspace_id"]}

    @app.get("/api/workspaces/sources")
    def list_workspace_sources() -> dict[str, Any]:
        """List verified candidates and approved releases available for workspace forking."""
        return {"items": workspace_store.sources()}

    @app.post("/api/workspaces")
    def create_workspace(request: CreateWorkspaceRequest) -> dict[str, Any]:
        """Create a new independent workspace from Core default policies."""
        try:
            return workspace_store.create(request.name)
        except WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/workspaces/fork")
    def fork_workspace(request: ForkWorkspaceRequest) -> dict[str, Any]:
        """Fork a verified candidate or approved release into a new workspace."""
        try:
            return workspace_store.fork(request.source_type, request.source_id, request.name)
        except (WorkspaceError, OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/policies/{stage_id}")
    def get_policy(stage_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        """Return the selected workspace's policy and current content hash."""
        with write_lock:
            spec, raw = read_policy(stage_id, workspace_id)
        return {"spec": spec, "sha256": _sha256(raw), "kind": spec["kind"], "stage": stage_id}

    @app.post("/api/policies/{stage_id}/validate")
    def validate_policy(
        stage_id: str, request: PolicyRequest, workspace_id: str | None = None
    ) -> dict[str, Any]:
        """Validate a proposed policy without saving or generating a candidate."""
        policy_path(stage_id, workspace_id)
        try:
            # Read both canonical policies under the same lock so the generated
            # preview always represents one coherent candidate pair.
            with write_lock:
                code, raw = build_candidate_module(stage_id, request.spec, workspace_id)
                compile(code, f"policy_generated.py::{stage_id}", "exec")
        except PolicyValidationError as exc:
            return {"valid": False, "errors": [str(exc)]}
        except SyntaxError as exc:
            return {"valid": False, "errors": [f"Generated Python syntax error: {exc}"]}
        return {
            "valid": True,
            "errors": [],
            "policy_sha256": _sha256(raw),
            "generated_sha256": _sha256(code.encode("utf-8")),
        }

    @app.post("/api/policies/{stage_id}/preview")
    def preview_policy(
        stage_id: str, request: PolicyRequest, workspace_id: str | None = None
    ) -> dict[str, Any]:
        """Compile a proposed policy and return its deterministic Python preview."""
        policy_path(stage_id, workspace_id)
        try:
            with write_lock:
                code, raw = build_candidate_module(stage_id, request.spec, workspace_id)
                compile(code, f"policy_generated.py::{stage_id}", "exec")
        except PolicyValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "stage": stage_id,
            "code": code,
            "policy_sha256": _sha256(raw),
            "generated_sha256": _sha256(code.encode("utf-8")),
        }

    @app.post("/api/dev-candidates/build")
    def build_saved_dev_candidate(request: BuildCandidateRequest) -> dict[str, Any]:
        """Package saved policy/runtime source against an explicitly selected PROD baseline."""
        with write_lock:
            try:
                from modules.lifecycle.tools.dev_candidate import (
                    CandidateBuildError,
                    build_dev_candidate,
                )

                selected_workspace = request.workspace_id or get_default_workspace()["workspace_id"]
                return build_dev_candidate(
                    root, baseline_release=request.baseline_release, workspace_id=selected_workspace
                )
            except (CandidateBuildError, PolicyValidationError, OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/policies/{stage_id}")
    def save_policy(
        stage_id: str, request: PolicyRequest, workspace_id: str | None = None
    ) -> dict[str, Any]:
        """Save a validated policy using optimistic concurrency protection."""
        source_path = policy_path(stage_id, workspace_id)
        if request.expected_sha256 is None:
            raise HTTPException(
                status_code=428,
                detail="expected_sha256 is required for optimistic save protection.",
            )

        # Serialize the entire read/validate/compile/compare/write transaction.
        # This also prevents two local editors saving different stages from
        # generating policy_generated.py from an inconsistent pair of specs.
        with write_lock:
            try:
                current_bytes = source_path.read_bytes()
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"Cannot read current policy: {exc}"
                ) from exc
            current_sha = _sha256(current_bytes)
            if current_sha != request.expected_sha256:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "The policy changed after this editor loaded it. Reload before saving.",
                        "current_sha256": current_sha,
                    },
                )
            try:
                code, candidate_bytes = build_candidate_module(stage_id, request.spec, workspace_id)
                compile(code, "policy_generated.py", "exec")
            except PolicyValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            code_bytes = code.encode("utf-8")
            workspace_generated = source_path.parents[1] / "generated" / "policy_generated.py"
            old_generated = (
                workspace_generated.read_bytes() if workspace_generated.is_file() else None
            )
            _atomic_write(source_path, candidate_bytes)
            try:
                _atomic_write(workspace_generated, code_bytes)
            except Exception:
                _atomic_write(source_path, current_bytes)
                if old_generated is not None:
                    _atomic_write(workspace_generated, old_generated)
                raise

        return {
            "saved": True,
            "stage": stage_id,
            "sha256": _sha256(candidate_bytes),
            "generated_sha256": _sha256(code_bytes),
            "workspace_id": workspace_id or get_default_workspace()["workspace_id"],
            "message": "Strategy policy saved to its workspace. Core source and generated runtime files were not modified.",
        }

    dist_dir = root / "modules" / "policy-studio" / "frontend" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="studio-ui")
    else:

        @app.get("/", response_class=HTMLResponse)
        def studio_not_built() -> str:
            return """<!doctype html><html><head><title>UWflow Policy Studio</title></head>
            <body style='font:16px system-ui;max-width:720px;margin:64px auto;padding:0 24px'>
            <h1>UWflow Policy Studio API is running</h1>
            <p>The React interface is provided by the Dockerized Policy Studio frontend.
            Start both services from the repository root with
            <code>bash tools/guides/workflow/15-start-studio.sh</code>.</p>
            <p>API documentation: <a href='/docs'>/docs</a></p></body></html>"""

    return app


app = create_app()
