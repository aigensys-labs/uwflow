# Lifecycle

Lifecycle manages analyst strategy workspaces and immutable DEV candidate snapshots. It does not own Core source and never writes into `core/`.

A workspace can start from Core defaults or be forked from a verified candidate or approved release. The fork contains independent editable policy specifications and records the exact source identity; it does not duplicate or mutate the source runtime. Candidate construction pins the selected Core runtime, policy hashes, baseline and Kestra flow template into `var/artifacts/candidates/<candidate-id>/`. Building a candidate is local-only: it does not publish to Kestra, create evaluation evidence, approve a release or deploy production.

Only the current v2 candidate contract is accepted. A source must pass its manifests, policy specifications, candidate flow, production-flow template and declared checksum checks. Only artifacts that satisfy the current v2 manifests, schemas, identities and checksum contract are accepted.


For the complete object lifecycle, storage locations, identity model and immutability rules, see the [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md).

## Use Lifecycle

| Guide | Use it to… |
|---|---|
| [Policy Studio — local authoring](../../docs/studio/policy-studio.md) | Create a workspace from Core defaults or fork an existing verified candidate/approved release. |
| [DEV candidate lifecycle](../../docs/studio/policy-studio-dev.md) | Choose a baseline, build a candidate, understand its immutable identity and prepare DEV publication/replay. |
| [Governed release boundary](../../docs/production/production-release-workflow.md) | Continue from an evaluated candidate through evidence registration, approval and approved-release assembly. |
| [End-to-end DEV workflow](../../docs/development/end-to-end-dev-workflow.md) | Run the complete workflow, including local and Kestra replay and a controlled policy change. |

## Main artifact boundary

- Mutable workspace: `var/workspaces/strategies/<workspace-id>/`
- Immutable candidate: `var/artifacts/candidates/<candidate-id>/`
- Immutable approved release: `var/releases/approved/<release-id>/`

Candidate provenance includes workspace ancestry, baseline identity, Core runtime hashes, policy hashes, source-tree status and production-flow-template hash. Only a candidate built from a clean protected Core tree is eligible for production release assembly.
