# Run the seven-stage Core demo through Kestra

This is the Core-only first-run guide. It takes a new user from a clean checkout to a successful seven-stage Kestra execution and applicant reports. Core can also run directly through Python; the same environment is prepared in Step 1.

No Policy Studio, Lifecycle, History database, Evaluation, Reporting Module or Production Module setup is required. The only services used for this demo are Docker and local Kestra.

## Prerequisites

- Native Linux with Bash.
- Docker Engine and the Docker Compose V2 plugin, running and accessible to your user.
- Python 3.11 or newer, with the `venv` module available.
- `openssl` for the local Kestra credential helper.
- Internet access for the initial Python and Docker image downloads.

Extract the package and open a Bash terminal in the extracted repository root—the directory containing `pyproject.toml`, `docker-run.sh`, `core/` and `tools/`. Run all commands from that directory.

## 1. Prepare the minimal Core Python environment

Create a project virtual environment and install the base package. The base installation includes Core's required dependencies (including the Stage 7 PDF renderer); it does not install the optional Studio, History, Parquet or development/test extras.

```bash
python3 -m venv var/venv
source var/venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the direct seven-stage Core demo now, before introducing Kestra:

```bash
python -m core.python.cli --output-dir var/reports/local
```

The command should complete all seven stages and produce JSON, HTML and PDF applicant reports under `var/reports/local/`. This proves that the Core engine works independently of Kestra and the platform Modules.

> **Important:** do not run `tools/guides/workflow/01-python-environment.sh` for this Core-only demo. That script deliberately installs the complete platform development/test environment. The minimal setup above is sufficient.

## 2. Create local Kestra credentials

```bash
bash core/scripts/create-local-credentials.sh
```

The script creates a private `.env` file and prints the local username and password. Keep them private. Existing valid credentials are reused rather than regenerated.

## 3. Build the Core task image and start Kestra

Build only the Core image. The optional platform image is not needed:

```bash
bash tools/docker/build-images.sh --core-only
```

Open a second terminal in the same repository root and start local Kestra:

```bash
bash core/docker-run.sh
```

Keep this terminal open. Kestra runs in the foreground at [http://localhost:8080](http://localhost:8080). Sign in with the credentials created in Step 2.

The local launcher uses Docker Task Runner to start an isolated container for each Python task. It mounts the Docker socket, which grants the Kestra container powerful control over the host Docker daemon; use this launcher only for a trusted local demo environment. It does not mount Core source into the Kestra server.

## 4. Install the Kestra CLI and deploy the Core baseline

Return to the setup terminal. Install `kestractl` if it is not already available:

```bash
bash tools/guides/workflow/08-install-kestra-cli.sh
```

Then validate, publish the immutable Core runtime bundle and deploy the manual DEV flow:

```bash
bash tools/guides/workflow/09-deploy-dev-baseline.sh
```

The deployment script activates the `var/venv` created in Step 1. It validates the flow against the connected Kestra server, verifies the runtime files against their manifest, checks the remote Namespace Files path and refuses to overwrite existing immutable content. The flow is deployed to `com.ai.credit.dev` only.

## 5. Execute the seven-stage underwriting demo

In the Kestra UI:

1. Open namespace `com.ai.credit.dev`.
2. Open flow `uwflow_dev_baseline_v2_0_0`.
3. Choose **Execute** and retain the default synthetic input values.
4. Wait for all seven stages to finish.
5. Open task `stage7_render_report` and download the HTML, PDF and JSON outputs.

The packaged reference application is expected to return `APPROVED`, an AIDflow profile score of `837/900`, an approved amount of `€8,194.20` and an indicative APR of `8.9%`. These deterministic outputs are demonstration fixtures, not lending recommendations or validated risk estimates.

The Core-only Kestra demo is complete when the execution succeeds and all three applicant-report artifacts are available.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| Deployment reports that `var/venv` is missing or incomplete | Return to Step 1, create/activate `var/venv` and run `python -m pip install -e .`; then rerun the deployment command. |
| `docker info` fails or the image build cannot start | Start Docker Engine and verify that your user can access the Docker daemon. |
| The Core task image is unavailable | Rerun the Core-only image build in Step 3. Use `--replace-existing` only when intentionally rebuilding an existing local tag. |
| A container named `kestra` is already running | Reuse that local instance only if it is the intended UWflow Kestra server. Otherwise inspect it before stopping/removing it; preserve the `kestra_data` and `kestra_db` volumes. |
| `kestractl` is still not found | Rerun the installer. Workflow scripts add `~/.local/bin` to their own `PATH` when needed. |
| A Python task takes a few seconds to start | Docker Task Runner starts a separate container for each task. The prebuilt image avoids repeated dependency installation, not container startup. |

## Add the full UWflow platform

The platform extends Core with strategy workspaces, Policy Studio, historical data, paired champion–challenger evaluation, comparative reporting and controlled production release. Choose one of these guides:

- [DEV Fast Route](../../docs/development/dev-fast-route.md) for the automated local setup and short replay demonstration.
- [End-to-end DEV workflow](../../docs/development/end-to-end-dev-workflow.md) for the detailed setup, dataset validation, replay and policy-change walkthrough.
