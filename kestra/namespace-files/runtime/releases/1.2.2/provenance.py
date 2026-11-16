"""Verify an immutable UWflow runtime release bundle and describe its provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


def load_runtime_provenance(
    release_root: str | Path, expected_manifest_sha256: str | None = None
) -> dict[str, Any]:
    """Validate every file against release-manifest.json and return audit metadata.

    The release directory is expected to be mounted from Kestra Namespace Files.
    Any missing, unexpected, or modified Python module causes a hard failure.
    """
    root = Path(release_root).resolve()
    manifest_path = root / "release-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Missing runtime release manifest: {manifest_path}")

    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 and manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "Runtime release manifest checksum does not match the flow's pinned digest"
        )
    manifest = json.loads(manifest_bytes)
    file_hashes = manifest.get("files")
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise RuntimeError("Runtime release manifest has no file checksums")

    expected_files = set(file_hashes)
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*.py")}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        raise RuntimeError(
            f"Runtime release file set mismatch; missing={missing}, unexpected={unexpected}"
        )

    for relative_name, expected_hash in file_hashes.items():
        relative = PurePosixPath(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe path in runtime release manifest: {relative_name}")
        candidate = (root / Path(*relative.parts)).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise RuntimeError(f"Missing or unsafe runtime release file: {relative_name}")
        actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError(f"Runtime release checksum mismatch: {relative_name}")

    return {
        "integrity_status": "VERIFIED",
        "runtime_release": manifest.get("release_version"),
        "source_ref": manifest.get("source_ref"),
        "policy_version": manifest.get("policy_version"),
        "uwflow_engine_version": manifest.get("uwflow_engine_version"),
        "aidflow_model_version": manifest.get("aidflow_model_version"),
        "release_manifest_sha256": manifest_sha256,
        "runtime_file_count": len(file_hashes),
        "runtime_file_sha256": dict(sorted(file_hashes.items())),
    }
