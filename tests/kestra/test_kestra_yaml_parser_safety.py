"""Tests for deployable Kestra YAML structure, parser compatibility and task configuration."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _python_tasks(tasks):
    for task in tasks:
        if task.get("type") in {
            "io.kestra.plugin.scripts.python.Script",
            "io.kestra.plugin.scripts.python.Commands",
        }:
            yield task
        yield from _python_tasks(task.get("tasks", []))
        yield from _python_tasks(task.get("then", []))
        yield from _python_tasks(task.get("else", []))


def _raw(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assert_no_yaml_anchors_or_aliases(raw: str) -> None:
    # Inspect YAML tokens, not text patterns: this catches all valid anchor and
    # alias token forms, including forms that a regular expression can miss.
    forbidden = (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)
    assert not any(isinstance(token, forbidden) for token in yaml.scan(raw))


def _assert_indented_task_sequences(raw: str) -> None:
    """Ensure task list entries are visibly nested below their YAML key."""
    lines = raw.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.rstrip() == "tasks:":
            next_line = lines[index + 1]
            current_indent = len(line) - len(line.lstrip())
            next_indent = len(next_line) - len(next_line.lstrip())
            assert next_line.lstrip().startswith("- id:"), next_line
            assert next_indent == current_indent + 2, (
                f"Task item must be indented two spaces below 'tasks:'; got {next_line!r}"
            )


def _assert_python_task_mappings_are_materialized(flow: dict) -> None:
    tasks = list(_python_tasks(flow["tasks"]))
    assert tasks
    for task in tasks:
        assert isinstance(task.get("namespaceFiles"), dict)
        assert isinstance(task.get("taskRunner"), dict)
        assert task["namespaceFiles"]["enabled"] is True
        assert task["taskRunner"]["type"] == ("io.kestra.plugin.scripts.runner.docker.Docker")


def test_production_flow_repeats_verified_digest_as_materialized_values() -> None:
    path = "core/kestra/flows/uwflow_production_underwriting.yaml"
    raw = _raw(path)
    flow = yaml.safe_load(raw)
    digest = flow["labels"]["runtime-manifest-sha256"]
    tasks = list(_python_tasks(flow["tasks"]))

    assert len(tasks) == 7
    assert raw.count(digest) == len(tasks) + 1  # label plus every Python task
    assert all(task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == digest for task in tasks)
    _assert_no_yaml_anchors_or_aliases(raw)
    _assert_python_task_mappings_are_materialized(flow)


def test_production_digest_matches_immutable_runtime_manifest() -> None:
    flow = yaml.safe_load(_raw("core/kestra/flows/uwflow_production_underwriting.yaml"))
    manifest = ROOT / "core/kestra/namespace-files/runtime/releases/2.0.0/release-manifest.json"
    expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert flow["labels"]["runtime-manifest-sha256"] == expected


def test_dev_baseline_and_fresh_candidate_materialize_their_digest(candidate_package: dict) -> None:
    candidate_root = (
        candidate_package["root"] / "var/artifacts/candidates" / candidate_package["candidate_id"]
    )
    paths = [
        ROOT / "core/kestra/dev/flows/uwflow_dev_baseline_v2_0_0.yaml",
        candidate_root / "candidate-flow.yaml",
    ]
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        flow = yaml.safe_load(raw)
        digest = flow["labels"]["runtime-manifest-sha256"]
        tasks = list(_python_tasks(flow["tasks"]))
        assert raw.count(digest) == len(tasks) + 1
        assert all(task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == digest for task in tasks)
        _assert_no_yaml_anchors_or_aliases(raw)
        _assert_python_task_mappings_are_materialized(flow)


def test_history_replay_materializes_baseline_and_candidate_digests_in_matching_tasks(
    replay_package: dict,
) -> None:
    raw = replay_package["flow_path"].read_text(encoding="utf-8")
    flow = yaml.safe_load(raw)
    labels = flow["labels"]
    baseline_digest = labels["baseline-manifest-sha256"]
    candidate_digest = labels["candidate-manifest-sha256"]

    assert baseline_digest != candidate_digest
    assert raw.count(baseline_digest) == 2
    assert raw.count(candidate_digest) == 2
    _assert_no_yaml_anchors_or_aliases(raw)

    tasks = {task["id"]: task for task in flow["tasks"]}
    parallel = tasks["replay_pair"]
    assert parallel["type"] == "io.kestra.plugin.core.flow.Parallel"
    replay_tasks = {task["id"]: task for task in parallel["tasks"]}
    assert (
        replay_tasks["baseline_replay"]["env"]["UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"]
        == baseline_digest
    )
    assert (
        replay_tasks["candidate_replay"]["env"]["UWFLOW_HISTORY_EXPECTED_RUNTIME_MANIFEST_SHA256"]
        == candidate_digest
    )
    _assert_python_task_mappings_are_materialized(flow)


def test_serializer_emits_no_anchors_and_materializes_shared_values() -> None:
    spec_path = ROOT / "tools/kestra/yaml.py"
    spec = importlib.util.spec_from_file_location("kestra_yaml", spec_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    shared_mapping = {
        "enabled": True,
        "include": ["runtime/releases/2.0.0/**"],
        "ifExists": "FAIL",
    }
    shared_runner = {"type": "io.kestra.plugin.scripts.runner.docker.Docker"}
    digest = "a" * 64
    flow = {
        "labels": {"runtime-manifest-sha256": digest},
        "tasks": [
            {
                "id": "one",
                "type": "io.kestra.plugin.scripts.python.Script",
                "namespaceFiles": shared_mapping,
                "taskRunner": shared_runner,
                "containerImage": "ai/uwflow-runtime:2.0.0",
                "pythonVersion": "3.11",
                "env": {"APP_RUNTIME_MANIFEST_SHA256": "old"},
            },
            {
                "id": "two",
                "type": "io.kestra.plugin.scripts.python.Script",
                "namespaceFiles": shared_mapping,
                "taskRunner": shared_runner,
                "containerImage": "ai/uwflow-runtime:2.0.0",
                "pythonVersion": "3.11",
                "env": {"APP_RUNTIME_MANIFEST_SHA256": "old"},
            },
        ],
    }
    dumped = module.dump_kestra_yaml(flow)
    parsed = yaml.safe_load(dumped)

    _assert_no_yaml_anchors_or_aliases(dumped)
    _assert_indented_task_sequences(dumped)
    assert "tasks:\n  - id: one" in dumped
    assert dumped.count(digest) == 3
    assert all(task["env"]["APP_RUNTIME_MANIFEST_SHA256"] == digest for task in parsed["tasks"])
    assert all(task["namespaceFiles"] == shared_mapping for task in parsed["tasks"])
    assert all(task["taskRunner"] == shared_runner for task in parsed["tasks"])
    assert all(task["containerImage"] == "ai/uwflow-runtime:2.0.0" for task in parsed["tasks"])
    assert all(task["pythonVersion"] == "3.11" for task in parsed["tasks"])


def test_all_checked_in_kestra_flows_are_parser_safe_and_visually_indented() -> None:
    for path in sorted((ROOT / "core" / "kestra").rglob("*.yaml")):
        raw = path.read_text(encoding="utf-8")
        _assert_no_yaml_anchors_or_aliases(raw)
        parsed = yaml.safe_load(raw)
        assert isinstance(parsed, dict), path
        if "tasks" in parsed:
            _assert_indented_task_sequences(raw)


def test_generated_history_replay_flow_uses_schema_valid_task_topology(
    replay_package: dict,
) -> None:
    path = replay_package["flow_path"]
    raw = path.read_text(encoding="utf-8")
    flow = yaml.safe_load(raw)
    _assert_no_yaml_anchors_or_aliases(raw)

    def walk(tasks):
        for task in tasks:
            yield task
            yield from walk(task.get("tasks", []))

    tasks = list(walk(flow.get("tasks", [])))
    python_commands = [
        task for task in tasks if task.get("type") == "io.kestra.plugin.scripts.python.Commands"
    ]
    assert python_commands
    assert all("dependsOn" not in task for task in python_commands)
    assert all(
        task["type"] != "io.kestra.plugin.core.flow.Parallel"
        or (task.get("concurrent") == 2 and task.get("onChildFailure") == "FAIL")
        for task in tasks
    )
    assert [task["id"] for task in flow["tasks"]] == [
        "validate_dataset",
        "replay_pair",
        "compare_replays",
    ]
    parallel = flow["tasks"][1]
    assert parallel["type"] == "io.kestra.plugin.core.flow.Parallel"
    assert [task["id"] for task in parallel["tasks"]] == ["baseline_replay", "candidate_replay"]
