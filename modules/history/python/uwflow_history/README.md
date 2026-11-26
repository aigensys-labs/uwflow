# Historical data package

This package defines the independent historical-case contract, canonical serialization,
PostgreSQL and Parquet connectors, deterministic synthetic portfolio generation and replay
models. It is used by the repository's `tools/history/` commands and by the history-tools
bundle builder.

The source package lives at the repository root and is distributed as `uwflow_history`. The `modules.history.tools.history_tools_bundle` builder maps these source files into the
immutable Kestra Namespace Files execution layout under `scripts/uwflow_history/`. That virtual
artifact path is a deployment contract, not an alternate source-code location or fallback path.
