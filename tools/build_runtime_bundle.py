from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MODULES = (
    "common.py",
    "bootstrap.py",
    "hard_gates.py",
    "bureau_client.py",
    "alternative_data.py",
    "aidflow_scoring.py",
    "uwflow_engine.py",
    "report_renderer.py",
    "provenance.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_project() -> tuple[str, dict[str, str]]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = str(project["version"])
    common = (ROOT / "scripts" / "common.py").read_text(encoding="utf-8")
    aidflow = (ROOT / "scripts" / "aidflow_scoring.py").read_text(encoding="utf-8")
    uwflow = (ROOT / "scripts" / "uwflow_engine.py").read_text(encoding="utf-8")
    policy = re.search(r'^POLICY_VERSION\s*=\s*["\']([^"\']+)', common, re.M)
    uwflow_version = re.search(r'^UWFLOW_VERSION\s*=\s*["\']([^"\']+)', uwflow, re.M)
    aidflow_version = re.search(r'^PROFILE_SCORE_VERSION\s*=\s*["\']([^"\']+)', aidflow, re.M)
    if not all((policy, uwflow_version, aidflow_version)):
        raise RuntimeError("Could not extract engine versions from runtime source modules")
    return version, {
        "policy_version": policy.group(1),
        "uwflow_engine_version": uwflow_version.group(1),
        "aidflow_model_version": aidflow_version.group(1),
    }


def expected_payload() -> tuple[str, dict[str, bytes], bytes]:
    version, engine_versions = load_project()
    files = {name: (ROOT / "scripts" / name).read_bytes() for name in RUNTIME_MODULES}
    manifest = {
        "artifact_type": "uwflow-kestra-runtime",
        "manifest_format": 1,
        "release_version": version,
        "source_ref": f"v{version}",
        **engine_versions,
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return version, files, manifest_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the immutable Kestra runtime bundle")
    parser.add_argument("--check", action="store_true", help="Verify the checked-in release matches scripts/")
    parser.add_argument("--output-root", type=Path, default=ROOT / "kestra" / "namespace-files" / "runtime" / "releases")
    args = parser.parse_args()

    version, files, manifest_bytes = expected_payload()
    target = args.output_root / version

    if args.check:
        if not target.is_dir():
            raise SystemExit(f"Missing checked-in runtime release: {target}")
        for name, expected in files.items():
            actual_path = target / name
            if not actual_path.is_file() or actual_path.read_bytes() != expected:
                raise SystemExit(f"Runtime release differs from source: {actual_path}")
        manifest_path = target / "release-manifest.json"
        if not manifest_path.is_file() or manifest_path.read_bytes() != manifest_bytes:
            raise SystemExit(f"Runtime release manifest differs from expected: {manifest_path}")
        expected_names = set(files) | {"release-manifest.json"}
        actual_names = {item.name for item in target.iterdir() if item.is_file()}
        if actual_names != expected_names:
            raise SystemExit(f"Unexpected runtime bundle files: {sorted(actual_names ^ expected_names)}")
        print(f"Verified immutable runtime release v{version} ({len(files)} modules)")
        return 0

    if target.exists():
        raise SystemExit(
            f"Refusing to overwrite existing immutable release {target}. "
            "Bump project version before creating a new release."
        )
    target.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        (target / name).write_bytes(content)
    (target / "release-manifest.json").write_bytes(manifest_bytes)
    print(f"Created runtime release v{version}: {target}")
    print(f"Manifest SHA-256: {sha256(target / 'release-manifest.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
