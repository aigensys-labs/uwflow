# Workflow command index

The workflow scripts provide one-command entry points for local setup, DEV deployment, historical replay and Policy Studio operation. Run them from the UWflow repository root—the directory containing `pyproject.toml`, `docker-run.sh` and `tools/`.

Each command is launched with `bash`. Python-based scripts activate and verify `var/venv` within their own process. Step 01 creates it when missing, reuses it only when valid, and rebuilds an incomplete environment. Shared shell functions and credential generators live under `lib/`; run the numbered entry points rather than calling those helpers directly.

## Complete local DEV setup

```bash
bash tools/guides/workflow/dev-fast-route.sh
```

The [DEV Fast Route guide](../../../docs/development/dev-fast-route.md) describes the full sequence, validation gates, expected services and recovery path.

## Setup and deployment commands

| Step | Command | Operation |
|---|---|---|
| 00 | `00-preflight.sh` | Check Linux, Python, Bash, Docker and Compose |
| 01 | `01-python-environment.sh` | Create or repair `var/venv`, install project extras, run checks and materialize/verify the History tooling bundle |
| 02 | `02-build-studio-images.sh` | Build the Studio API and frontend images |
| 03 | `03-create-local-credentials.sh` | Create local Kestra credentials |
| 04 | `04-create-history-credentials.sh` | Create/reuse or reconcile the paired PostgreSQL and Kestra history credentials |
| 05 | `05-build-task-image.sh` | Build the versioned Python task image |
| 06 | `06-start-history-database.sh` | Start/reuse PostgreSQL and verify health plus owner authentication |
| 07 | `07-start-kestra.sh` | Start local Kestra |
| 08 | `08-install-kestra-cli.sh` | Verify `kestractl`; request approval before installing it when absent |
| 09 | `09-deploy-dev-baseline.sh` | Validate and deploy the manual DEV baseline |
| 10 | `10-initialize-history-database.sh` | Initialize or upgrade history schemas and database roles |
| 11 | `11-select-or-create-dataset.sh` | Select or create and checksum-validate an immutable dataset |
| 12 | `12-run-local-noop-replay.sh` | Replay the baseline and reference candidate locally |
| 13 | `13-build-history-replay-flow.sh` | Build the immutable history-tools bundle and paired replay flow |
| 14 | `14-publish-history-replay-flow.sh` | Validate, publish/reuse immutable bundles and deploy the DEV replay flow |
| 15 | `15-start-studio.sh` | Start the complete Dockerized Policy Studio |
| 16 | `16-stop-studio.sh` | Stop the Policy Studio containers |

## Policy and repository commands

| Step | Command | Operation |
|---|---|---|
| 17 | `17-verify-policy-save.sh` | Verify saved policies, generated Python, tests and runtime bundle |
| 18 | `18-verify-studio-candidate.sh` | Validate and record a Studio candidate and its baseline |
| 21 | `21-stop-history-database.sh` | Stop PostgreSQL while retaining its persistent volume |
| 22 | `22-verify-repository.sh` | Compile policies, run tests and build/reuse then verify immutable bundles |
| 23 | `23-initialize-github-repository.sh` | Prepare and optionally publish a new GitHub repository |
| 90 | `90-diagnostics.sh` | Display container, logs and workflow-state diagnostics |

This numbered command index is for the full platform workflow. For the Core-only seven-stage demo, follow the [Core first-run guide](../../../core/kestra/README.md). For the full platform, use the [End-to-end DEV workflow](../../../docs/development/end-to-end-dev-workflow.md) or the [DEV Fast Route](../../../docs/development/dev-fast-route.md).
