# Audit, traceability and runtime provenance


For the complete workspace-to-deployment lifecycle and canonical storage model, see [UWflow lifecycle and storage model](../architecture/lifecycle-and-storage.md).

## Evidence to retain per underwriting execution

Persist the following evidence as one linked decision record, keyed by Kestra execution ID and UWflow decision reference:

- application payload snapshot, with personal-data minimization and retention;
- hard-gate outcomes, reason codes and matched Stage 1 policy rule IDs;
- Stage 3 source-plan result and traversed routing node IDs;
- canonical policy identifiers and source-spec SHA-256 values from `policy_generated.POLICY_METADATA`;
- bureau provider reference, received timestamp, normalized result and policy outcome;
- source-adapter results, status, provider references, timestamps and normalized values;
- AIDflow model version, model-artifact identifier/hash, score, input lineage, coverage and diagnostics;
- UWflow engine version, policy version, affordability calculation, pricing configuration and final decision;
- runtime release version, source Git ref, release-manifest SHA-256 and each runtime module SHA-256;
- configured task-image reference, task-runner type, Python interpreter version and verified runtime path;
- Kestra namespace, flow ID/revision, execution ID, start/end timestamps, task attempts and outputs;
- final JSON snapshot, HTML decision card and PDF report;
- deployment provenance: approved release ID, release-manifest hash, Git commit, GitHub Actions run ID, protected environment and deployment result.

For historical simulations, additionally retain:

- dataset ID, snapshot manifest and dataset content checksum;
- generator name/version/seed for synthetic data, or source-system snapshot reference for real data;
- point-in-time cutoff and case selection parameters;
- baseline runtime release and manifest digest;
- candidate ID and manifest digest;
- history tooling bundle ID and digest;
- replay parameters, batch offsets/counts and execution IDs;
- per-case output artifact hashes and aggregate comparison artifact hashes.

## Runtime integrity model

The immutable runtime `release-manifest.json` lists a SHA-256 digest for each Python module. `core/docker/bootstrap.py`, baked into the task image, verifies the flow-pinned manifest digest, selected release directory, artifact type and every module/policy-spec checksum before adding the runtime to `sys.path`. A missing, extra or modified runtime file causes the task to fail rather than continue silently.

The manifest hash proves byte identity against the manifest; it does not prove that the manifest itself was approved. Approval is represented by an explicit attestation linked to the exact candidate manifest and evaluation ID. The `approved_by` field is a supplied attestation string, not an authenticated user identity, cryptographic signature or RBAC control. The institution's authoritative approval record must be retained separately. GitHub governance adds protected-branch review and a protected deployment Environment; the deploy workflow additionally requires manual dispatch from protected `main` with the exact approved release ID. Release tags do not trigger production deployment.

## Kestra and image controls

- Use versioned Namespace Files rather than host-mounted application source.
- Use the prebuilt `ai/uwflow-core-runtime` image for Core underwriting tasks; pin the immutable OCI digest in the approved release. `ai/uwflow-runtime` is for optional DEV History/Evaluation tasks, not the live PROD Core path. No task-level `pip install` or `dependencies` block should remain.
- The current Docker Task Runner still starts one isolated container per Python task. The prebuilt image avoids package installation on every task; it does not remove container startup. Process Runner is a separate lower-isolation operating model.
- Record the configured task image reference. For remote production, record and pin the OCI digest, not only a mutable tag.
- Deploy each approved Core runtime under its explicitly selected approved release ID, for example `runtime/releases/2.0.1/`. The platform version, Core runtime version, DEV candidate ID and approved release ID are separate identities.
- Restrict production Namespace Files write permission to the deployment identity.
- Mark CI-managed production flows with `system.readOnly: "true"`.
- Retain Kestra execution metadata and namespace-file revision history according to the institution's records schedule.
- Export decision and replay evidence to a separate, retention-controlled store; Kestra operational storage is not the sole long-term regulatory archive.

## AIDflow model provenance

The Python inference wrapper and trained model artifact are separate versioned objects. The deployed AIDflow implementation must return the model version and artifact digest it actually loaded. Record preprocessing version, model-artifact hash, inference code release and source-input lineage. A code checksum alone does not identify model weights or preprocessing state.

## Limitations

This repository demonstrates code verification and provenance propagation. It does not implement WORM storage, digital signature verification, enterprise audit-log export, legal hold, a complete retention schedule or an independent provider-evidence vault. Those require institution-specific infrastructure and governance.
