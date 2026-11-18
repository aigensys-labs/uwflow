# First local run — from zero to a working UWflow demo

This guide starts Kestra, uploads the approved Python release into Kestra, deploys the flow and runs the John Jones example.

**Time:** about three minutes once Docker has the required images. The first run can take longer because Docker and Kestra download files.

> **Demo only:** this package uses synthetic bureau and alternative-data results. It is not approved for real lending. Read [Production readiness](PRODUCTION_READINESS.md) before connecting real data or making real credit decisions.

## Before you start

You need Docker running, Python 3.11 or newer, this repository extracted, and a terminal opened in the repository folder. On Windows, use WSL with Docker Desktop integration. This guide targets Kestra Open Source; you do not need to create a namespace first.

**Already have Kestra running from an older UWflow setup?** Stop it before Step 2 and start it again with this repository's launcher. This version adds a webhook secret; a running container cannot receive a new environment value. The Docker volumes keep your existing Kestra data. If your current server was already started with this repository's `.env`, you can leave it running and skip Step 2.

## 0. Clone the UWflow repo

```bash
git clone https://github.com/aigensys-labs/uwflow.git
cd uwflow
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

**Why:** your local machine needs the package importable so that tests, linters, and the `uwflow-demo` / `uwflow-report` entry points work from the terminal. The venv isolates dependencies from your system Python; the `-e` flag makes source edits take effect immediately without re-installing; `.[dev]` pulls in `reportlab`, `pytest`, `PyYAML`, and `ruff`. 

## 1. Create a local login

```bash
chmod +x ./tools/create-local-env.sh
./tools/create-local-env.sh
```

Keep the password printed by the command. You will use it to sign in to Kestra. If the script says `.env` already exists, it has left the file untouched. Check that it contains `SECRET_UNDERWRITING_WEBHOOK_KEY`. If it is missing or still has the example placeholder, back it up and generate a fresh file:

```bash
cp .env .env.backup
rm .env
./tools/create-local-env.sh
```

**Why:** the local server needs a login, and the webhook needs its own secret. The script creates both in `.env`, makes the file private to your user, and uses the Base64 format expected by Kestra Open Source. It never overwrites an existing `.env`.

## 2. Pre-build docker image


```bash
chmod +x ./tools/build-docker.sh
./tools/build-docker.sh
```

**Why**: Pre-building aigensys/uwflow-runtime:1.2.2 locally ensures that Kestra's Docker task runner executes Python tasks and parallel fan-outs instantly (~0.2s) without triggering runtime package installation (uv/pip) inside every container.


## 3. Start Kestra

```bash
chmod +x ./docker-run.sh
./docker-run.sh
```

Leave this terminal open. When the log says the server is running, open **http://localhost:8080** and sign in with the username and password from Step 1.

If the launcher says a stopped container named `kestra` already exists, remove only that container and retry:

```bash
docker rm kestra
./docker-run.sh
```

Your `kestra_data` and `kestra_db` volumes are not removed by this command.

**Why:** this starts a local Kestra server and gives it Docker access so each Python task can run in its own container. The repository's Python files are not mounted into Kestra. Kestra will receive the approved release in Step 6. Docker's socket gives Kestra control over the local Docker daemon, so this launcher is for a single-user demo only.

## 4. Install the Kestra command-line tool

Open a **second terminal** in the repository folder. Run:

```bash
curl -fsSL https://raw.githubusercontent.com/kestra-io/kestractl/main/install-scripts/install.sh | bash
kestractl --help
```

**Why:** the command-line tool sends the release files and flow to Kestra through its API. There is no copying into Docker and no pasting Python into YAML.

## 5. Connect that terminal to Kestra

Run these commands in the second terminal:

```bash
source .env

