"""Validate and stage immutable Kestra Namespace Files bundles.

Only files declared in ``release-manifest.json`` are staged for upload. Local
bytecode caches and other unmanifested files can never leak into immutable
runtime/candidate/history-tools directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def stage_bundle(source: Path, destination: Path) -> list[str]:
    """Stage only manifest-declared files from an immutable bundle for Namespace Files upload."""
    source = source.resolve()
    destination = destination.resolve()
    manifest_path = source / "release-manifest.json"
    if not source.is_dir() or not manifest_path.is_file():
        raise ValueError(f"Bundle directory or manifest is missing: {source}")

    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read bundle manifest: {manifest_path}: {exc}") from exc

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Bundle manifest must contain a 'files' mapping")

    declared: set[str] = set()
    payloads: dict[str, bytes] = {}
    for relative_name, expected_sha in sorted(files.items()):
        if not isinstance(relative_name, str) or not isinstance(expected_sha, str):
            raise ValueError("Bundle manifest file names and SHA-256 values must be strings")
        relative = PurePosixPath(relative_name)
        if (
            not relative_name
            or relative_name in {".", ".."}
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in relative_name
            or ":" in relative_name
        ):
            raise ValueError(f"Unsafe path in bundle manifest: {relative_name!r}")
        if (
            not expected_sha
            or len(expected_sha) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha)
        ):
            raise ValueError(f"Invalid SHA-256 in bundle manifest for {relative_name!r}")

        path = source.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                f"Manifest-declared bundle file is missing or is a symlink: {relative_name}"
            )
        try:
            path.resolve().relative_to(source)
        except ValueError as exc:
            raise ValueError(f"Manifest path escapes bundle directory: {relative_name}") from exc
        content = path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(
                f"Bundle file checksum mismatch for {relative_name}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        declared.add(relative_name)
        payloads[relative_name] = content

    destination.mkdir(parents=True, exist_ok=False)
    for relative_name, content in payloads.items():
        target = destination.joinpath(*PurePosixPath(relative_name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (destination / "release-manifest.json").write_bytes(manifest_bytes)

    actual_local = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and path.name != "release-manifest.json"
    }
    excluded = sorted(actual_local - declared)
    return excluded


def main() -> int:
    """Stage or inspect the selected immutable bundle for Kestra Namespace Files publishing."""
    parser = argparse.ArgumentParser(description="Stage only manifest-verified Namespace Files")
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage", help="validate a bundle and copy only manifest files")
    stage.add_argument("--source", type=Path, required=True)
    stage.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    try:
        excluded = stage_bundle(args.source, args.destination)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Staged manifest-verified bundle: {args.destination}")
    if excluded:
        print(
            f"Excluded {len(excluded)} local file(s) not declared in the manifest "
            "(for example __pycache__ or editor artifacts)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
