# Audit, traceability and runtime provenance

## Evidence to retain per underwriting execution

Persist the following evidence as one linked decision record, keyed by Kestra execution ID and UWflow decision reference:

- application payload snapshot (with appropriate personal-data minimization and retention);
- hard-gate outcomes and reason codes;
- bureau provider reference, received timestamp, normalized result and policy outcome;
- all ten source adapter results, status, provider reference, data timestamps and normalized scores;
- AIDflow model version, model-artifact identifier/hash, score, input lineage, coverage and scoring diagnostics;
- UWflow engine version, policy version, policy check results, affordability calculation, pricing configuration and final decision;
- runtime release version, source Git ref, release-manifest SHA-256 and each runtime module SHA-256;
- task runner type, configured Python container image reference and actual Python interpreter version;
- Kestra namespace, flow ID, flow revision, execution ID, start/end timestamps, task attempts and relevant execution outputs;
- final JSON snapshot, HTML decision card and PDF report;
- deployment provenance showing the Git commit, tag, approver/environment and deployment result.

## Runtime integrity model

`release-manifest.json` lists a SHA-256 digest for each Python module in the release. Stage 1 validates the file set and every digest before hard-gate logic executes. The verified manifest digest and release metadata are copied into the UWflow decision and rendered report. A missing, extra or modified Python source file causes the stage to fail rather than silently continuing.

A manifest hash proves byte identity against the manifest; it does not prove that the manifest itself was approved. Approval is provided by GitHub governance: protected branches, required reviewers, release tags restricted to maintainers, signed tags where available, protected deployment environments and restricted service-account permissions.

## Kestra controls

- Use Namespace Files rather than host-mounted source directories.
- Run application Python in an isolated Docker task image; record the configured image reference and interpreter version for every decision. For production, pin and record the verified OCI digest as well.
- Deploy each release under a new versioned path, e.g. `runtime/releases/1.2.2/`.
- Restrict production Namespace File write permissions to the deployment identity. Developers should not have direct write access in production.
- Mark CI-managed production flows with `system.readOnly: "true"`.
- Retain Kestra execution metadata and namespace file revision history according to the institution's records schedule.
- Export final decision evidence to a separate, retention-controlled store; do not rely on Kestra operational storage as the sole long-term regulatory archive.

## AIDflow model provenance

The Python inference wrapper and the trained model artifact are separate versioned objects. The deployed AIDflow implementation must return the model version and artifact digest it actually loaded. Record feature/preprocessing version, model artifact hash, inference code release and source input lineage. A code checksum alone is not enough to identify the model weights or preprocessing state.

## Important limitation

This repository demonstrates runtime code verification and metadata propagation. It does not implement a WORM archive, digital signature verification, enterprise audit-log export, legal hold, retention schedule, or independent source-provider evidence vault. Those require institution-specific infrastructure and governance.
