# Evaluation

Evaluation builds and runs paired historical replay flows in Kestra DEV. It binds one exact baseline release and one immutable candidate to the same frozen dataset, runs both sides, and compares outputs only after both branches succeed. It does not call live providers to fill missing historical evidence and it does not mutate or deploy production.

Generated manual replay-flow definitions are stored under `var/artifacts/replay-flows/`. Completed comparison output must be registered as an immutable evaluation artifact under `var/artifacts/evaluations/` before it can be referenced by an approval attestation.


For the complete object lifecycle, storage locations, identity model and immutability rules, see the [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md).

## Run and interpret an evaluation

| Guide | Use it to… |
|---|---|
| [End-to-end DEV workflow](../../docs/development/end-to-end-dev-workflow.md) | Build the replay flow, publish/reuse immutable bundles, run a 100-case smoke replay and then the full portfolio replay. |
| [Historical data and replay](../../docs/development/historical-data-and-replay.md) | Understand the frozen dataset, paired execution, integrity rules and reproducibility contract. |
| [Champion vs Challenger report](../../docs/development/champion-challenger-impact-report.md) | Read decision migrations, stage outcomes, score deciles, segments, source coverage and evidence outputs. |
| [Governed release boundary](../../docs/production/production-release-workflow.md) | Register evaluation evidence and bind it to the exact candidate/baseline/dataset before requesting approval. |

**Evaluation boundary:** successful replay demonstrates reproducibility and outcome differences on the selected dataset. It does not by itself approve a candidate or establish real-world loss performance.
