# UWflow DEV Fast Route

The DEV Fast Route prepares a complete local UWflow development environment with one command. It builds the Python task image and both Policy Studio images, starts the history database and Kestra, verifies the ordinary underwriting flow, creates or reuses the synthetic FSTPD30 dataset, runs a paired champion/challenger replay and starts the Policy Studio.

## Run the route

Use a native Linux host with Bash, Python 3.11 or newer with the `venv` module, Docker Engine and Docker Compose V2. Docker must be running and accessible to your user.

Extract the repository and open a terminal in the `uwflow` project root—the directory containing `pyproject.toml`, `docker-run.sh` and `tools/`. Run:

```bash
bash tools/guides/workflow/dev-fast-route.sh
```

The route installs Python project dependencies and runs repository checks before starting services. Because the History tooling bundle is a derived immutable artifact and is not pre-populated in a clean ZIP, this step builds or reuses it from the tracked History/Reporting sources and then verifies its manifest and payload. Docker image builds and package installation complete before dependent services are started. PostgreSQL health and authentication, Kestra authenticated flow-search API readiness, and Policy Studio service readiness are checked before the route continues.

When `kestractl` is not installed, the route asks for confirmation before running the official installer. It asks before reconciling an existing PostgreSQL owner-password mismatch, recovering missing history credentials for an existing database, or reusing an existing immutable Kestra Namespace Files path. Credential recovery rotates database login passwords only after approval and preserves the existing database volume and records.

## Execution sequence

| Sequence | Operation | Verification |
|---|---|---|
| 1 | Check Linux, Python, Bash, Docker and Compose | Docker daemon is reachable |
| 2 | Create or repair `var/venv`, install project extras, run repository checks and build/reuse the History tooling bundle from Module source | Tests, policy compiler, Core runtime and generated History bundle checks pass |
| 3 | Build the Policy Studio API and frontend images | Both Docker builds complete |
| 4 | Check for `kestractl` | Missing CLI is installed only after confirmation |
| 5 | Create/reuse or reconcile local Kestra and paired history credentials | Credential files and history paths validate; approved recovery is recorded for the database and Kestra reload steps |
| 6 | Build/reuse the underwriting task image | Versioned task image is available locally |
| 7 | Start/reuse PostgreSQL history storage | Container is healthy and the configured owner DSN authenticates |
| 8 | Start/reuse Kestra in detached mode | Current read-only history secrets match the container environment; authenticated API is ready |
| 9 | Publish/reuse and deploy the DEV baseline | Live Kestra validates the flow; immutable files are verified |
| 10 | Execute the ordinary seven-stage underwriting flow | Kestra execution completes with `SUCCESS` |
| 11 | Initialize history schemas and roles; create/reuse the FSTPD30 dataset | Independent read-back checksum and point-in-time checks pass |
| 12 | Run the local 100-case baseline/no-op comparison | Decisions, scores, hard-gate outcomes, source plans and approved amounts match |
| 13 | Build, validate, publish/reuse and deploy the paired replay flow | Kestra accepts the flow before bundle publication; published paths remain immutable |
| 14 | Execute the 100-case paired replay | Kestra execution and comparison tasks complete with `SUCCESS` |
| 15 | Start the Policy Studio | API and frontend health checks pass; React entry modules load; API catalogue and frontend API proxy return the expected seven-stage contract |

The route records execution IDs, candidate and dataset identities, bundle IDs and the selected baseline under `var/operator-state/`.

### Kestra trigger timeouts

The Fast Route assigns each requested execution a unique `uwflow.fastRouteRequestId` label and writes a mode-`0600` request marker under `var/operator-state/` before sending the API request. A timeout or connection interruption makes the POST outcome ambiguous: Kestra may have accepted the execution even though the client did not receive its ID. The route therefore searches the execution API for the exact label, namespace, flow and main execution. When it finds one match, it recovers that execution ID and continues monitoring its real state. It never sends a second POST for an unresolved request. This is client-side request reconciliation; it does not claim that Kestra itself deduplicates arbitrary concurrent executions. The implementation follows Kestra's [execution-label](https://kestra.io/docs/workflow-components/labels), [execution-trigger API](https://kestra.io/docs/how-to-guides/api) and [query-filter](https://kestra.io/docs/api-reference/query-filters) contracts.

If no matching execution appears within the reconciliation window, the route stops and retains the request marker. Inspect Kestra Executions using the printed label. Rerunning the Fast Route resumes the search without submitting another execution. Remove the matching `.request.json` marker only after confirming in Kestra that no execution was created. This prevents an ambiguous HTTP response from creating duplicate underwriting runs.

## When it completes

The following local services remain running:

| Service | Default address |
|---|---|
| Kestra | [http://localhost:8080](http://localhost:8080) |
| Policy Studio | [http://127.0.0.1:5173](http://127.0.0.1:5173) |
| Studio API | [http://127.0.0.1:9000/docs](http://127.0.0.1:9000/docs) |
| History PostgreSQL | `127.0.0.1:55432`, database `uwflow_history` |

Custom Studio and PostgreSQL ports can be set in the corresponding local environment files. The history database persists in the Docker volume `uwflow_history_pgdata`.

The terminal summary includes the selected dataset, baseline, candidate, history-tools bundle, flow ID, execution IDs, report location and local development credentials. Credentials are read from `.env`, `.env.history` and `.env.history.kestra`; they are not copied into another file. Keep the terminal output private.

Download the comparison report and CSV/JSON evidence from the successful `compare_replays` task in Kestra.

## Scope of the first replay

When `UWFLOW_FAST_ROUTE=true`, Step 11 creates a fresh isolated workspace from the Core default policy and builds a new immutable no-op candidate against the selected baseline. It does not depend on a hardcoded candidate ID or on an analyst workspace. The 100-case replay verifies the infrastructure and report path; it is expected to show no strategy-driven decision movement. The generated candidate ID is saved in `var/operator-state` and is valid only for that package's current artifact contract.

The default dataset contains 5,000 synthetic applicants, but the Fast Route replays 100 cases for the first execution. The detailed [End-to-end DEV workflow](end-to-end-dev-workflow.md) explains the full 5,000-case replay and the process for editing a policy, building a distinct candidate and comparing it on the same dataset.

FSTPD30 labels are generated synthetic counterfactuals. They support deterministic software and policy-sensitivity tests; they are not observed repayment outcomes or validated credit-risk estimates.

## If the route stops

The route stops at the first failed command or verification. It does not start dependent stages after a failed check, delete persistent Docker volumes, rotate credentials without approval, overwrite immutable Namespace Files or deploy to PROD. When an approved credential recovery is in progress, the existing database volume is retained and Kestra is restarted with the regenerated read-only secret file. The reload checks whether a Kestra container exists, verifies its two named data-volume mounts before stopping it, waits for Docker automatic container removal, and safely handles a container that disappears during shutdown. The next container starts with the updated secret file; `kestra_data` and `kestra_db` are not removed.

Run the diagnostics command from the repository root:

```bash
bash tools/guides/workflow/90-diagnostics.sh
```

Inspect service logs with:

```bash
docker logs --tail 100 kestra
```

```bash
docker logs --tail 100 uwflow-history-db
```

```bash
docker compose --project-name uwflow-studio -f docker-compose.studio.yml logs --tail 100
```

To stop only the Policy Studio containers:

```bash
bash tools/guides/workflow/16-stop-studio.sh
```

Kestra and PostgreSQL remain running after the Fast Route completes. Use the documented operator procedures to stop them while preserving their named volumes.
