from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
version = str(project["version"])
manifest = (
    ROOT
    / "kestra"
    / "namespace-files"
    / "runtime"
    / "releases"
    / version
    / "release-manifest.json"
)
provenance = {
    "project": "UWflow",
    "runtime_release": version,
    "git_ref": os.getenv("GITHUB_REF", "local"),
    "git_sha": os.getenv("GITHUB_SHA", "UNAVAILABLE"),
    "repository": os.getenv("GITHUB_REPOSITORY", "UNAVAILABLE"),
    "release_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
}

json_path = ROOT / "deployment-provenance.json"
json_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
summary_path = os.getenv("GITHUB_STEP_SUMMARY")
if summary_path:
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n### UWflow deployment provenance\n\n")
        for key, value in provenance.items():
            handle.write(f"- **{key}:** `{value}`\n")
print(json.dumps(provenance, indent=2))
