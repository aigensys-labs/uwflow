# Deploying UWflow to Kestra

## First local run

For the shortest guided setup, follow [First local run](FIRST_RUN.md). It uses the Kestra CLI to upload the immutable Python bundle into Namespace Files and then deploys the flow. No `/app/scripts` host mount is required.

## What is deployed

- Flow: `kestra/flows/uwflow_production_underwriting.yaml`
- Runtime bundle: `kestra/namespace-files/runtime/releases/1.2.2/`
- Kestra namespace: `com.ai.credit.production`
- Runtime image for this demo: `python:3.11.18-slim-trixie`

## New release procedure

1. Change source modules under `scripts/` and add or update tests.
2. Bump `project.version` in `pyproject.toml`.
3. Update the release path in the flow's `namespaceFiles.include`, `WORKING_DIR` paths, labels and pinned manifest hash.
4. Run `python tools/build_runtime_bundle.py`. It creates the new bundle and refuses to overwrite an existing version.
5. Run `python tools/build_runtime_bundle.py --check`, tests and lint.
6. Commit source, flow and generated bundle together. Obtain code review and merge.
7. Create a protected tag matching the project version, for example `v1.2.2`.
8. Approve the `uwflow-production` GitHub Environment deployment. CI uploads the immutable Namespace Files release first, validates the flow and then deploys it.

Never overwrite a published runtime release. If an upload reports that the path already exists, compare its manifest and individual checksums; do not use `--override` to force it.

## Local Docker runner

`docker-run.sh` uses Kestra `v2.0.10-slim`, embedded H2 and local storage. It mounts the Docker socket because the flow uses the Docker Task Runner. It does not mount application scripts from the host. The Docker socket can control the host Docker daemon, so this launcher is for local evaluation only.

For real workloads, use the infrastructure, network, storage, secret, access-control and worker-isolation requirements in [Production readiness](PRODUCTION_READINESS.md).
