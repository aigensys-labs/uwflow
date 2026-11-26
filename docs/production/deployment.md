# Deploying UWflow to Kestra


For the complete workspace-to-deployment lifecycle and canonical storage model, see [UWflow lifecycle and storage model](../architecture/lifecycle-and-storage.md).

## Current v2 execution model

- Platform version: `2.0.0` (`pyproject.toml`).
- Core underwriting engine: independently runnable from `core/`.
- Production namespace: `com.ai.credit.production`.
- DEV namespace: `com.ai.credit.dev`.
- Approved production source: `var/releases/approved/<release-id>/`.

The checked-in `core/kestra/flows/` and `core/kestra/namespace-files/runtime/releases/` paths contain the Core development flow and immutable Core runtime snapshots used as explicit bootstrap/reference baselines. They are not the source of production deployment. Production deployment accepts only a verified immutable package under `var/releases/approved/`. That package contains the Core runtime and approved production flow only; Policy Studio, Lifecycle, History, Evaluation, Reporting and other platform Modules are not deployed into the live underwriting execution path.

## Images

The Core task image contains the Kestra Python bootstrap and execution dependencies. Business runtime modules are supplied separately as immutable Namespace Files. Optional History/Evaluation tasks use the platform runtime image. Production Core tasks must use a digest-pinned Core image reference recorded in the approved release manifest.

## Local development

For a Core-only local run, follow [Run the seven-stage Core demo through Kestra](../../core/kestra/README.md). The local launcher starts a development Kestra instance and publishes development flows to the DEV namespace. It does not deploy or modify PROD.

Start Policy Studio with:

```bash
bash tools/guides/workflow/15-start-studio.sh
```

Studio stores mutable analyst work under `var/workspaces/strategies/`. It can fork immutable DEV candidates and approved releases. It never writes Core source. Candidate artifacts are stored under `var/artifacts/candidates/` and published only to `com.ai.credit.dev` by explicit operator action.

## Production release

Follow [Governed release boundary](production-release-workflow.md). The process is:

1. Fork or create a strategy workspace.
2. Build an immutable candidate from an explicitly selected Core runtime and baseline.
3. Publish and evaluate it in Kestra DEV against frozen historical evidence.
4. Register the evaluation under `var/artifacts/evaluations/`.
5. Obtain explicit underwriting/risk approval referencing the exact candidate manifest and evaluation ID.
6. Assemble `var/releases/approved/<release-id>/` with the Production module.
7. Manually dispatch `.github/workflows/deploy-kestra.yml` with that exact release ID and approve the protected GitHub environment.

The workflow verifies approval, candidate and runtime hashes, evaluation reference, production-flow hash and digest-pinned image. It must be manually dispatched from protected `main` with the exact approved release ID, and the `uwflow-production` GitHub Environment applies its reviewer gate. It uploads only the approved Core runtime and deploys only that package's production flow. No platform `v*` tag can deploy underwriting production.

## Deployment verification

A successful local test or GitHub workflow does not prove the live Kestra state. Verify the actual production flow's runtime-release label, runtime manifest hash, image digest and Namespace Files contents in the target Kestra instance. Keep secrets, worker credentials, network policy, backups and operational readiness separately managed. See [Production readiness](production-readiness.md).
