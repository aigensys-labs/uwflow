# Production readiness — before real underwriting

The quick-start is a local demonstration only. It uses Kestra `server local`, an embedded H2 database, local storage, a Docker socket and synthetic providers. Do not expose it to a network or use its decisions for real lending.

Before a real deployment, the platform owner should approve and implement the following:

| Area | Required before live applications | Why it matters |
|---|---|---|
| Kestra infrastructure | Supported deployment topology, external PostgreSQL, durable object storage, backups and recovery tests | A local single-container database is not an operational production store. |
| Network and access | HTTPS, managed identity, least-privilege roles, private network access and restricted API endpoints | Prevents unauthorized users from changing flows or accessing applicant information. |
| Task isolation | Dedicated workers or an approved remote/Kubernetes task runner; do not expose a general-purpose host Docker socket to an untrusted authoring environment | Python tasks execute code. The execution boundary must be controlled. |
| Secrets | Managed secret backend or institution-approved secret manager; rotate and audit credentials | Base64 environment secrets in Kestra OSS are not encryption or a full secrets-management solution. |
| Runtime images | Approved images pinned by verified digest, vulnerability scanning, SBOM and controlled patch process | Makes the task runtime repeatable and reviewable. |
| Source deployment | Protected Git branches and tags, mandatory review, CI checks, a restricted deployment service account and immutable release directories | Prevents unreviewed code from reaching production. |
| Data sources | Contracted bureau/open-banking/alternative-data providers, data minimization, lawful basis, consent where required, retention and outage handling | Synthetic adapters are not real integrations or evidence of data rights. |
| AIDflow model | Validated model artefact, documented training data, independent validation, monitoring, drift controls, explainability and version approval | The demonstration scorer is synthetic and is not a credit-risk model. |
| UWflow policy | Approved eligibility, affordability, pricing, referral and decline rules, with effective dates and policy owners | The included thresholds and pricing are illustrative. |
| Audit evidence | Independently retained execution ID, exact source commit, manifest hash, model artifact hash, policy version, input lineage, decision outputs and actor/deployment evidence | Enables reconstruction and review of each historical decision. |
| Resilience | Timeouts, retries, idempotency, provider fallback rules, manual-review queues and operational alerting | Underwriting cannot assume every external service is always available. |
| Legal and compliance | Legal/compliance approval for jurisdiction, consumer disclosures, adverse-action reasons, privacy, records retention and applicable AI/credit rules | Technical success does not establish legal permission to make credit decisions. |

## Release rule

A production runtime release is immutable. Change the source in Git, test it, create a new version, build a new `runtime/releases/<version>` bundle and deploy it through the approved pipeline. Never replace a historical release directory.

The repository's SHA-256 manifest detects accidental or unauthorized changes to the runtime files. It does not by itself prove who approved a release, that the model is valid, or that the input data was correct. Keep approval records and execution evidence in independently controlled systems.
