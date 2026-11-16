from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from provenance import load_runtime_provenance

RELEASE_ROOT = ROOT / "kestra" / "namespace-files" / "runtime" / "releases" / "1.2.2"


def test_runtime_release_manifest_verifies_all_files() -> None:
    manifest = json.loads((RELEASE_ROOT / "release-manifest.json").read_text(encoding="utf-8"))
    result = load_runtime_provenance(RELEASE_ROOT)

    assert result["integrity_status"] == "VERIFIED"
    assert result["runtime_release"] == "1.2.2"
    assert result["runtime_file_count"] == len(manifest["files"]) == 8
    assert len(result["release_manifest_sha256"]) == 64


def test_runtime_release_rejects_wrong_pinned_manifest_hash() -> None:
    with pytest.raises(RuntimeError, match="pinned digest"):
        load_runtime_provenance(RELEASE_ROOT, expected_manifest_sha256="0" * 64)


def test_runtime_release_rejects_modified_module(tmp_path: Path) -> None:
    for source in RELEASE_ROOT.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_bytes(source.read_bytes())
    with (tmp_path / "uwflow_engine.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# unexpected runtime modification\n")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        load_runtime_provenance(tmp_path)
