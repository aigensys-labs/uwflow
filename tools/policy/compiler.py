"""Validate canonical UWflow policy specs and compile deterministic Python.

This compiler is intentionally standard-library-only. It accepts a small,
allow-listed condition AST and emits normal Python functions; it never evaluates
user-provided Python or expressions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC_DIR = ROOT / "core" / "underwriting" / "policies" / "stages"
DEFAULT_FIELD_CATALOG = ROOT / "core" / "underwriting" / "policies" / "schema" / "fields.json"
DEFAULT_OUTPUT = ROOT / "core" / "python" / "runtime" / "policy_generated.py"

ALLOWED_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "between"}
FIELD_TYPES = {"boolean", "integer", "number", "string"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class PolicyValidationError(ValueError):
    """Raised when a policy specification is invalid or unsafe to compile."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyValidationError(message)


def _is_typed_value(value: Any, field_type: str) -> bool:
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if field_type == "string":
        return isinstance(value, str)
    return False


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyValidationError(f"Missing policy file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyValidationError(f"Invalid JSON in {path}: {exc}") from exc
    _require(isinstance(value, dict), f"Expected a JSON object in {path}")
    return value


def _field_type(field_catalog: dict[str, Any], field: str, stage: str) -> str:
    _require(isinstance(field, str), "Policy field name must be a string")
    fields = field_catalog.get("fields", {})
    _require(isinstance(fields, dict), "Field catalogue 'fields' must be an object")
    _require(field in fields, f"Field {field!r} is not in the allow-list")
    definition = fields[field]
    _require(isinstance(definition, dict), f"Field catalogue entry {field!r} must be an object")
    _require(stage in definition.get("stages", []), f"Field {field!r} is not allowed in {stage}")
    field_type = definition.get("type")
    _require(field_type in FIELD_TYPES, f"Unsupported catalogue type for {field!r}: {field_type!r}")
    return field_type


def _validate_condition(
    condition: Any,
    *,
    stage: str,
    declared_inputs: dict[str, str],
    field_catalog: dict[str, Any],
    location: str,
) -> None:
    _require(isinstance(condition, dict), f"{location} must be an object")
    _require(
        set(condition) == {"field", "op", "value"},
        f"{location} must contain field, op and value only",
    )
    field = condition["field"]
    op = condition["op"]
    value = condition["value"]
    _require(isinstance(field, str), f"{location}.field must be a string")
    _require(isinstance(op, str), f"{location}.op must be a string")
    actual_type = _field_type(field_catalog, field, stage)
    _require(field in declared_inputs, f"{location} references undeclared input {field!r}")
    _require(declared_inputs[field] == actual_type, f"Input type mismatch for {field!r}")
    _require(op in ALLOWED_OPERATORS, f"Unsupported operator {op!r} at {location}")

    if op in {"==", "!="}:
        _require(
            _is_typed_value(value, actual_type),
            f"Invalid {actual_type} comparison value at {location}",
        )
    elif op in {"<", "<=", ">", ">="}:
        _require(
            actual_type in {"integer", "number"},
            f"Operator {op!r} requires a numeric field at {location}",
        )
        _require(
            _is_typed_value(value, actual_type), f"Invalid numeric comparison value at {location}"
        )
    elif op == "in":
        _require(
            isinstance(value, list) and len(value) > 0,
            f"Operator 'in' needs a non-empty array at {location}",
        )
        _require(
            all(_is_typed_value(item, actual_type) for item in value),
            f"Invalid 'in' values at {location}",
        )
    elif op == "between":
        _require(
            actual_type in {"integer", "number"},
            f"Operator 'between' requires a numeric field at {location}",
        )
        _require(
            isinstance(value, list)
            and len(value) == 2
            and all(_is_typed_value(item, actual_type) for item in value)
            and value[0] <= value[1],
            f"Operator 'between' needs two ordered numeric bounds at {location}",
        )


def _validate_stage_inputs(spec: dict[str, Any], field_catalog: dict[str, Any]) -> dict[str, str]:
    stage = spec.get("stage")
    _require(isinstance(stage, str) and stage, "Policy stage must be a non-empty string")
    inputs = spec.get("inputs")
    _require(
        isinstance(inputs, list) and inputs, f"{spec.get('id')}: inputs must be a non-empty array"
    )
    declared: dict[str, str] = {}
    for index, item in enumerate(inputs):
        location = f"{spec.get('id')}.inputs[{index}]"
        _require(
            isinstance(item, dict) and set(item) == {"field", "type"},
            f"{location} must contain field and type only",
        )
        field = item["field"]
        _require(
            isinstance(field, str) and field not in declared,
            f"Duplicate or invalid input field at {location}",
        )
        catalog_type = _field_type(field_catalog, field, stage)
        _require(
            item["type"] == catalog_type,
            f"Input {field!r} must use catalogue type {catalog_type!r}",
        )
        declared[field] = catalog_type
    return declared


def validate_dmn_table(spec: dict[str, Any], field_catalog: dict[str, Any]) -> None:
    """Validate Stage 1's single-predicate-per-input underwriting checks."""
    expected_keys = {"schema_version", "id", "stage", "kind", "description", "inputs", "checks"}
    missing_keys = expected_keys - set(spec)
    extra_keys = set(spec) - expected_keys
    _require(
        not missing_keys, f"DMN policy is missing required top-level keys: {sorted(missing_keys)}"
    )
    _require(
        not extra_keys, f"DMN policy contains unsupported top-level keys: {sorted(extra_keys)}"
    )
    _require(
        spec.get("schema_version") == 2,
        "Unsupported DMN schema_version; expected version 2 single-predicate checks",
    )
    _require(spec.get("kind") == "dmn_table", "Expected kind='dmn_table'")
    _require(
        isinstance(spec.get("id"), str) and IDENTIFIER.fullmatch(spec["id"]),
        "DMN id must be a snake_case identifier",
    )
    stage = spec.get("stage")
    _require(stage == "stage_1_hard_gates", f"Unsupported DMN stage: {stage!r}")
    _require(
        isinstance(spec.get("description"), str) and spec["description"],
        "DMN description is required",
    )
    declared_inputs = _validate_stage_inputs(spec, field_catalog)

    checks = spec.get("checks")
    _require(isinstance(checks, list) and checks, "DMN checks must be a non-empty array")
    check_ids: set[str] = set()
    checked_fields: set[str] = set()
    for index, check in enumerate(checks):
        location = f"{spec['id']}.checks[{index}]"
        _require(
            isinstance(check, dict)
            and set(check)
            == {"check_id", "field", "description", "valid_when", "failure_reason_code"},
            f"{location} has missing or unsupported keys",
        )
        check_id = check["check_id"]
        _require(
            isinstance(check_id, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", check_id),
            f"Invalid check_id at {location}",
        )
        _require(check_id not in check_ids, f"Duplicate check_id {check_id!r}")
        check_ids.add(check_id)

        field = check["field"]
        _require(isinstance(field, str), f"{location}.field must be a string")
        _field_type(field_catalog, field, stage)
        _require(field in declared_inputs, f"{location}.field must reference a declared input")
        _require(
            field not in checked_fields,
            f"Input field {field!r} has more than one policy check; use one positive predicate per variable",
        )
        checked_fields.add(field)
        _require(
            isinstance(check["description"], str) and check["description"],
            f"Missing description at {location}",
        )
        reason_code = check["failure_reason_code"]
        _require(
            isinstance(reason_code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", reason_code),
            f"{location}.failure_reason_code must be a non-empty uppercase reason code",
        )
        valid_when = check["valid_when"]
        _require(
            isinstance(valid_when, dict) and set(valid_when) == {"op", "value"},
            f"{location}.valid_when must contain op and value only",
        )
        _validate_condition(
            {"field": field, **valid_when},
            stage=stage,
            declared_inputs=declared_inputs,
            field_catalog=field_catalog,
            location=f"{location}.valid_when",
        )

    _require(
        checked_fields == set(declared_inputs),
        "Stage 1 must define exactly one positive predicate for every declared input field; "
        f"missing={sorted(set(declared_inputs) - checked_fields)}",
    )


def _validate_graph_condition(
    condition: dict[str, Any], stage: str, field_catalog: dict[str, Any]
) -> None:
    _require(isinstance(condition, dict), "Routing condition must be an object")
    field = condition.get("field")
    _require(isinstance(field, str), "Routing condition field must be a string")
    field_type = _field_type(field_catalog, field, stage)
    _validate_condition(
        condition,
        stage=stage,
        declared_inputs={field: field_type},
        field_catalog=field_catalog,
        location=f"routing condition for {field}",
    )


def validate_routing_dag(spec: dict[str, Any], field_catalog: dict[str, Any]) -> None:
    """Validate Stage 3 routing topology, allowed conditions and terminal paths."""
    _require(
        set(spec)
        == {
            "schema_version",
            "id",
            "stage",
            "kind",
            "description",
            "entry_node",
            "inputs",
            "nodes",
            "edges",
        },
        "Routing policy contains missing or unsupported top-level keys",
    )
    _require(spec.get("schema_version") == 1, "Unsupported routing schema_version")
    _require(spec.get("kind") == "routing_dag", "Expected kind='routing_dag'")
    _require(
        isinstance(spec.get("id"), str) and IDENTIFIER.fullmatch(spec["id"]),
        "Routing DAG id must be a snake_case identifier",
    )
    stage = spec.get("stage")
    _require(stage == "stage_3_source_plan", f"Unsupported routing stage: {stage!r}")
    declared_inputs = _validate_stage_inputs(spec, field_catalog)
    _require(
        set(declared_inputs)
        == {"hard_gates_passed", "bureau_decision_status", "data_sharing_consent"},
        "Stage 3 input contract has changed",
    )

    nodes = spec.get("nodes")
    edges = spec.get("edges")
    _require(isinstance(nodes, list) and nodes, "Routing DAG nodes must be a non-empty array")
    _require(isinstance(edges, list) and edges, "Routing DAG edges must be a non-empty array")
    node_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        _require(isinstance(node, dict), f"Node at index {index} must be an object")
        node_id = node.get("id")
        _require(
            isinstance(node_id, str) and IDENTIFIER.fullmatch(node_id),
            f"Invalid routing node id at index {index}",
        )
        _require(node_id not in node_by_id, f"Duplicate routing node id {node_id!r}")
        _require(
            isinstance(node.get("label"), str) and node["label"], f"Node {node_id!r} needs a label"
        )
        node_type = node.get("type")
        _require(
            isinstance(node_type, str)
            and node_type in {"condition_split", "source_plan", "outcome"},
            f"Unsupported node type {node_type!r}",
        )
        if node_type == "source_plan":
            _require(
                set(node) == {"id", "type", "label", "source_ids"},
                f"Unsupported source_plan node shape: {node_id}",
            )
            source_ids = node["source_ids"]
            allowed_sources = field_catalog.get("source_ids", [])
            _require(
                isinstance(source_ids, list)
                and source_ids
                and all(isinstance(source, str) for source in source_ids)
                and len(source_ids) == len(set(source_ids))
                and all(source in allowed_sources for source in source_ids),
                f"Node {node_id!r} contains invalid or duplicate source IDs",
            )
        elif node_type == "outcome":
            _require(
                set(node) == {"id", "type", "label", "action", "reason"},
                f"Unsupported outcome node shape: {node_id}",
            )
            _require(
                node.get("action") == "SKIP_SOURCE_COLLECTION",
                f"Unsupported routing outcome action at {node_id!r}",
            )
            _require(
                isinstance(node.get("reason"), str) and node["reason"],
                f"Outcome {node_id!r} needs a reason",
            )
        else:
            _require(
                set(node) == {"id", "type", "label"},
                f"Unsupported condition_split node shape: {node_id}",
            )
        node_by_id[node_id] = node

    entry = spec.get("entry_node")
    _require(isinstance(entry, str) and entry in node_by_id, "Routing entry_node does not exist")
    edge_ids: set[str] = set()
    outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_by_id}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_by_id}
    for index, edge in enumerate(edges):
        _require(
            isinstance(edge, dict)
            and set(edge).issubset(
                {"id", "source", "target", "condition", "is_default", "priority"}
            )
            and {"id", "source", "target", "is_default"}.issubset(edge),
            f"Invalid routing edge at index {index}",
        )
        edge_id = edge["id"]
        _require(
            isinstance(edge_id, str) and IDENTIFIER.fullmatch(edge_id),
            f"Invalid edge id at index {index}",
        )
        _require(edge_id not in edge_ids, f"Duplicate routing edge id {edge_id!r}")
        edge_ids.add(edge_id)
        source, target = edge["source"], edge["target"]
        _require(
            isinstance(source, str)
            and isinstance(target, str)
            and source in node_by_id
            and target in node_by_id,
            f"Edge {edge_id!r} references an unknown node",
        )
        _require(
            isinstance(edge["is_default"], bool), f"Edge {edge_id!r}.is_default must be boolean"
        )
        if edge["is_default"]:
            _require(
                "condition" not in edge and "priority" not in edge,
                f"Default edge {edge_id!r} cannot have a condition or priority",
            )
        else:
            _require("condition" in edge, f"Conditional edge {edge_id!r} needs a condition")
            _require(
                isinstance(edge.get("priority"), int)
                and not isinstance(edge.get("priority"), bool),
                f"Conditional edge {edge_id!r} needs an integer priority",
            )
            _validate_graph_condition(edge["condition"], stage, field_catalog)
        outgoing[source].append(edge)
        adjacency[source].append(target)

    for node_id, node in node_by_id.items():
        node_edges = outgoing[node_id]
        if node["type"] == "condition_split":
            defaults = [edge for edge in node_edges if edge["is_default"]]
            conditional = [edge for edge in node_edges if not edge["is_default"]]
            _require(
                len(defaults) == 1,
                f"Condition split {node_id!r} must have exactly one default edge",
            )
            _require(
                bool(conditional),
                f"Condition split {node_id!r} needs at least one conditional edge",
            )
            priorities = [edge["priority"] for edge in conditional]
            _require(
                len(priorities) == len(set(priorities)),
                f"Condition split {node_id!r} has duplicate priorities",
            )
        else:
            _require(not node_edges, f"Terminal node {node_id!r} cannot have outgoing edges")

    # Kahn's algorithm rejects cycles. The following traversal independently
    # enforces that every declared node can be reached from the entry point.
    indegree = {node_id: 0 for node_id in node_by_id}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited_count = 0
    while queue:
        current = queue.pop(0)
        visited_count += 1
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    _require(visited_count == len(node_by_id), "Routing DAG contains a cycle")

    reachable: set[str] = set()
    stack = [entry]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(adjacency[current])
    _require(
        reachable == set(node_by_id),
        f"Routing DAG contains unreachable nodes: {sorted(set(node_by_id) - reachable)}",
    )


def _python_literal(value: Any) -> str:
    return repr(value)


def _compile_dmn(spec: dict[str, Any]) -> str:
    check_rows = [
        {
            "check_id": check["check_id"],
            "field": check["field"],
            "description": check["description"],
            "valid_when": check["valid_when"],
            "failure_reason_code": check["failure_reason_code"],
        }
        for check in spec["checks"]
    ]
    lines = [
        "_STAGE1_CHECKS = " + _python_literal(check_rows),
        "",
        "def evaluate_stage1_hard_gates(context: Mapping[str, Any]) -> dict[str, Any]:",
        '    """Evaluate one positive predicate per Stage 1 underwriting variable.',
        "",
        "    A true predicate produces PASS. Its logical complement produces FAIL",
        "    with the check's configured failure reason code.",
        '    """',
        "    _validate_context(context, _STAGE1_INPUT_TYPES)",
        "    checks: list[dict[str, Any]] = []",
        "    trace: list[str] = []",
        "    for check in _STAGE1_CHECKS:",
        "        condition = {'field': check['field'], **check['valid_when']}",
        "        passed = _matches(context, condition)",
        "        checks.append({",
        "            'check_id': check['check_id'],",
        "            'status': 'PASS' if passed else 'FAIL',",
        "            'reason_code': None if passed else check['failure_reason_code'],",
        "            'description': check['description'],",
        "        })",
        "        trace.append(check['check_id'])",
        "    return {'checks': checks, 'trace': trace}",
    ]
    return "\n".join(lines)


def _compile_routing(spec: dict[str, Any]) -> str:
    node_by_id = {node["id"]: node for node in spec["nodes"]}
    outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_by_id}
    for edge in spec["edges"]:
        outgoing[edge["source"]].append(edge)

    lines = [
        "",
        "_STAGE3_INPUT_TYPES = "
        + _python_literal({item["field"]: item["type"] for item in spec["inputs"]}),
        "",
    ]
    for node_id, node in node_by_id.items():
        function_name = f"_route_{node_id}"
        lines.extend(
            [
                f"def {function_name}(context: Mapping[str, Any], trace: list[str]) -> dict[str, Any]:",
                f"    trace.append({_python_literal(node_id)})",
            ]
        )
        if node["type"] == "condition_split":
            edges = outgoing[node_id]
            conditional = sorted(
                (edge for edge in edges if not edge["is_default"]),
                key=lambda item: item["priority"],
            )
            default_edge = next(edge for edge in edges if edge["is_default"])
            for index, edge in enumerate(conditional):
                keyword = "if" if index == 0 else "elif"
                lines.append(
                    f"    {keyword} _matches(context, {_python_literal(edge['condition'])}):"
                )
                lines.append(f"        return _route_{edge['target']}(context, trace)")
            lines.append("    else:")
            lines.append(f"        return _route_{default_edge['target']}(context, trace)")
        elif node["type"] == "source_plan":
            lines.extend(
                [
                    f"    source_ids = {_python_literal(node['source_ids'])}",
                    "    return {",
                    "        'action': 'COLLECT_SOURCES',",
                    "        'source_ids': list(source_ids),",
                    "        'loop_values': list(source_ids) if source_ids else ['__NO_SOURCE_COLLECTION__'],",
                    "        'planned_count': len(source_ids),",
                    "        'reason': 'CONSENTED_SOURCE_COLLECTION',",
                    "        'trace': list(trace),",
                    "    }",
                ]
            )
        else:
            lines.extend(
                [
                    "    return {",
                    f"        'action': {_python_literal(node['action'])},",
                    "        'source_ids': [],",
                    "        'loop_values': ['__NO_SOURCE_COLLECTION__'],",
                    "        'planned_count': 0,",
                    f"        'reason': {_python_literal(node['reason'])},",
                    "        'trace': list(trace),",
                    "    }",
                ]
            )
        lines.append("")

    lines.extend(
        [
            "def build_stage3_source_plan(context: Mapping[str, Any]) -> dict[str, Any]:",
            '    """Return the source-collection plan; never performs source I/O."""',
            "    _validate_context(context, _STAGE3_INPUT_TYPES)",
            f"    return _route_{spec['entry_node']}(context, [])",
        ]
    )
    return "\n".join(lines)


