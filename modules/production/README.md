# Production

Production manages the governed transition from an evaluated DEV candidate to an immutable deployable release. It verifies candidate artifact/runtime/policy hashes, clean Core provenance, the exact production-flow template, registered evaluation evidence, an explicit approval attestation and a digest-pinned Core task image.

The approved-release assembler writes only to `var/releases/approved/<release-id>/`. It assembles files locally; it does not call Kestra or deploy. Production deployment is manually dispatched from protected `main` with an exact approved release ID. It deploys only that release's Core runtime and production flow. Modules are not deployed into the live underwriting execution path.


For the complete object lifecycle, storage locations, identity model and immutability rules, see the [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md).

## Operate the production lifecycle

| Guide | Use it to… |
|---|---|
| [Governed release boundary](../../docs/production/production-release-workflow.md) | Move from workspace and immutable candidate through replay, evidence registration, explicit approval and approved-release assembly. |
| [GitHub publishing](../../docs/production/github-publishing.md) | Configure the repository, protected `main`, manual deployment workflow, secrets and production environment gate. |
| [Deployment details](../../docs/production/deployment.md) | Understand Core/platform task images, Namespace Files, DEV/PROD separation and deployment verification. |
| [Audit and provenance](../../docs/production/audit-and-provenance.md) | Define the release, runtime, replay, approval and deployment records to retain. |
| [Production readiness](../../docs/production/production-readiness.md) | Plan the operational, security, model-risk and lending controls required before real decisions. |

## Assemble an approved release

The command below is the local package-assembly entry point. Use the exact evaluated candidate ID, an approval attestation that references its evaluation, and the digest of the published Core task image. The example values are placeholders, not a ready-to-deploy release.

```bash
python -m modules.production.tools.release.assemble_approved_release --candidate dev-0123456789abcdef --release-id 2.0.1 --approval approval.json --image-reference ghcr.io/example/uwflow-core-runtime@sha256:REPLACE_WITH_DIGEST
```

The `approved_by` value in the JSON is an attestation string, not an authenticated user identity or RBAC control. Institutional business approval must come from the organisation's authorised process.
