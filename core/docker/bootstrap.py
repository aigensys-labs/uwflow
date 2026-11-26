"""Small, strict runtime adapter for Python tasks executed by Kestra.

This is part of UWflow Core. It contains no underwriting logic: application
modules supply immutable runtime bundles and declare their artifact type in
the flow environment. The Core adapter verifies those bundles before import.

Task scripts start with ``from bootstrap import ctx`` and then contain only
application-specific work.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, TypeVar


class BootstrapConfigurationError(RuntimeError):
    """Raised when a Kestra task's runtime environment is incomplete or unsafe."""


JsonType = TypeVar("JsonType")


class _TaskContext:
    """Validated access to Kestra, task environment and the pinned runtime bundle."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        kestra_client: Any | None = None,
        python_version: str | None = None,
        python_path: list[str] | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        if kestra_client is None:
            try:
                kestra_module = importlib.import_module("kestra")
                kestra_client = kestra_module.Kestra
            except (ImportError, AttributeError) as exc:
                raise BootstrapConfigurationError(
                    "The Kestra Python helper is unavailable. Build/use a compatible Core task image; "
                    "do not install dependencies inside the task."
                ) from exc
        self.kestra = kestra_client
        # Deliberate, explicit convenience exports for short Kestra task scripts.
        # These are module references, not wrappers or mutable global state.
        self.json = json
        self.os = os
        self.sys = sys
        self.Path = Path

        self.python_version = python_version or sys.version.split()[0]
        self.task_runner = "Docker"
        self.task_runner_type = "io.kestra.plugin.scripts.runner.docker.Docker"

        self.working_dir = self._resolve_working_dir()
        # Core uses one explicit runtime contract for every Kestra execution.
        self.runtime_path = self.env_str("APP_RUNTIME_PATH")
        self.runtime_root = self._resolve_runtime_root(self.runtime_path)
        self.runtime_manifest_sha256 = self.env_str("APP_RUNTIME_MANIFEST_SHA256")
        self.task_image = self.env_str("APP_TASK_IMAGE")
        self.runtime_artifact_type = self.env_str("APP_RUNTIME_ARTIFACT_TYPE")

        self._verify_runtime_bundle()
        target_path = sys.path if python_path is None else python_path
        runtime_path = str(self.runtime_root)
        if runtime_path in target_path:
            target_path.remove(runtime_path)
        target_path.insert(0, runtime_path)

    def env_str(
        self,
        name: str,
        *,
        default: str | None = None,
        required: bool = True,
    ) -> str:
        """Return a non-empty canonical environment variable without exposing secrets."""
        value = self._environ.get(name)
        if value is None or not value.strip():
            if default is not None:
                return default
            if required:
                raise BootstrapConfigurationError(
                    f"Required Kestra task environment variable {name!r} is missing or empty."
                )
            return ""
        return value.strip()

    def env_json(
        self,
        name: str,
        *,
        expected_type: type[JsonType] | tuple[type[Any], ...] | None = None,
    ) -> Any | JsonType:
        """Parse a JSON environment variable and optionally enforce its top-level type."""
        raw_value = self.env_str(name)
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise BootstrapConfigurationError(
                f"Kestra task environment variable {name!r} is not valid JSON "
                f"(line {exc.lineno}, column {exc.colno})."
            ) from exc
        if expected_type is not None and not isinstance(value, expected_type):
            expected_name = (
                ", ".join(item.__name__ for item in expected_type)
                if isinstance(expected_type, tuple)
                else expected_type.__name__
            )
            raise BootstrapConfigurationError(
                f"Kestra task environment variable {name!r} must decode to {expected_name}; "
                f"received {type(value).__name__}."
            )
        return value

    def _resolve_working_dir(self) -> Path:
        raw_path = self.env_str("WORKING_DIR")
        working_dir = Path(raw_path).resolve()
        if not working_dir.is_dir():
            raise BootstrapConfigurationError(
                f"Kestra WORKING_DIR does not exist or is not a directory: {working_dir}"
            )
        return working_dir

    def _resolve_runtime_root(self, relative_path: str) -> Path:
        path = Path(relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise BootstrapConfigurationError(
                "APP_RUNTIME_PATH must be a safe path relative to WORKING_DIR."
            )
        runtime_root = (self.working_dir / path).resolve()
        if not runtime_root.is_relative_to(self.working_dir):
            raise BootstrapConfigurationError(
                "APP_RUNTIME_PATH resolves outside the Kestra task working directory."
            )
        if not runtime_root.is_dir():
            raise BootstrapConfigurationError(
                f"Pinned application runtime directory is missing: {runtime_root}"
            )
        return runtime_root

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_bundle_file(root: Path, relative_name: str) -> Path:
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise BootstrapConfigurationError(
                f"Unsafe path in application runtime manifest: {relative_name!r}"
            )
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise BootstrapConfigurationError(
                f"Runtime manifest path escapes the bundle: {relative_name!r}"
            )
        return resolved

    def _verify_runtime_bundle(self) -> None:
        """Verify the manifest pin and every application file before importing code."""
        manifest_path = self.runtime_root / "release-manifest.json"
        if not manifest_path.is_file():
            raise BootstrapConfigurationError(
                f"Pinned application runtime has no release-manifest.json: {self.runtime_root}"
            )
        actual_manifest_sha = self._sha256(manifest_path)
        if actual_manifest_sha != self.runtime_manifest_sha256:
            raise BootstrapConfigurationError(
                "Application runtime manifest SHA-256 does not match the flow's pinned value. "
                f"Expected {self.runtime_manifest_sha256}; received {actual_manifest_sha}."
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BootstrapConfigurationError(
                "The pinned application runtime manifest is not valid JSON."
            ) from exc
        if manifest.get("release_version") != self.runtime_root.name:
            raise BootstrapConfigurationError(
                "Runtime manifest release_version does not match the selected Namespace Files directory."
            )
        if manifest.get("artifact_type") != self.runtime_artifact_type:
            raise BootstrapConfigurationError(
                "The selected bundle artifact type does not match APP_RUNTIME_ARTIFACT_TYPE. "
                f"Expected {self.runtime_artifact_type!r}; received {manifest.get('artifact_type')!r}."
            )

        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise BootstrapConfigurationError("Runtime manifest has no application checksum map.")
        checksums = dict(files)
        policy_specs = manifest.get("policy_specs", {})
        if policy_specs:
            if not isinstance(policy_specs, dict):
                raise BootstrapConfigurationError(
                    "Runtime manifest policy_specs must be an object."
                )
            checksums.update(
                {f"policy-specs/{name}": digest for name, digest in policy_specs.items()}
            )

        for relative_name, expected_sha in checksums.items():
            if not isinstance(relative_name, str) or not isinstance(expected_sha, str):
                raise BootstrapConfigurationError(
                    "Runtime manifest checksum entries must be strings."
                )
            if len(expected_sha) != 64:
                raise BootstrapConfigurationError(
                    f"Runtime manifest contains an invalid SHA-256 for {relative_name!r}."
                )
            file_path = self._safe_bundle_file(self.runtime_root, relative_name)
            if not file_path.is_file():
                raise BootstrapConfigurationError(
                    f"Pinned application runtime file is missing: {relative_name}"
                )
            actual_sha = self._sha256(file_path)
            if actual_sha != expected_sha:
                raise BootstrapConfigurationError(
                    f"Pinned application runtime checksum mismatch: {relative_name}"
                )


# Deliberately create one context per Python task process. Docker Runner isolation
# means this object is not shared across tasks or applicants.
ctx = _TaskContext()
