"""Tests for manifest-verified staging of immutable Namespace Files bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.kestra.namespace_files import stage_bundle


def test_staging_copies_only_manifest_declared_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "__pycache__").mkdir()
    payload = b"print('runtime')\n"
    (source / "scripts/runtime.py").write_bytes(payload)
    (source / "__pycache__/runtime.cpython-312.pyc").write_bytes(b"compiled-cache")
    (source / "local-note.txt").write_text("not part of immutable bundle", encoding="utf-8")
    manifest = {
        "artifact_type": "test-bundle",
        "files": {"scripts/runtime.py": hashlib.sha256(payload).hexdigest()},
    }
    (source / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    destination = tmp_path / "staged"
    excluded = stage_bundle(source, destination)

    assert (destination / "scripts/runtime.py").read_bytes() == payload
    assert (destination / "release-manifest.json").is_file()
    assert not (destination / "__pycache__").exists()
    assert not (destination / "local-note.txt").exists()
    assert excluded == ["__pycache__/runtime.cpython-312.pyc", "local-note.txt"]


def test_staging_refuses_manifest_checksum_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "runtime.py").write_text("actual", encoding="utf-8")
    (source / "release-manifest.json").write_text(
        json.dumps({"files": {"runtime.py": "0" * 64}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="checksum mismatch"):
        stage_bundle(source, tmp_path / "staged")


def test_staging_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "release-manifest.json").write_text(
        json.dumps({"files": {"../escape.py": "0" * 64}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unsafe path"):
        stage_bundle(source, tmp_path / "staged")
