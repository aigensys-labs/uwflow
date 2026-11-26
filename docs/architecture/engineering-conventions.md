# Engineering conventions

This document describes the implementation conventions used by UWflow flow builders, runtime tasks, immutable artifacts and operator tooling. Apply these conventions when extending the repository so generated artifacts remain deterministic and compatible with the deployed Kestra version.

## Kestra YAML: declare once in source, materialize for deployment

**Default rule: minimum repetition, maximum declaration in one place.** Keep shared values and reusable structures centralized in Python flow-builder inputs and helper functions. The YAML written to Kestra must be fully materialized: do not emit YAML anchors or aliases.

### Why deployed Kestra YAML must not contain anchors or aliases

The current Kestra 2.0 deployment path uses Jackson's YAML parser. Jackson's `YAMLParser` exposes an alias token as a string containing the anchor name; it does not replay the referenced scalar or mapping value. This matches the deployment error observed when `kestractl flows deploy` tried to bind `namespaceFiles: *uwflow_runtime_namespace_files`: Kestra received the string `uwflow_runtime_namespace_files` where a `NamespaceFiles` object was required.

This is not limited to mappings. A scalar alias for a manifest hash could silently become the literal string `uwflow_runtime_manifest_sha256`, potentially passing a string type check but failing runtime integrity verification. Therefore **no YAML anchors (`&`) or aliases (`*`) are allowed in deployable UWflow Kestra flow files**.

### The correct DRY approach

Centralize each shared value in the flow builder, then copy it into each task before serialization. For example:

- Flow-level label is the source of truth for `runtime-manifest-sha256`.
- Candidate builder's `candidate_id` is the source of truth for candidate Namespace Files paths.
- Baseline/candidate release IDs and their manifests are separate source values in the historical replay builder.
- Shared image and Python version are resolved once by the flow builder.
- Namespace Files and Docker Task Runner mappings are created from shared Python dictionaries/default objects.

The serializer writes ordinary literal values and full mapping objects into every task. The repeated YAML is a generated deployment artifact, not a second source of truth. This is safer than relying on YAML features the Kestra parser does not resolve.

Illustrative generator-side pattern:

```python
runtime_path = f"runtime/releases/{release}"
manifest_sha256 = verified_manifest_sha256
namespace_files = {
    "enabled": True,
    "include": [f"{runtime_path}/**"],
    "ifExists": "FAIL",
}
task_runner = {
    "type": "io.kestra.plugin.scripts.runner.docker.Docker",
}

for task in python_tasks:
    task["namespaceFiles"] = dict(namespace_files)
    task["taskRunner"] = dict(task_runner)
    task["containerImage"] = task_image
    task["pythonVersion"] = python_version
    task.setdefault("env", {})["APP_RUNTIME_PATH"] = runtime_path
    task["env"]["APP_RUNTIME_MANIFEST_SHA256"] = manifest_sha256
```

The resulting flow YAML intentionally repeats these literal values and mappings. Do not add `&anchor`, `*alias`, or YAML merge keys (`<<`) to reduce that repetition.

### Rules

1. **One source of truth in code.** Shared release metadata, paths, image references and task defaults must be set by flow-builder inputs/configuration, not manually copied between task definitions in generator code.
2. **No YAML anchors or aliases in deployable flows.** This applies to scalar values and mapping/sequence values alike.
3. **Materialize mapping properties.** Emit complete `namespaceFiles` and `taskRunner` mappings for each task.
4. **Keep artifact identities distinct.** Historical replay must preserve different baseline and candidate runtime paths and manifest hashes.
5. **Pass YAML values into Python through task environment variables.** Do not put values inside Python script text through YAML syntax tricks.
6. **Keep task-specific configuration explicit.** Do not pass applicant data or unrelated values to tasks that do not need them.
7. **Generate consistently.** All generated flows must go through `tools/kestra/yaml.py` and the repository flow builders.
8. **Validate with the actual deployment parser.** Generic YAML parsing alone is insufficient. Run `kestractl flows validate` against the target Kestra instance before deploying.
9. **Regression test expanded output.** Tests must assert there are no anchor/alias tokens and that every task receives the correct materialized digest, path, image, runner and Namespace Files values.

### Why this is the standard

