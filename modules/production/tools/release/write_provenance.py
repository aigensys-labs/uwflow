"""Write a local provenance record for an immutable approved release."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)


def write_provenance(release_id: str, repository_root: Path | str = ROOT) -> dict:
    """Write a deployment provenance record for an immutable approved release."""
    root = Path(repository_root).resolve()
    release = root / "var/releases/approved" / release_id
    manifest_path = release / "release-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Approved release manifest not found: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("release_id") != release_id:
        raise ValueError("Approved release manifest identity does not match its directory")
    provenance = {
        "project": "UWflow",
        "approved_release_id": release_id,
        "candidate_id": manifest.get("candidate_id"),
        "release_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "git_ref": os.getenv("GITHUB_REF", "local"),
        "git_sha": os.getenv("GITHUB_SHA", "UNAVAILABLE"),
        "repository": os.getenv("GITHUB_REPOSITORY", "UNAVAILABLE"),
    }
    output = root / "var/deployments/deployment-provenance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return provenance


def main() -> int:
    """Record deployment provenance for the specified approved release."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-id", default=os.getenv("UWFLOW_APPROVED_RELEASE_ID"), required=False
    )
    args = parser.parse_args()
    if not args.release_id:
        parser.error("--release-id or UWFLOW_APPROVED_RELEASE_ID is required")
    print(json.dumps(write_provenance(args.release_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
