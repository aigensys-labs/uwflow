# UWflow Core

**Core is the original, complete UWflow underwriting system—not an empty or domain-neutral task runner.**

It is independently usable and can execute the full seven-stage underwriting journey in either of two ways:

1. **Kestra + Docker:** Kestra orchestrates seven stages; isolated Python task containers execute the version-pinned Core runtime.
2. **Direct Python:** the Core CLI executes the same underwriting logic locally and generates the Stage 7 applicant reports without starting Kestra.

Core includes the complete original decision path: input validation and hard gates, bureau assessment, consent/source planning, alternative-data execution, AIDflow inference, UWflow decisioning, and basic applicant report generation.

## What belongs to Core

| Area | Contents |
|---|---|
| `docker/` | Core Python task image, Kestra bootstrap and the dependencies required by the seven stages. |
| `kestra/` | Local Kestra launcher, seven-stage DEV baseline flow, production execution-flow contract and immutable runtime releases. |
| `python/runtime/` | Canonical nine-file Python runtime loaded by both the Kestra flow and local runner. |
| `python/` | Direct seven-stage CLI and local execution adapter. |
| `underwriting/policies/` | Baseline policy definitions and field catalog used by Core. |
| `underwriting/examples/` | Synthetic application examples and applicant report examples. |
| `underwriting/tools/` | Immutable Core runtime bundle builder and verifier. |

The flat nine-file import contract inside Kestra Namespace Files remains unchanged. The source lives in `core/python/runtime/`; immutable version snapshots live in `core/kestra/namespace-files/runtime/releases/<version>/`.

## Run Core with Python

From the repository root:

```bash
python -m core.python.cli
```

Run a particular example and select the output directory:

```bash
python -m core.python.cli --input core/underwriting/examples/applications/application_default.json --output-dir var/reports
```

The command executes Stages 1–6 through the Core engine and Stage 7 through the Core applicant report renderer. It generates `underwriting_decision.json`, `underwriting_decision.html` and `underwriting_decision.pdf`. It requires the Core Python dependencies only; it does not start Kestra, Docker, PostgreSQL or any platform module.

## Run Core through Kestra

See the [Core Kestra guide](kestra/README.md). The Core-only execution path requires Docker Engine, a local Kestra instance, the Core task image and the immutable Core runtime release. It does not require Policy Studio, History, Evaluation, Reporting or Production modules.

## Dependency boundary

The Core task image is `ai/uwflow-core-runtime:<version>`. It includes the Kestra Python adapter and the report renderer dependency required by Core Stage 7. The optional `ai/uwflow-runtime:<version>` image extends Core with module dependencies such as PostgreSQL and Parquet support. Core flows use the Core image and do not depend on the platform image.

## What Core deliberately does not include

Core does not need the following modules to process one application:

- analyst-facing Policy Studio;
- content-addressed DEV candidate lifecycle;
- historical portfolio storage and dataset management;
- champion–challenger replay orchestration;
- comparative portfolio impact reporting;
- protected Git-based production promotion and release governance.

Those capabilities are introduced in the root README under [What Modules add](../README.md#what-modules-add), with practical operator guides on each module page. They consume and govern Core; they do not replace its decision engine.
