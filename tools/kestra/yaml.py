"""Kestra YAML serialization with parser-safe, fully materialized values.

The Kestra deployment path uses Jackson's YAML parser, which exposes YAML alias
nodes as strings containing the anchor name instead of resolving the referenced
value. Therefore deployed flow YAML must not contain anchors or aliases.

Shared runtime settings are centralized in flow-builder inputs/labels and copied
into the relevant task fields before serialization. The output intentionally
repeats literal values and mapping blocks so Kestra receives ordinary YAML
objects with no alias indirection.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_DIGEST_ENV_BINDINGS = {
    "runtime-manifest-sha256": (
        ("APP_RUNTIME_MANIFEST_SHA256",),
        None,
    ),
    "baseline-manifest-sha256": (
        ("UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256",),
        "baseline_replay",
    ),
    "candidate-manifest-sha256": (
        ("UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256",),
        "candidate_replay",
    ),
}


class _KestraDumper(yaml.SafeDumper):
    """Kestra-safe dumper with explicit indentation and no YAML aliases.

    PyYAML normally emits sequences nested below mapping keys without an extra
    indentation level (for example ``tasks:\n- id: ...``). Although valid YAML,
    Kestra's flow topology presentation does not consistently recognize those
    task hierarchies. Always indent nested sequences so task items are visibly
    children of ``tasks`` and nested task lists remain visually unambiguous.
    """

    def ignore_aliases(self, data: Any) -> bool:
        # Do not use anchors for either scalars or collections. The deployed
        # Kestra/Jackson parser returns the alias name as a string value.
        """Disable YAML anchor and alias emission for Kestra-compatible flow files."""
        return True

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        # Force indentless=False for sequences under mappings. This emits
        # ``tasks:\n  - id: ...`` instead of ``tasks:\n- id: ...``.
        """Indent YAML sequence items beneath their owning mapping keys."""
        return super().increase_indent(flow, indentless=False)


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_KestraDumper.add_representer(str, _represent_string)


def _python_tasks(flow: dict[str, Any]) -> list[dict[str, Any]]:
    """Return Python task mappings, including nested Loop/branch tasks."""
    found: list[dict[str, Any]] = []

    def visit(items: Any) -> None:
        if not isinstance(items, list):
            return
        for task in items:
            if not isinstance(task, dict):
                continue
            if task.get("type") in {
                "io.kestra.plugin.scripts.python.Script",
                "io.kestra.plugin.scripts.python.Commands",
            }:
                found.append(task)
            for branch in ("tasks", "then", "else"):
                visit(task.get(branch))

    visit(flow.get("tasks", []))
    return found


def _materialize_shared_runtime_values(flow: dict[str, Any]) -> None:
    """Copy canonical flow-level/runtime values into each applicable task.

    The flow's labels are authoritative for manifest hashes. For a normal
    release flow, the common runtime path, image and Python version are taken
    from the flow's first Python task and copied to the other Python tasks.
    Historical replay keeps its baseline/candidate roots task-specific.
    """
    tasks = _python_tasks(flow)
    labels = flow.get("labels", {})
    if not isinstance(labels, dict):
        labels = {}

    for label_name, (env_names, task_id) in _DIGEST_ENV_BINDINGS.items():
        digest = labels.get(label_name)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            continue
        for task in tasks:
            if task_id is not None and task.get("id") != task_id:
                continue
            env = task.get("env")
            if isinstance(env, dict):
                for env_name in env_names:
                    if env_name in env:
                        env[env_name] = digest

    if not tasks:
        return

    # Normal production/baseline/candidate flows have one runtime root.
    # Replay flows intentionally expose two roots through a different env key.
    for env_name in ("APP_RUNTIME_PATH",):
        runtime_paths = [
            task.get("env", {}).get(env_name)
            for task in tasks
            if isinstance(task.get("env"), dict) and isinstance(task["env"].get(env_name), str)
        ]
        if runtime_paths and len(set(runtime_paths)) == 1:
            runtime_path = runtime_paths[0]
            for task in tasks:
                env = task.setdefault("env", {})
                if env_name in env:
                    env[env_name] = runtime_path

    images = [task.get("containerImage") for task in tasks if task.get("containerImage")]
    if images and len(set(images)) == 1:
        image = images[0]
        for task in tasks:
            if "containerImage" in task:
                task["containerImage"] = image
            env = task.get("env")
            if isinstance(env, dict):
                for env_name in ("APP_TASK_IMAGE",):
                    if env_name in env:
                        env[env_name] = image

    python_versions = [task.get("pythonVersion") for task in tasks if task.get("pythonVersion")]
    if python_versions and len(set(python_versions)) == 1:
        python_version = python_versions[0]
        for task in tasks:
            if "pythonVersion" in task:
                task["pythonVersion"] = python_version


def dump_kestra_yaml(value: dict[str, Any]) -> str:
    """Serialize a fully materialized Kestra flow with no YAML anchors/aliases."""
    _materialize_shared_runtime_values(value)
    return yaml.dump(
        value,
        Dumper=_KestraDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=110,
    )