def render_module(specs: list[dict[str, Any]], spec_bytes: dict[str, bytes]) -> str:
    """Render deterministic Python source from the validated Stage 1 and Stage 3 policy specs."""
    dmn = next(spec for spec in specs if spec["kind"] == "dmn_table")
    routing = next(spec for spec in specs if spec["kind"] == "routing_dag")
    metadata = {
        spec["stage"]: {
            "policy_id": spec["id"],
            "kind": spec["kind"],
            "sha256": hashlib.sha256(spec_bytes[spec["stage"]]).hexdigest(),
        }
        for spec in specs
    }
    stage1_inputs = {item["field"]: item["type"] for item in dmn["inputs"]}
    header = [
        '"""Generated UWflow policy functions. DO NOT EDIT BY HAND.',
        "",
        "Regenerate with: python tools/compile_policy_spec.py",
        '"""',
        "from __future__ import annotations",
        "",
        "import math",
        "from typing import Any, Mapping",
        "",
        "POLICY_METADATA = " + _python_literal(metadata),
        "_STAGE1_INPUT_TYPES = " + _python_literal(stage1_inputs),
        "",
        "",
        "def _validate_context(context: Mapping[str, Any], input_types: dict[str, str]) -> None:",
        '    """Fail closed when a required, typed policy input is unavailable."""',
        "    for field, field_type in input_types.items():",
        "        if field not in context:",
        '            raise ValueError(f"Missing policy input: {field}")',
        "        value = context[field]",
        "        valid = (",
        "            isinstance(value, bool) if field_type == 'boolean' else",
        "            isinstance(value, int) and not isinstance(value, bool) if field_type == 'integer' else",
        "            isinstance(value, (int, float)) and not isinstance(value, bool) if field_type == 'number' else",
        "            isinstance(value, str) if field_type == 'string' else",
        "            False",
        "        )",
        "        if not valid:",
        '            raise ValueError(f"Policy input {field!r} must be {field_type}")',
        "",
        "",
        "def _matches(context: Mapping[str, Any], condition: dict[str, Any]) -> bool:",
        '    """Evaluate one previously validated condition AST node."""',
        "    actual = context[condition['field']]",
        "    expected = condition['value']",
        "    op = condition['op']",
        "    if op == '==':",
        "        return actual == expected",
        "    if op == '!=':",
        "        return actual != expected",
        "    if op == '<':",
        "        return actual < expected",
        "    if op == '<=':",
        "        return actual <= expected",
        "    if op == '>':",
        "        return actual > expected",
        "    if op == '>=':",
        "        return actual >= expected",
        "    if op == 'in':",
        "        return actual in expected",
        "    if op == 'between':",
        "        return expected[0] <= actual <= expected[1]",
        '    raise ValueError(f"Unsupported compiled operator: {op!r}")',
        "",
        "",
        _compile_dmn(dmn),
        _compile_routing(routing),
        "",
    ]
    return "\n".join(header)


