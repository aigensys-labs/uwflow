"""Tests for Kestra task bootstrap and immutable Core runtime verification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "core" / "docker" / "bootstrap.py"


class _FakeKestra:
    @staticmethod
    def outputs(_outputs: dict) -> None:
        return None


def _load_bootstrap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, tamper: bool = False):
    working_dir = tmp_path / "task"
    runtime_root = working_dir / "runtime" / "releases" / "2.0.0"
    runtime_root.mkdir(parents=True)
    module_bytes = b"VALUE = 'verified'\n"
    (runtime_root / "example_module.py").write_bytes(module_bytes)
    files = {"example_module.py": hashlib.sha256(module_bytes).hexdigest()}
    manifest = {
        "artifact_type": "uwflow-kestra-runtime",
        "manifest_format": 1,
        "release_version": "2.0.0",
        "files": files,
        "policy_specs": {},
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    manifest_path = runtime_root / "release-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    expected_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if tamper:
        (runtime_root / "example_module.py").write_text("VALUE = 'tampered'\n", encoding="utf-8")

    for key, value in {
        "WORKING_DIR": str(working_dir),
        "APP_RUNTIME_PATH": "runtime/releases/2.0.0",
        "APP_RUNTIME_MANIFEST_SHA256": expected_sha,
        "APP_TASK_IMAGE": "ai/uwflow-core-runtime:2.0.0",
        "APP_RUNTIME_ARTIFACT_TYPE": "uwflow-kestra-runtime",
    }.items():
        monkeypatch.setenv(key, value)

    fake_module = types.ModuleType("kestra")
    fake_module.Kestra = _FakeKestra
    monkeypatch.setitem(sys.modules, "kestra", fake_module)
    module_spec = importlib.util.spec_from_file_location(
        f"uwflow_bootstrap_test_{id(tmp_path)}", BOOTSTRAP
    )
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module, runtime_root


def test_bootstrap_exposes_validated_context_and_adds_runtime_to_import_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, runtime_root = _load_bootstrap(tmp_path, monkeypatch)

    assert module.ctx.runtime_root == runtime_root
    assert module.ctx.runtime_manifest_sha256
    assert module.ctx.task_image == "ai/uwflow-core-runtime:2.0.0"
    assert module.ctx.task_runner == "Docker"
    assert module.ctx.json is json
    assert module.ctx.os is __import__("os")
    assert module.ctx.sys is sys
    assert module.ctx.Path is Path
    assert str(runtime_root) == sys.path[0]
    import example_module

    assert example_module.VALUE == "verified"


def test_bootstrap_rejects_runtime_bundle_file_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _load_bootstrap(tmp_path, monkeypatch, tamper=True)


def test_bootstrap_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    working_dir = tmp_path / "task"
    working_dir.mkdir()
    fake_module = types.ModuleType("kestra")
    fake_module.Kestra = _FakeKestra
    monkeypatch.setitem(sys.modules, "kestra", fake_module)
    monkeypatch.setenv("WORKING_DIR", str(working_dir))
    monkeypatch.setenv("APP_RUNTIME_PATH", "../outside")
    monkeypatch.setenv("APP_RUNTIME_MANIFEST_SHA256", "0" * 64)
    monkeypatch.setenv("APP_TASK_IMAGE", "ai/uwflow-core-runtime:2.0.0")
    monkeypatch.setenv("APP_RUNTIME_ARTIFACT_TYPE", "uwflow-kestra-runtime")
    namespace: dict[str, object] = {}
    source = BOOTSTRAP.read_text(encoding="utf-8")
    exec(
        compile(
            source.split("# Deliberately create one context per Python task process.")[0],
            str(BOOTSTRAP),
            "exec",
        ),
        namespace,
    )
    context_type = namespace["_TaskContext"]
    error_type = namespace["BootstrapConfigurationError"]
    with pytest.raises(error_type, match="safe path"):
        context_type()


def test_bootstrap_requires_the_current_runtime_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working_dir = tmp_path / "task"
    working_dir.mkdir()
    fake_module = types.ModuleType("kestra")
    fake_module.Kestra = _FakeKestra
    monkeypatch.setitem(sys.modules, "kestra", fake_module)
    monkeypatch.setenv("WORKING_DIR", str(working_dir))
    for key in (
        "APP_RUNTIME_PATH",
        "APP_RUNTIME_MANIFEST_SHA256",
        "APP_TASK_IMAGE",
        "APP_RUNTIME_ARTIFACT_TYPE",
    ):
        monkeypatch.delenv(key, raising=False)
    namespace: dict[str, object] = {}
    source = BOOTSTRAP.read_text(encoding="utf-8")
    prefix = source.split("# Deliberately create one context per Python task process.")[0]
    exec(compile(prefix, str(BOOTSTRAP), "exec"), namespace)
    context_type = namespace["_TaskContext"]
    error_type = namespace["BootstrapConfigurationError"]
    with pytest.raises(error_type, match="APP_RUNTIME_PATH"):
        context_type()
