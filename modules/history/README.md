# History

History owns historical case storage and access: dataset contracts, canonicalization, PostgreSQL/Parquet connectors, point-in-time snapshots and synthetic portfolio generation. It supplies frozen evidence to Evaluation; it does not decide underwriting policy, execute the seven-stage Core decision or publish production flows.

Replay helper bundles are immutable build outputs under `var/artifacts/tool-bundles/history/<bundle-id>/`, not source files under the Module. A clean package does not contain a pre-generated bundle: full-platform setup builds or reuses it from the tracked History/Reporting sources, then verifies its content-addressed manifest. The later replay workflow reuses that exact bundle ID. The bundle's internal Namespace Files layout contains the History scripts and tools used by the Kestra replay tasks.


For the complete object lifecycle, storage locations, identity model and immutability rules, see the [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md).

## Use History

| Guide | Use it to… |
|---|---|
| [Historical data and replay](../../docs/development/historical-data-and-replay.md) | Understand the dataset contract, point-in-time rules, PostgreSQL/Parquet storage, checksum validation and replay data path. |
| [End-to-end DEV workflow](../../docs/development/end-to-end-dev-workflow.md) | Initialise the database, create or select the synthetic FSTPD30 dataset, validate it and run local/Kestra replay. |
| [DEV Fast Route](../../docs/development/dev-fast-route.md) | Prepare the full local platform and run the short paired-replay demonstration with one command. |

**Data boundary:** datasets are immutable and versioned. Replay uses only the source evidence available at the original decision time; missing historical observations are not filled with live provider calls. Synthetic outcomes demonstrate software behavior, not realised lending performance or calibrated risk.
