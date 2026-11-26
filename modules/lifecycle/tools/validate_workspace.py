"""Validate a saved strategy workspace without modifying Core or workspace files."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from modules.lifecycle.workspaces import WorkspaceStore
from tools.policy.compiler import compile_specs

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())


def validate_workspace(repository_root: Path | str = ROOT, workspace_id: str | None = None) -> dict:
    """Validate workspace metadata, source ancestry and supported policy specifications."""
    root = Path(repository_root).resolve()
    store = WorkspaceStore(root)
    workspace = store.get(workspace_id) if workspace_id else store.ensure_default()
    policy_dir = root / "var/workspaces/strategies" / workspace["workspace_id"] / "policy-specs"
    catalog = root / "core/underwriting/policies/schema/fields.json"
    generated, sources = compile_specs(policy_dir, catalog)
    generated_path = (
        root
        / "var/workspaces/strategies"
        / workspace["workspace_id"]
        / "generated/policy_generated.py"
    )
    if generated_path.is_file() and generated_path.read_text(encoding="utf-8") != generated:
        raise ValueError("Workspace generated policy is stale; save or recompile the workspace")
    return {
        "workspace_id": workspace["workspace_id"],
        "name": workspace["name"],
        "policy_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()},
        "generated_sha256": hashlib.sha256(generated.encode()).hexdigest(),
        "valid": True,
    }


def main() -> int:
    """Validate one workspace without modifying its contents."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id")
    args = parser.parse_args()
    print(json.dumps(validate_workspace(workspace_id=args.workspace_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
