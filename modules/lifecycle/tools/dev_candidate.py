"""Build an immutable, content-addressed DEV runtime and Kestra flow.

This tool never writes Core source, a production release, or Kestra. It packages a
selected workspace and its pinned Core runtime into var/artifacts/candidates/<candidate-id>/,
including the manual-only DEV flow and exact source templates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from typing import Any

import yaml

from core.underwriting.tools.runtime_bundle import RUNTIME_MODULES
from tools.policy.compiler import PolicyValidationError, compile_specs
from tools.kestra.yaml import dump_kestra_yaml
from tools.kestra.cli import nsfiles_upload_directory_command

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
DEV_NAMESPACE = "com.ai.credit.dev"


class CandidateBuildError(RuntimeError):
    """Raised when a DEV candidate cannot be built without overwriting content."""


def _resolve_baseline_release(value: str | None) -> str:
    baseline = value or os.environ.get("UWFLOW_BASELINE_RELEASE", "").strip()
    if not baseline:
        raise CandidateBuildError(
            "Set UWFLOW_BASELINE_RELEASE to the exact runtime currently deployed in PROD, "
            "or pass --baseline-release. Candidate creation will not guess the control release."
        )
    if re.fullmatch(r"\d+\.\d+\.\d+", baseline) is None:
        raise CandidateBuildError("Baseline release must be a semantic MAJOR.MINOR.PATCH version.")
    return baseline


def _baseline_flow_id(release: str, template_bytes: bytes) -> str:
    suffix = hashlib.sha256(template_bytes).hexdigest()[:10]
    return f"uwflow_dev_baseline_v{release.replace('.', '_')}_{suffix}"


def _python_tasks(tasks: list[dict[str, Any]]):
    for task in tasks:
        if task.get("type") in {
            "io.kestra.plugin.scripts.python.Script",
            "io.kestra.plugin.scripts.python.Commands",
        }:
            yield task
        yield from _python_tasks(task.get("tasks", []))
        yield from _python_tasks(task.get("then", []))
        yield from _python_tasks(task.get("else", []))


def _write_baseline_flow(
    root: Path,
    production_flow_path: Path,
    baseline_release: str,
    baseline_manifest_sha256: str,
) -> tuple[str, Path]:
    """Create/update a manual-only DEV flow over the explicitly selected baseline."""
    flow = yaml.safe_load(production_flow_path.read_text(encoding="utf-8"))
    template_bytes = production_flow_path.read_bytes()
    flow_id = _baseline_flow_id(baseline_release, template_bytes)
    runtime_path = f"runtime/releases/{baseline_release}"
    flow["id"] = flow_id
    flow["namespace"] = DEV_NAMESPACE
    flow["description"] = (
        f"UWflow DEV baseline flow pinned to immutable runtime {baseline_release}. "
        "Manual execution only. Uses the current reviewed orchestration contract while "
        "loading the exact baseline Python runtime."
    )
    labels = flow.setdefault("labels", {})
    labels["environment"] = "dev-baseline"
    labels["runtime-release"] = baseline_release
    labels["runtime-manifest-sha256"] = baseline_manifest_sha256
    labels.pop("system.readOnly", None)
    flow.pop("triggers", None)

    shared_namespace_files = {
        "enabled": True,
        "include": [f"{runtime_path}/**"],
        "ifExists": "FAIL",
    }
    for task in _python_tasks(flow.get("tasks", [])):
        task["namespaceFiles"] = shared_namespace_files
        env = task.setdefault("env", {})
        env["APP_RUNTIME_PATH"] = runtime_path
        env["APP_RUNTIME_MANIFEST_SHA256"] = baseline_manifest_sha256
        env["APP_RUNTIME_ARTIFACT_TYPE"] = "uwflow-kestra-runtime"

    destination = root / "var" / "artifacts" / "baselines" / f"{flow_id}.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = dump_kestra_yaml(flow).encode("utf-8")
    if destination.exists() and destination.read_bytes() != rendered:
        raise CandidateBuildError(f"Refusing to overwrite immutable baseline flow: {destination}")
    if not destination.exists():
        destination.write_bytes(rendered)
    return flow_id, destination


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _source_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "working-tree"


def _source_tree_status(root: Path) -> str:
    try:
        # Workspace and artifact directories are intentionally mutable/untracked;
        # promotion eligibility concerns the protected Core source tree only.
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "core/"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return "clean" if not result.stdout.strip() else "dirty"
    except (OSError, subprocess.SubprocessError):
        return "unverified"


def _write_immutable_directory(target: Path, files: dict[str, bytes]) -> None:
    if target.exists():
        for relative, content in files.items():
            path = target / relative
            if not path.is_file() or path.read_bytes() != content:
                raise CandidateBuildError(
                    f"Content-addressed candidate path already exists with different content: {path}"
                )
        actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
        if actual != set(files):
            raise CandidateBuildError(
                f"Candidate path contains unexpected files: {sorted(actual ^ set(files))}"
            )
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for relative, content in files.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _candidate_flow(
    production_flow_path: Path,
    *,
    candidate_id: str,
    manifest_sha256: str,
    flow_template_release: str,
) -> bytes:
    """Render a manual-only DEV flow over the immutable candidate bundle."""
    flow = yaml.safe_load(production_flow_path.read_text(encoding="utf-8"))
    expected_release = str(flow.get("labels", {}).get("runtime-release", ""))
    if not expected_release:
        raise CandidateBuildError(
            "Selected production flow template has no runtime-release identity"
        )

    flow["id"] = f"uwflow_dev_candidate_{candidate_id.removeprefix('dev-')}"
    flow["namespace"] = DEV_NAMESPACE
    flow["description"] = (
        f"UWflow DEV candidate {candidate_id}. Manual execution only; never production. "
        "The flow uses the reviewed orchestration contract and loads the exact immutable "
        "content-addressed candidate bundle."
    )
    labels = flow.setdefault("labels", {})
    labels["environment"] = "dev-candidate"
    labels["runtime-release"] = candidate_id
    labels["runtime-manifest-sha256"] = manifest_sha256
    labels.pop("system.readOnly", None)
    flow.pop("triggers", None)

    runtime_path = f"runtime/candidates/{candidate_id}"
    shared_namespace_files = {
        "enabled": True,
        "include": [f"{runtime_path}/**"],
        "ifExists": "FAIL",
    }
    for task in _python_tasks(flow.get("tasks", [])):
        task["namespaceFiles"] = shared_namespace_files
        env = task.setdefault("env", {})
        env["APP_RUNTIME_PATH"] = runtime_path
        env["APP_RUNTIME_MANIFEST_SHA256"] = manifest_sha256
        env["APP_RUNTIME_ARTIFACT_TYPE"] = "uwflow-kestra-runtime"

    return dump_kestra_yaml(flow).encode("utf-8")


def build_dev_candidate(
    repository_root: Path | str = ROOT,
    *,
    baseline_release: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Build an immutable DEV candidate from a saved workspace and verified baseline."""
    root = Path(repository_root).resolve()
    baseline_release = _resolve_baseline_release(baseline_release)
    from modules.lifecycle.workspaces import WorkspaceStore

    workspace_store = WorkspaceStore(root)
    workspace = (
        workspace_store.get(workspace_id) if workspace_id else workspace_store.ensure_default()
    )
    workspace_id = workspace["workspace_id"]
    policies_dir = root / "var" / "workspaces" / "strategies" / workspace_id / "policy-specs"
    runtime_relative = workspace.get("core_runtime", {}).get("runtime_source_path")
    flow_template_relative = workspace.get("flow_template_source_path")
    if not isinstance(runtime_relative, str) or not runtime_relative:
        raise CandidateBuildError("Workspace has no explicit Core runtime source path")
    if not isinstance(flow_template_relative, str) or not flow_template_relative:
        raise CandidateBuildError("Workspace has no explicit production-flow template source path")
    runtime_source = (root / runtime_relative).resolve()
    if root not in runtime_source.parents or not runtime_source.is_dir():
        raise CandidateBuildError(
            "Workspace Core runtime source is missing or escapes repository root"
        )
    flow_template_source = (root / flow_template_relative).resolve()
    if root not in flow_template_source.parents or not flow_template_source.is_file():
        raise CandidateBuildError(
            "Workspace production-flow template source is missing or escapes repository root"
        )
    catalog = root / "core" / "underwriting" / "policies" / "schema" / "fields.json"
    generated_path = (
        root
        / "var"
        / "workspaces"
        / "strategies"
        / workspace_id
        / "generated"
        / "policy_generated.py"
    )
    approved_release = root / "var" / "releases" / "approved" / baseline_release
    core_baseline = (
        root / "core" / "kestra" / "namespace-files" / "runtime" / "releases" / baseline_release
    )
    if approved_release.exists():
        if (
            not (approved_release / "runtime").is_dir()
            or not (approved_release / "production-flow.yaml").is_file()
        ):
            raise CandidateBuildError(
                f"Approved release {baseline_release} is incomplete; refusing to fall back to a Core snapshot."
            )
        baseline_bundle = approved_release / "runtime"
        baseline_bundle_relative = (
            Path("var") / "releases" / "approved" / baseline_release / "runtime"
        )
        baseline_flow_path = approved_release / "production-flow.yaml"
        baseline_source_type = "approved-release"
    elif core_baseline.is_dir():
        # A checked-in Core runtime snapshot is the explicit bootstrap/reference baseline
        # before the first governed v2 production release exists. Module artifact lookup
        # never searches alternative or retired module-owned directories.
        baseline_bundle = core_baseline
        baseline_bundle_relative = (
            Path("core") / "kestra" / "namespace-files" / "runtime" / "releases" / baseline_release
        )
        baseline_flow_path = (
            root / "core" / "kestra" / "flows" / "uwflow_production_underwriting.yaml"
        )
        baseline_source_type = "core-runtime-snapshot"
    else:
        raise CandidateBuildError(
            f"Baseline {baseline_release} is neither an approved release nor a checked-in Core runtime snapshot."
        )
    production_flow_path = flow_template_source

    if not baseline_bundle.is_dir():
        raise CandidateBuildError(f"Missing baseline runtime release: {baseline_bundle}")
    if not (baseline_bundle / "release-manifest.json").is_file():
        raise CandidateBuildError("Baseline runtime has no release manifest")
    baseline_manifest = json.loads(
        (baseline_bundle / "release-manifest.json").read_text(encoding="utf-8")
    )
    if baseline_manifest.get("release_version") != baseline_release:
        raise CandidateBuildError(
            "The selected baseline directory and its release-manifest version do not match."
        )
    baseline_manifest_sha256 = _sha256((baseline_bundle / "release-manifest.json").read_bytes())
    if not production_flow_path.is_file():
        raise CandidateBuildError(
            f"Missing selected production flow template: {production_flow_path}"
        )
    if not baseline_flow_path.is_file():
        raise CandidateBuildError(f"Missing baseline production flow: {baseline_flow_path}")

    try:
        generated, policy_sources = compile_specs(policies_dir, catalog)
    except PolicyValidationError as exc:
        raise CandidateBuildError(f"Saved canonical policy validation failed: {exc}") from exc
    if generated_path.is_file() and generated_path.read_text(encoding="utf-8") != generated:
        raise CandidateBuildError(
            "Workspace generated policy is stale. Save or recompile the workspace before building."
        )

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    flow_template_version = str(project["version"])
    common = (root / "core" / "python" / "runtime" / "common.py").read_text(encoding="utf-8")
    aidflow = (root / "core" / "python" / "runtime" / "aidflow_scoring.py").read_text(
        encoding="utf-8"
    )
    uwflow = (root / "core" / "python" / "runtime" / "uwflow_engine.py").read_text(encoding="utf-8")
    policy_match = re.search(r'^POLICY_VERSION\s*=\s*["\']([^"\']+)', common, re.M)
    uwflow_match = re.search(r'^UWFLOW_VERSION\s*=\s*["\']([^"\']+)', uwflow, re.M)
    aidflow_match = re.search(r'^PROFILE_SCORE_VERSION\s*=\s*["\']([^"\']+)', aidflow, re.M)
    if not all((policy_match, uwflow_match, aidflow_match)):
        raise CandidateBuildError("Could not extract runtime engine/model version metadata")
    engine_versions = {
        "policy_version": policy_match.group(1),
        "uwflow_engine_version": uwflow_match.group(1),
        "aidflow_model_version": aidflow_match.group(1),
    }
    runtime_files = {name: (runtime_source / name).read_bytes() for name in RUNTIME_MODULES}
    policy_filenames = {
        "stage_1_hard_gates": "stage1_hard_gates.json",
        "stage_3_source_plan": "stage3_source_plan.json",
    }
    policy_files = {
        f"policy-specs/{policy_filenames[name]}": content
        for name, content in policy_sources.items()
    }
    source_ref = _source_commit(root)
    core_runtime_hashes = {
        name: _sha256(content) for name, content in sorted(runtime_files.items())
    }
    fingerprint = hashlib.sha256()
    fingerprint.update(
        f"based-on={baseline_release}\nbaseline-source={baseline_source_type}\n".encode()
    )
    # Provenance is part of candidate identity. A bundle built from an exported
    # working tree must not collide with the same files built from a committed tree.
    fingerprint.update(f"source-ref={source_ref}\nworkspace={workspace_id}\n".encode())
    fingerprint.update(f"core-source-status={_source_tree_status(root)}\n".encode())
    for name, content in sorted(runtime_files.items()):
        fingerprint.update(name.encode() + b"\0" + content + b"\0")
    for name, content in sorted(policy_files.items()):
        fingerprint.update(name.encode() + b"\0" + content + b"\0")
    # The base flow is also part of the candidate identity: changes to the
    # Kestra wiring must produce a new candidate even if Python is unchanged.
    fingerprint.update(production_flow_path.read_bytes())
    fingerprint.update(baseline_flow_path.read_bytes())
    candidate_id = f"dev-{fingerprint.hexdigest()[:16]}"

    manifest = {
        "artifact_type": "uwflow-kestra-runtime",
        "manifest_format": 1,
        "release_version": candidate_id,
        "source_ref": source_ref,
        "environment": "DEV",
        "workspace_id": workspace_id,
        "workspace_source": workspace.get("source", {}),
        "core_runtime": {
            "platform_version": workspace.get("core_runtime", {}).get(
                "platform_version", flow_template_version
            ),
            "module_hashes": core_runtime_hashes,
            "runtime_source_path": workspace.get("core_runtime", {}).get("runtime_source_path"),
        },
        "baseline_flow_sha256": _sha256(baseline_flow_path.read_bytes()),
        "core_source_tree_status": _source_tree_status(root),
        "production_flow_template_sha256": _sha256(production_flow_path.read_bytes()),
        "candidate_id": candidate_id,
        "based_on_production_release": baseline_release,
        "baseline_source_type": baseline_source_type,
        **engine_versions,
        "files": {name: _sha256(content) for name, content in sorted(runtime_files.items())},
        "policy_specs": {
            name.removeprefix("policy-specs/"): _sha256(content)
            for name, content in sorted(policy_files.items())
        },
    }
    manifest_bytes = _json_bytes(manifest)
    manifest_sha256 = _sha256(manifest_bytes)

    bundle_files = {
        **runtime_files,
        **policy_files,
        "release-manifest.json": manifest_bytes,
        "production-flow-template.yaml": production_flow_path.read_bytes(),
    }
    bundle_relative = Path("var") / "artifacts" / "candidates" / candidate_id
    bundle_path = root / bundle_relative

    baseline_flow_id, baseline_flow_path = _write_baseline_flow(
        root, baseline_flow_path, baseline_release, baseline_manifest_sha256
    )

    candidate_flow_bytes = _candidate_flow(
        production_flow_path,
        candidate_id=candidate_id,
        manifest_sha256=manifest_sha256,
        flow_template_release=flow_template_version,
    )
    candidate_flow_id = f"uwflow_dev_candidate_{candidate_id.removeprefix('dev-')}"
    candidate_flow_relative = bundle_relative / "candidate-flow.yaml"
    candidate_flow_path = root / candidate_flow_relative
    if candidate_flow_path.exists() and candidate_flow_path.read_bytes() != candidate_flow_bytes:
        raise CandidateBuildError(
            f"Refusing to overwrite existing candidate flow: {candidate_flow_path}"
        )
    bundle_files["candidate-flow.yaml"] = candidate_flow_bytes
    artifact_manifest = {
        "artifact_format": 1,
        "candidate_id": candidate_id,
        "release_manifest_sha256": manifest_sha256,
        "files": {name: _sha256(content) for name, content in sorted(bundle_files.items())},
    }
    bundle_files["candidate-artifact-manifest.json"] = _json_bytes(artifact_manifest)
    _write_immutable_directory(bundle_path, bundle_files)

    baseline_flow_relative = baseline_flow_path.relative_to(root)
    candidate_bundle_upload = nsfiles_upload_directory_command(
        DEV_NAMESPACE,
        f"./{bundle_relative.as_posix()}",
        f"runtime/candidates/{candidate_id}",
    )
    setup_commands = "\n\n".join(
        [
            f"# DEV baseline selected from the verified live PROD release: {baseline_release}.",
            nsfiles_upload_directory_command(
                DEV_NAMESPACE,
                f"./{baseline_bundle_relative.as_posix()}",
                f"runtime/releases/{baseline_release}",
            ),
            f"kestractl flows validate ./{baseline_flow_relative.as_posix()}",
            f"kestractl flows deploy ./{baseline_flow_relative.as_posix()} --override --fail-fast",
        ]
    )
    candidate_commands = "\n\n".join(
        [
            "# Upload this immutable candidate and deploy its manual-only DEV flow.",
            candidate_bundle_upload,
            f"kestractl flows validate ./{candidate_flow_relative.as_posix()}",
            f"kestractl flows deploy ./{candidate_flow_relative.as_posix()} --override --fail-fast",
        ]
    )
    replay_command = (
        "python -m tools.history.replay.dev_cohort "
        f"--baseline-flow {baseline_flow_id} "
        f"--candidate-flow {candidate_flow_id} "
        "--cohort modules/history/examples/cohorts/dev_cohort.sample.jsonl "
        f"--output var/reports/dev-replay-{candidate_id}.csv"
    )

    return {
        "candidate_id": candidate_id,
        "based_on_production_release": baseline_release,
        "dev_namespace": DEV_NAMESPACE,
        "baseline_flow_id": baseline_flow_id,
        "candidate_flow_id": candidate_flow_id,
        "bundle_relative_path": bundle_relative.as_posix(),
        "flow_relative_path": candidate_flow_relative.as_posix(),
        "manifest_sha256": manifest_sha256,
        "setup_commands": setup_commands,
        "candidate_commands": candidate_commands,
        "replay_command": replay_command,
    }


def main() -> int:
    """Build a DEV candidate from the selected workspace using the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Build an immutable content-addressed UWflow DEV candidate"
    )
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    parser.add_argument("--baseline-release", help="Exact runtime currently deployed in PROD")
    parser.add_argument("--workspace-id", help="Strategy workspace to package")
    args = parser.parse_args()
    result = build_dev_candidate(
        baseline_release=args.baseline_release, workspace_id=args.workspace_id
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Built {result['candidate_id']}")
        print(f"Manifest SHA-256: {result['manifest_sha256']}")
        print("\n" + result["setup_commands"])
        print("\n" + result["candidate_commands"])
        print("\nReplay with:\n" + result["replay_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