The objective is still **minimum repetition and maximum declaration in one place**. The declaration belongs in Python flow-builder configuration; the deployed YAML is expanded for compatibility. This keeps a single source of truth without relying on parser-dependent YAML alias behavior.

## Namespace Files directory uploads

Every `kestractl nsfiles upload` of a directory whose destination already contains the source directory basename must include `--no-root`. The CLI otherwise nests the source directory under the destination (for example, uploading local `core/kestra/namespace-files/runtime/releases/2.0.0` to remote `runtime/releases/2.0.0` creates `runtime/releases/2.0.0/2.0.0/...`). Use the shared `tools/kestra/cli.py` command builder from candidate and replay tooling so this flag cannot be accidentally omitted. After an upload, list the exact remote path recursively and verify the manifest and module files are directly under the intended artifact directory.

## Python Kestra task entrypoint

Every Python Kestra task must begin with:

```python
from bootstrap import ctx
```

Shared environment parsing, runtime path setup, Kestra client access and immutable bundle verification belong in `core/docker/bootstrap.py`. Task scripts should contain only stage-specific operations and outputs.

## Runtime and release integrity

- Approved production runtime bundles are immutable under `var/releases/approved/<release-id>/runtime/`. The current Core runtime snapshot under `core/kestra/namespace-files/runtime/releases/2.0.0/` is the explicit bootstrap baseline before the first approved release. Modules may use it only when that exact baseline is selected and no approved release with the same ID exists. The platform version, Core runtime version, DEV candidate ID and approved release ID are distinct.
- DEV runtime candidates and historical tooling bundles are content-addressed. Candidate creation does not predict or reserve an approved production release ID; the Production assembler requires that ID explicitly after evaluation and approval.
- The production deployment workflow accepts only an immutable package under `var/releases/approved/`, manually dispatched from protected `main` with the exact release ID. A platform version tag is not a production deployment trigger.
- The flow's manifest digest must be derived from the exact `release-manifest.json` bytes in the selected bundle.
- Do not copy a digest from a previous release or manually edit individual task pins. Use the Lifecycle candidate builder and Production approved-release assembler. The approved-release assembler is the only supported production package writer; there is no in-place production-flow updater. Modules must not edit Core source.
- Keep the Docker task image, Namespace Files path and runtime manifest pin aligned.

## Orchestration boundary

Kestra owns task order, dependencies, retries, fan-out, isolated task execution and artifact hand-off. Python modules own underwriting calculations, source access through connector contracts, and replay comparisons. Do not move business policy or data-source-specific SQL into Kestra expressions.

### Express task ordering with Kestra flowables, not `dependsOn` on runnable tasks

A normal top-level `tasks:` list executes in order. Use `io.kestra.plugin.core.flow.Parallel` when independent tasks should run concurrently. For historical replay, the supported topology is:

1. `validate_dataset` runs first.
2. `replay_pair` is a `Parallel` flowable with `concurrent: 2` and `onChildFailure: FAIL`; it contains `baseline_replay` and `candidate_replay`.
3. `compare_replays` runs after the parallel block completes and consumes both replay output files.

Never put `dependsOn` on `io.kestra.plugin.scripts.python.Commands`; the server rejects that property. If a future workflow needs a dependency graph rather than ordered lists or parallel branches, use the dedicated `io.kestra.plugin.core.flow.Dag` flowable and validate it against the target server.

Every operator flow deployment must be preceded by `kestractl flows validate <flow.yaml>`. In publication workflows, validate before any Namespace Files upload, so schema or plugin errors do not leave partially published immutable artifacts. `kestractl flows validate` is a server-side check; generic YAML parsing and local unit tests are not substitutes.

### Kestra YAML sequence indentation

Deployable Kestra flow YAML must indent every sequence item two spaces beneath
its owning mapping key. In particular, write `tasks:` followed by `  - id: ...`,
not PyYAML's default indentless `tasks:` followed by `- id: ...`. The latter is
valid YAML and may deploy, but the Kestra flow topology view can fail to render
the task graph correctly. `tools/kestra/yaml.py` enforces this using a custom
`SafeDumper.increase_indent()` override. All generated flows must pass the
`test_all_checked_in_kestra_flows_are_parser_safe_and_visually_indented` repository check, which also
checks explicit task-list indentation.
