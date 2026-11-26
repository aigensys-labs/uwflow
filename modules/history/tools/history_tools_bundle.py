"""Build an immutable Namespace Files bundle for historical replay tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def source_files(repository_root: Path | str | None = None) -> dict[str, bytes]:
    """Collect the exact source files declared in the History tooling bundle."""
    root = Path(repository_root).resolve() if repository_root is not None else ROOT
    package_root = root / "modules" / "history" / "python" / "uwflow_history"
    tool_files = {
        "run_history_batch.py": root / "tools" / "history" / "replay" / "run_batch.py",
        "validate_history_dataset.py": root
        / "tools"
        / "history"
        / "datasets"
        / "validate_dataset.py",
        "compare_history_batches.py": root / "tools" / "history" / "replay" / "compare_batches.py",
        "impact_report.py": root / "modules" / "reporting" / "tools" / "impact_report.py",
    }
    files: dict[str, bytes] = {}
    if not package_root.is_dir():
        raise FileNotFoundError(f"History source package not found: {package_root}")
    for path in sorted(package_root.rglob("*.py")):
        files[(Path("scripts") / "uwflow_history" / path.relative_to(package_root)).as_posix()] = (
            path.read_bytes()
        )
    for name, path in tool_files.items():
        if not path.is_file():
            raise FileNotFoundError(f"History tooling source is missing: {path}")
        files[(Path("tools") / name).as_posix()] = path.read_bytes()
    return files


def build_bundle(
    *, check: bool = False, repository_root: Path | str | None = None
) -> tuple[str, Path]:
    """Build or verify the immutable content-addressed History tooling bundle."""
    root = Path(repository_root).resolve() if repository_root is not None else ROOT
    target_root = root / "var" / "artifacts" / "tool-bundles" / "history"
    files = source_files(repository_root=root)
    digest_material = "\n".join(
        f"{name}:{_sha(content)}" for name, content in sorted(files.items())
    )
    bundle_id = f"ht-{_sha(digest_material.encode())[:16]}"
    target = target_root / bundle_id
    manifest = {
        "artifact_type": "uwflow-history-tools",
        "manifest_format": 1,
        "bundle_id": bundle_id,
        "files": {name: _sha(content) for name, content in sorted(files.items())},
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

    if check:
        if not target.is_dir():
            raise SystemExit(f"Missing immutable history tooling bundle: {target}")
        for name, content in files.items():
            actual = target / name
            if not actual.is_file() or actual.read_bytes() != content:
                raise SystemExit(f"History tooling bundle differs from source: {actual}")
        actual_manifest = target / "release-manifest.json"
        if not actual_manifest.is_file() or actual_manifest.read_bytes() != manifest_bytes:
            raise SystemExit(f"History tooling manifest differs from expected: {actual_manifest}")
        print(f"Verified immutable history tooling bundle {bundle_id} ({len(files)} files)")
        return bundle_id, target

    if target.exists():
        # Content-derived IDs mean an existing bundle must be identical.
        build_bundle(check=True)
        return bundle_id, target

    target_root.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=False)
    try:
        for name, content in files.items():
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (target / "release-manifest.json").write_bytes(manifest_bytes)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    print(f"Created immutable history tooling bundle {bundle_id}: {target}")
    return bundle_id, target


def main() -> int:
    """Build/reuse the History tooling bundle or verify it in check-only mode."""
    parser = argparse.ArgumentParser(
        description="Build or verify the Kestra Namespace Files history tooling"
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    bundle_id, _ = build_bundle(check=args.check)
    print(f"HISTORY_TOOLS_BUNDLE_ID={bundle_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
