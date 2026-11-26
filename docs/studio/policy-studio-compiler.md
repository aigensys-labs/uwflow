# Policy specifications and compiler

UWflow uses one deterministic policy compiler, but there are two distinct ownership paths: **Core maintainers** update Core's canonical default strategy through reviewed source changes; **analysts** edit independent workspace copies through Policy Studio. An analyst save never regenerates or writes Core runtime source.

## Ownership and compilation contract

- `core/underwriting/policies/` contains the checked-in default policy specifications and field catalogue owned by Core.
- `core/python/runtime/policy_generated.py` is the generated runtime implementation for the Core default strategy. It changes only through an explicit Core-maintainer source change and Git review.
- `var/workspaces/strategies/<workspace-id>/policy-specs/` contains mutable analyst-owned copies of the editable policy specifications.
- `var/workspaces/strategies/<workspace-id>/generated/policy_generated.py` contains the generated preview for that workspace. It is not imported by the live Core runtime.
- `var/artifacts/candidates/<candidate-id>/` contains the immutable candidate runtime/policy snapshot and its provenance manifests. The Lifecycle builder compiles the selected workspace policy specs and packages the output with the workspace-pinned Core runtime.
- `var/releases/approved/<release-id>/` is the only deployable production package boundary. It is assembled after evaluation and explicit approval.

The compiler accepts a small allow-listed condition model. It validates schemas, field types, operators, graph structure and registered source IDs, then deterministically emits Python. It does not accept arbitrary analyst Python or executable expressions.

## Core-maintainer changes versus analyst changes

### Core default strategy maintenance

A Core maintainer may intentionally change the canonical default policy and generated runtime as a reviewed code change. From the repository root:

```bash
python -m tools.policy.compiler --check
```

The maintained compiler defaults to `core/underwriting/policies/stages/`, the Core field catalogue and `core/python/runtime/policy_generated.py`. If the Core default policy is deliberately changed, compile the generated Core module, rebuild and verify the immutable Core runtime bundle, review the complete diff, and publish it through the Core release process. This is not the analyst workflow.

`tools/compile_policy_spec.py` is a Core-only CLI alias retained for the direct Core maintenance workflow. The canonical maintained command is `python -m tools.policy.compiler`.

### Analyst workspace changes

Policy Studio loads the selected workspace's JSON, validates it using the same compiler, and saves the JSON plus generated preview only under that workspace. Lifecycle recompiles the selected workspace specifications during candidate construction and rejects stale generated preview code. No analyst save or candidate build writes `core/`.

A workspace can be created from Core defaults or forked from any available DEV candidate or approved release. Forking copies only editable policy specs into a new workspace and records the source artifact manifest hash, parent workspace identity, and pinned Core runtime/production-flow-template paths. The original source artifact is not modified or duplicated.

## Stage 1 — Hard Gates

`stage1_hard_gates.json` defines six checks in the runtime's established order:

1. `APPLICATION_DATA_VALID`
2. `MINIMUM_AGE`
3. `MINIMUM_INCOME`
4. `EMPLOYMENT_STATUS`
5. `REQUEST_AMOUNT`
6. `LOAN_TERM`

Each check defines one positive `valid_when` predicate and one failure reason code. A matching predicate produces `PASS`; its logical complement produces `FAIL`. The evaluator checks all six rules independently, preserving multiple failures in the result.

Parsing, normalization and application-data validation remain in `core/python/runtime/hard_gates.py`. Missing or incorrectly typed values fail closed. Evaluation results include matched policy rule IDs in `policy_trace`.

## Stage 3 — Source Planning

`stage3_source_plan.json` defines a directed acyclic graph using three allow-listed context fields: `hard_gates_passed`, `bureau_decision_status` and `data_sharing_consent`. It evaluates hard-gate result, bureau status and consent in sequence. When collection is permitted, it returns the configured source plan; otherwise, it returns the no-collection outcome.

The compiler checks node/edge references, reachability, graph cycles, default edges, condition priorities, field/operator compatibility and source IDs. The generated function returns a typed source plan. It does not call source adapters or create Kestra tasks; Kestra Stage 4 remains responsible for source execution.

## Candidate and release identity

The platform version (`pyproject.toml`), Core runtime release, DEV candidate ID and approved production release ID are separate identities. Candidate construction records its baseline and exact source hashes but does not calculate, reserve or predict an approved production release ID. The release ID is supplied explicitly to the Production assembler after the candidate has evaluation evidence and an approval attestation.

Candidate creation is local-only. Publishing the candidate to `com.ai.credit.dev`, running replay, registering evaluation evidence, assembling the approved release and deploying to PROD are separate steps. Production deployment is manually dispatched from protected `main` with the exact approved release ID; `v*` tags do not trigger deployment.
