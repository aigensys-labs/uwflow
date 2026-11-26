# Operator commands and repository tooling

The root `tools/` tree contains shared operator commands and cross-module adapters. It is
not a second implementation home for Lifecycle, History, Evaluation or Core runtime
builders. Those implementations live with the owner module.

## Command map

| Path | Responsibility |
|---|---|
| [policy/](policy/) | Canonical Core policy validation, deterministic compilation and reviewed Core policy-schema migration |
| [history/datasets/](history/datasets/) | Generate, list and validate immutable datasets |
| [history/database/](history/database/) | Database schema and least-privilege role bootstrap |
| [history/replay/](history/replay/) | Local replay, cohort execution and paired-result comparison |
| [kestra/](kestra/) | Shared CLI construction, flow serialization and Namespace Files operations |
| [demo/](demo/) | Local synthetic application and report commands |
| [docker/](docker/) | Build the Core and optional platform task images |
| [guides/workflow/](guides/workflow/) | One-command operator procedures and their shell helpers |

## Implementation ownership

- `core/underwriting/tools/runtime_bundle.py` builds and verifies the immutable Core runtime bundle.
- `modules/lifecycle/tools/dev_candidate.py` builds immutable DEV candidates from selected workspaces.
- `modules/history/tools/history_tools_bundle.py` builds immutable History tooling bundles.
- `modules/evaluation/tools/history_replay_flow.py` builds paired replay flows.
- `modules/production/tools/release/` assembles approved production releases.
- `tools/kestra/` remains shared because Core and multiple modules use the same Kestra command and YAML contracts.

Run Python commands from the repository root. Examples:

```bash
python -m tools.policy.compiler --check
```

```bash
python -m core.underwriting.tools.runtime_bundle --check
```

```bash
python -m modules.history.tools.history_tools_bundle --check
```

```bash
python -m modules.lifecycle.tools.dev_candidate --help
```

Build Docker task images with `bash tools/docker/build-images.sh`. The `--core-only`
option builds only the standalone Core image; `--push` pushes selected tags. Approved
production release assembly still requires an immutable registry `repo@sha256:...`
image reference.

Use the `bash tools/guides/workflow/<step>.sh` command shown in each operator guide for
environment setup, publishing, replay and Studio lifecycle. The scripts validate the
repository root and initialize the project Python environment where required. They do
not silently install missing system packages or remove Docker volumes.

## Core-maintainer-only migration

The maintained Core policy compiler is `tools/policy/compiler.py`; use
`python -m tools.policy.compiler`. The Step 20 migration launcher intentionally modifies
the Core default policy/runtime and is reserved for reviewed Core maintenance. Analysts
must use Policy Studio workspaces. Production owns release assembly under `modules/production/tools/release/`. Platform Modules
use the current v2 module-owned artifact locations and explicit release entry points.

## Kestra artifact paths

Kestra Namespace Files paths are runtime contracts, not source-tree paths. Underwriting
runtime bundles are published under `runtime/releases/` and `runtime/candidates/`, while
History helpers use `history-tools/` and the virtual package path
`scripts/uwflow_history/`. Do not rename or overwrite an already-published immutable
artifact.

## Write boundaries

Policy Studio and Lifecycle write to `var/workspaces/` and `var/artifacts/candidates/`; History
and Evaluation write immutable bundles/evidence under `var/artifacts/`; the approved-release
assembler writes to `var/releases/approved/`; deployment automation writes to
`deployments/`. Modules must not write Core source. The retained Step 20 migration
command is a separate Core-maintainer operation and must not be used for analyst strategy
work.
