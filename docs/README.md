# UWflow documentation

This index is organized around what a user wants to do. Choose a run path first; use the module landing pages for the practical procedures inside the full platform.

## Run UWflow

| Goal | Start here | Scope |
|---|---|---|
| **Run Core only** | [Core first-run guide](../core/kestra/README.md) | The standalone seven-stage underwriting demo through Python and Kestra. No platform Modules or History services. |
| **Run the full platform quickly** | [DEV Fast Route](development/dev-fast-route.md) | One-command setup, Core smoke test, paired replay and Policy Studio startup. |
| **Run the full platform step by step** | [End-to-end DEV workflow](development/end-to-end-dev-workflow.md) | Detailed setup, dataset validation, local and Kestra replay, policy editing and candidate creation. |

## Operate the platform modules

Each module page is the operator entry point for that capability. It explains what the module owns, what it deliberately does not do, and which focused guides to follow. The guides are linked there rather than duplicated in this index.

| Capability | Operator entry point |
|---|---|
| Policy authoring and workspace editing | [Policy Studio](../modules/policy-studio/README.md) |
| Workspace and immutable candidate lifecycle | [Lifecycle](../modules/lifecycle/README.md) |
| Historical datasets and source evidence | [History](../modules/history/README.md) |
| Paired champion–challenger replay | [Evaluation](../modules/evaluation/README.md) |
| Comparative impact reports | [Reporting](../modules/reporting/README.md) |
| Approval, release assembly and deployment | [Governed release boundary](../modules/production/README.md) |
| Optional module task-image dependencies | [Platform Runtime](../modules/platform-runtime/README.md) |

## Architecture and engineering

Use these references to understand ownership boundaries, contribute safely and verify the package.

| Reference | Contents |
|---|---|
| [System architecture](architecture/architecture.md) | Component boundaries, Kestra task contract, execution isolation, history/replay and release immutability. |
| [Core and Modules](architecture/core-and-modules.md) | Why Core runs independently and how Modules operate around it. |
| [UWflow lifecycle and storage model](architecture/lifecycle-and-storage.md) | Authoritative lifecycle, object identities, storage locations, ownership and immutability rules from workspace through deployment. |
| [Engineering conventions](architecture/engineering-conventions.md) | Flow generation, YAML serialization, Namespace Files and Python task conventions. |
| [Workflow command index](../tools/guides/workflow/README.md) | Numbered operator-script entry points for the full platform workflow. |
| [Repository tooling map](../tools/README.md) | Build, policy, history, Kestra and release utilities. |
| [Test suite map](../tests/README.md) | Test coverage by system boundary. |
| [Contributing](../CONTRIBUTING.md) | Development setup, architecture rules and pull-request expectations. |