export KESTRACTL_HOST="http://localhost:8080"
export KESTRACTL_TENANT="main"
export KESTRACTL_USERNAME="$KESTRA_SERVER_BASIC_AUTH_USERNAME"
export KESTRACTL_PASSWORD="$KESTRA_SERVER_BASIC_AUTH_PASSWORD"
```

If you kept an already-running server, replace the two values above with the username and password that server already uses. For a server restarted with the new `.env`, use the credentials printed in Step 1.

**Why:** this tells the command-line tool which local Kestra server and login to use. The settings live only in this terminal session; they are not saved in the repository.

## 6. Check the release before uploading

```bash
source .venv/bin/activate
python tools/build_runtime_bundle.py --check
```

You should see: `Verified immutable runtime release v1.2.2 (8 modules)`.

**Why:** this compares the Python source under `scripts/` with the versioned files that will be uploaded. It catches accidental differences before they reach Kestra.

## 7. Upload the approved Python release

```bash
kestractl nsfiles upload com.aigensys.credit.production \
  ./kestra/namespace-files/runtime/releases/1.2.2 \
  runtime/releases/ \
  --fail-fast --allow-missing-namespace
```

**Why:** this sends the exact, versioned Python files to Kestra through its API. The flow will run these files, not files from your laptop. On Kestra Open Source, namespaces are implicit, so the CLI option skips a namespace pre-check that is not available in OSS. The release folder is immutable: do not add `--override`. A new code change must use a new release number.

Wait for the upload to finish successfully, then verify it:

```bash
kestractl nsfiles list com.aigensys.credit.production \
  --path runtime/releases/1.2.2 --recursive
```

You should see the Python modules and `release-manifest.json`.

## 8. Deploy the flow

```bash
kestractl flows deploy ./kestra/flows/uwflow_production_underwriting.yaml \
  --override --fail-fast
```

**Why:** this installs the workflow definition in Kestra. It is safe to update this stable flow from reviewed source; the versioned Python files uploaded in Step 6 stay unchanged.

## 9. Run the sample application

In Kestra, open **Flows → com.aigensys.credit.production → uwflow_production_underwriting**. Select **Execute** and keep the default John Jones inputs.

The workflow runs hard gates, bureau assessment, ten synthetic data sources, AIDflow scoring, UWflow decisioning, and report generation.

Open the execution. When it succeeds, open the `stage7_render_report` task outputs and download the HTML, PDF and JSON reports.

For the default John Jones example, the synthetic result should be **APPROVED**, with an AIDflow customer-profile score of **837/900**, an approved amount of **€8,194.20**, and an illustrative APR of **8.9%**. These figures are only a quick check that you ran the expected demo input.

**You are done when:** the execution is green and all three report files are available.

---

## If something does not work

| What you see | What to do |
|---|---|
| `docker: invalid reference format` | Use the flow included in this repository. Its Python image is `python:3.11.18-slim-trixie`, without an `@sha256` suffix. |
| `kestractl: command not found` | Close and reopen the second terminal, then run `kestractl --help`. Check the installer's message if it is still missing. |
| Namespace does not appear in the UI before deployment | This is expected on Kestra Open Source. Namespaces are implicit; upload the files with `--allow-missing-namespace`, then deploy the flow. |
| Upload says the release path already exists | Do not force an overwrite. Compare the remote `release-manifest.json` with the local one. |
| Python cannot import a module | Run `kestractl nsfiles list com.aigensys.credit.production --path runtime/releases/1.2.2 --recursive` and check that the module is present. Then confirm `python tools/build_runtime_bundle.py --check` passes locally. |
| Kestra cannot download a plugin or Python image | The first execution needs internet access. Check the Kestra terminal, restore connectivity and retry. |
| Port 8080 is already in use | Reuse the Kestra server already running, or stop it before starting another. |

## What this setup is — and is not

This guide gets the **local synthetic demonstration** running. It does not create a production lending service. Real underwriting requires approved data providers and consent, a validated AIDflow model, governed UWflow policy, controlled identities and deployment approvals, durable storage, monitoring, and independently retained audit evidence. See [Production readiness](PRODUCTION_READINESS.md).

## Official Kestra references

- [Namespace Files](https://kestra.io/docs/concepts/namespace-files)
- [Docker Task Runner](https://kestra.io/docs/task-runners/types/docker-task-runner)
- [kestractl commands](https://github.com/kestra-io/kestractl)
- [Kestra local quickstart](https://kestra.io/docs/quickstart)