def validate_policy_spec(spec: dict[str, Any], field_catalog: dict[str, Any]) -> None:
    """Validate one supported policy document against the canonical field catalogue."""
    kind = spec.get("kind")
    if kind == "dmn_table":
        validate_dmn_table(spec, field_catalog)
    elif kind == "routing_dag":
        validate_routing_dag(spec, field_catalog)
    else:
        raise PolicyValidationError(f"Unsupported policy kind: {kind!r}")


def compile_specs(
    spec_dir: Path = DEFAULT_SPEC_DIR,
    field_catalog_path: Path = DEFAULT_FIELD_CATALOG,
) -> tuple[str, dict[str, bytes]]:
    """Load, validate and compile the supported policy specifications into Python source."""
    field_catalog = _load_json(field_catalog_path)
    spec_paths = sorted(spec_dir.glob("*.json"))
    _require(bool(spec_paths), f"No policy specs found in {spec_dir}")
    specs: list[dict[str, Any]] = []
    spec_bytes: dict[str, bytes] = {}
    for path in spec_paths:
        spec = _load_json(path)
        if spec.get("kind") == "dmn_table":
            validate_dmn_table(spec, field_catalog)
        elif spec.get("kind") == "routing_dag":
            validate_routing_dag(spec, field_catalog)
        else:
            raise PolicyValidationError(f"Unsupported policy kind in {path}: {spec.get('kind')!r}")
        _require(
            spec["stage"] not in spec_bytes,
            f"More than one policy spec supplied for stage {spec['stage']!r}",
        )
        specs.append(spec)
        spec_bytes[spec["stage"]] = path.read_bytes()
    _require(
        {spec["kind"] for spec in specs} == {"dmn_table", "routing_dag"},
        "Expected one DMN table and one routing DAG",
    )
    _require(
        {spec["stage"] for spec in specs} == {"stage_1_hard_gates", "stage_3_source_plan"},
        "Expected Stage 1 and Stage 3 policy specs",
    )
    specs.sort(key=lambda item: item["stage"])
    return render_module(specs, spec_bytes), spec_bytes


def main() -> int:
    """Compile the canonical Core policy specifications or verify the generated module is current."""
    parser = argparse.ArgumentParser(
        description="Validate UWflow policy specs and compile deterministic Python"
    )
    parser.add_argument("--spec-dir", type=Path, default=DEFAULT_SPEC_DIR)
    parser.add_argument("--field-catalog", type=Path, default=DEFAULT_FIELD_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="Verify generated Python is current without writing it"
    )
    args = parser.parse_args()

    try:
        generated, _ = compile_specs(args.spec_dir, args.field_catalog)
    except PolicyValidationError as exc:
        parser.error(str(exc))

    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != generated:
            raise SystemExit(
                f"Generated policy module is stale: {args.output}. Run python -m tools.policy.compiler"
            )
        print(f"Verified generated policy module: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Compiled {args.spec_dir} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
