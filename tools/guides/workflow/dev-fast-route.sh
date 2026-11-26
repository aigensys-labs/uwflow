#!/usr/bin/env bash
# One-command Linux DEV setup through the 100-case Kestra replay and Policy Studio.
set -Eeuo pipefail

source tools/guides/workflow/lib/common.sh
require_repository_root

CURRENT_STEP="Linux host preflight"

on_error() {
  local exit_code=$?
  trap - ERR
  printf '\n\033[31mUWflow DEV FAST ROUTE STOPPED\033[0m\n' >&2
  printf 'Failed during: %s\n' "$CURRENT_STEP" >&2
  printf 'Exit code: %s\n' "$exit_code" >&2
  printf 'No dependent step was started after the failure. Existing credentials, database volumes and immutable artifacts were preserved.\n' >&2
  printf 'For diagnostics run: bash tools/guides/workflow/90-diagnostics.sh\n' >&2
  printf 'Kestra logs: docker logs --tail 100 kestra\n' >&2
  printf 'History PostgreSQL logs: docker logs --tail 100 uwflow-history-db\n' >&2
  printf 'Studio logs: docker compose --project-name uwflow-studio -f modules/policy-studio/compose.yml logs --tail 100\n' >&2
  exit "$exit_code"
}
trap on_error ERR

run_step() {
  CURRENT_STEP="$1"
  shift
  printf '\n\033[36m== %s ==\033[0m\n' "$CURRENT_STEP"
  "$@"
  printf '\033[32mPASS\033[0m  %s\n' "$CURRENT_STEP"
}

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ERROR: UWflow DEV Fast Route supports Linux hosts only (native Linux + Docker Engine/Compose V2)." >&2
  exit 2
fi

printf '\nUWflow DEV FAST ROUTE — LINUX\n'
printf 'This route prepares the full local DEV stack, verifies a 100-case paired replay, and starts Policy Studio.\n'
printf 'It reuses the numbered operator scripts and stops at the first failed check.\n'
printf 'The production champion is never modified or deployed. Synthetic FSTPD30 labels are test fixtures only.\n'
printf 'Missing kestractl is never installed without your explicit approval.\n'

# Clear inherited route flags so the baseline tests always exercise the normal
# interactive operator behavior, even if a parent shell exported old settings.
unset UWFLOW_FAST_ROUTE UWFLOW_SUPPRESS_CREDENTIAL_OUTPUT \
  UWFLOW_FAST_ROUTE_AUTO_UPLOAD UWFLOW_FAST_ROUTE_AUTO_DEPLOY \
  UWFLOW_FAST_ROUTE_DEFAULT_DATASET

run_step "00 — Linux/Docker/Python preflight" bash tools/guides/workflow/00-preflight.sh
run_step "01 — Python environment, dependencies, tests and bundle checks" bash tools/guides/workflow/01-python-environment.sh

# Studio images are a required part of the end-to-end developer environment.
# docker compose build is synchronous: no dependent step starts before both images finish.
run_step "02 — Build Policy Studio Docker images" bash tools/guides/workflow/02-build-studio-images.sh

# Install the Kestra CLI before starting services so the user can approve or
# decline the only additional host dependency without leaving containers behind.
run_step "08 — Check/install Kestra CLI" bash tools/guides/workflow/08-install-kestra-cli.sh

# Fast Route defaults are deliberately scoped after pytest. Exporting these
# before Step 01 would leak operator behavior into child test processes.
export UWFLOW_FAST_ROUTE=true
export UWFLOW_SUPPRESS_CREDENTIAL_OUTPUT=true
export UWFLOW_FAST_ROUTE_AUTO_UPLOAD=true
export UWFLOW_FAST_ROUTE_AUTO_DEPLOY=true
export UWFLOW_FAST_ROUTE_DEFAULT_DATASET=true

# Activate this shell for the API helper; the shared loader verifies the
# environment created/repaired by Step 01, just like every numbered script.
load_python_environment
export PYTHONUNBUFFERED=1

run_step "03 — Create/reuse local Kestra credentials" bash tools/guides/workflow/03-create-local-credentials.sh
run_step "04 — Create/reuse paired historical PostgreSQL credentials" bash tools/guides/workflow/04-create-history-credentials.sh
run_step "05 — Build/reuse the Python underwriting task image" bash tools/guides/workflow/05-build-task-image.sh
run_step "06 — Start and authenticate the PostgreSQL history database" bash tools/guides/workflow/06-start-history-database.sh

CURRENT_STEP="07 — Start/reload Kestra and verify its environment"
if [[ -f var/operator-state/history-kestra-secrets-reload ]] || \
   ! docker ps --format '{{.Names}}' | grep -qx 'kestra'; then
  export UWFLOW_KESTRA_DETACHED=true
  run_step "07 — Start/reload Kestra in detached DEV mode" bash tools/guides/workflow/07-start-kestra.sh
  unset UWFLOW_KESTRA_DETACHED
else
  printf '\nKestra is already running; checking that it has the current history secrets.\n'
fi

# A running container with stale history secrets is not a valid dependency.
load_history_credentials
if [[ ! -r .env.history.kestra ]]; then
  echo "ERROR: .env.history.kestra is missing." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env.history.kestra
set +a
run_step "Kestra — Verify current read-only history secrets" \
  python tools/kestra/fast_route_api.py verify-container-secrets --container kestra

load_local_kestra_credentials
run_step "Kestra — Wait for authenticated API readiness" \
  python tools/kestra/fast_route_api.py wait-ready --base-url "$KESTRACTL_HOST"

run_step "09 — Validate, publish/reuse and deploy the DEV baseline" bash tools/guides/workflow/09-deploy-dev-baseline.sh

PROJECT_VERSION="$(python -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
BASELINE_FLOW="uwflow_dev_baseline_v${PROJECT_VERSION//./_}"
run_step "Kestra — Execute and verify the ordinary seven-stage underwriting smoke test" \
  python tools/kestra/fast_route_api.py execute \
    --flow-id "$BASELINE_FLOW" \
    --label "single-application underwriting smoke test" \
    --state-file var/operator-state/baseline-smoke-execution-id

run_step "10 — Initialize/upgrade history schemas and least-privilege roles" bash tools/guides/workflow/10-initialize-history-database.sh
rm -f var/operator-state/history-owner-password-reconcile-approved
run_step "11 — Select/create and checksum-validate the canonical FSTPD30 dataset" bash tools/guides/workflow/11-select-or-create-dataset.sh
run_step "12 — Run the local 100-case no-op replay" bash tools/guides/workflow/12-run-local-noop-replay.sh

CANDIDATE_ID="$(require_candidate_id)"
LOCAL_COMPARISON="var/reports/history/local-${CANDIDATE_ID}/comparison/comparison.json"
CURRENT_STEP="Verify the local no-op replay comparison"
python - "$LOCAL_COMPARISON" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"Missing local comparison report: {path}")
report = json.loads(path.read_text(encoding="utf-8"))
checks = {
    "case_count": report.get("case_count") == 100,
    "decision_changes": report.get("decision_changes") == 0,
    "source_plan_changes": report.get("source_plan_changes") == 0,
    "hard_gate_result_changes": report.get("hard_gate_result_changes") == 0,
    "score_delta": (report.get("profile_score_delta") or {}).get("mean_candidate_minus_baseline") == 0.0,
    "approved_amount_delta": (report.get("approved_amount_delta_eur") or {}).get("total_candidate_minus_baseline") == 0.0,
    "approved_amount_cases": (report.get("approved_amount_delta_eur") or {}).get("changed_case_count") == 0,
}
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}  no-op {name}")
if not all(checks.values()):
    raise SystemExit("The local baseline/candidate control was not a true no-op. Stop before publishing the replay flow.")
print("Local comparison confirms identical decisions, scores, source plans, hard gates and approved amounts.")
PY
printf '\033[32mPASS\033[0m  %s\n' "$CURRENT_STEP"

run_step "13 — Build/pin the immutable history-tools bundle and paired replay flow" bash tools/guides/workflow/13-build-history-replay-flow.sh
run_step "14 — Server-validate, publish/reuse immutable bundles and deploy the DEV replay flow" bash tools/guides/workflow/14-publish-history-replay-flow.sh

DATASET_ID="$(read_state dataset-id)"
REPLAY_FLOW="$(read_state replay-flow-id)"
run_step "Kestra — Execute and verify the 100-case champion/challenger replay" \
  python tools/kestra/fast_route_api.py execute \
    --flow-id "$REPLAY_FLOW" \
    --label "100-case paired champion/challenger replay" \
    --state-file var/operator-state/history-replay-execution-id \
    --input "dataset_id=${DATASET_ID}" \
    --input "batch_size=2000" \
    --input "offset=0" \
    --input "max_cases=100"

# Step 02 built both images. Step 15 now starts the complete API + frontend
# stack detached, then waits for API health and a successful frontend HTTP check.
export UWFLOW_STUDIO_DETACHED=true
run_step "15 — Start and verify the complete Dockerized Policy Studio" bash tools/guides/workflow/15-start-studio.sh
unset UWFLOW_STUDIO_DETACHED

CURRENT_STEP="Display connection details and local credentials"
load_local_kestra_credentials
load_history_credentials
set -a
# shellcheck disable=SC1091
. ./.env.history.kestra
set +a

printf '\n\033[32m==================================================\033[0m\n'
printf '\033[32mUWflow DEV FAST ROUTE — COMPLETED\033[0m\n'
printf '\033[32m==================================================\033[0m\n'
printf '\nKestra UI:       http://localhost:8080\n'
printf 'Policy Studio:  http://127.0.0.1:%s\n' "${UWFLOW_STUDIO_WEB_PORT:-5173}"
printf 'Studio API:     http://127.0.0.1:%s/docs\n' "${UWFLOW_STUDIO_API_PORT:-9000}"
printf 'History DB:     127.0.0.1:%s / %s\n' "$UWFLOW_HISTORY_PORT" "$UWFLOW_HISTORY_DB"
printf 'Replay flow:    com.ai.credit.dev / %s\n' "$REPLAY_FLOW"
printf 'Dataset:        %s\n' "$DATASET_ID"
printf 'Candidate:      %s\n' "$CANDIDATE_ID"
printf 'Baseline:       %s\n' "$(read_state baseline-release 2.0.0)"
printf 'History tools:  %s\n' "$(read_state history-tools-bundle-id)"
printf 'Local no-op:    %s\n' "$LOCAL_COMPARISON"
printf 'Kestra run IDs: %s / %s\n' \
  "$(read_state baseline-smoke-execution-id 'not recorded')" \
  "$(read_state history-replay-execution-id 'not recorded')"
printf 'Reports:        Download from the successful compare_replays task in Kestra.\n'
printf '\n\033[33mSENSITIVE — LOCAL DEVELOPMENT CREDENTIALS\033[0m\n'
printf 'Displayed only in this terminal; never paste this section into GitHub or shared chat.\n\n'
printf '[Kestra local UI — HTTP Basic Auth]\n'
printf 'Username:                 %s\n' "$KESTRA_SERVER_BASIC_AUTH_USERNAME"
printf 'Password:                 %s\n' "$KESTRA_SERVER_BASIC_AUTH_PASSWORD"
printf 'Underwriting webhook key: %s\n' "$SECRET_UNDERWRITING_WEBHOOK_KEY"
printf '\n[History PostgreSQL — host access]\n'
printf 'Host / port / database:   127.0.0.1:%s / %s\n' "$UWFLOW_HISTORY_PORT" "$UWFLOW_HISTORY_DB"
printf 'Owner user:               %s\n' "$UWFLOW_HISTORY_OWNER_USER"
printf 'Owner password:           %s\n' "$UWFLOW_HISTORY_OWNER_PASSWORD"
printf 'Admin DSN:                %s\n' "$UWFLOW_HISTORY_ADMIN_DSN"
printf '\nReader user:              %s\n' "$UWFLOW_HISTORY_READ_USER"
printf 'Reader password:          %s\n' "$UWFLOW_HISTORY_READ_PASSWORD"
printf 'Read-only DSN:            %s\n' "$UWFLOW_HISTORY_DSN"
printf '\nWriter user:              %s\n' "$UWFLOW_HISTORY_WRITE_USER"
printf 'Writer password:          %s\n' "$UWFLOW_HISTORY_WRITE_PASSWORD"
printf 'Writer DSN:               %s\n' "$UWFLOW_HISTORY_WRITE_DSN"
printf '\n[Kestra OSS Base64 secrets — .env.history.kestra]\n'
printf 'SECRET_UWFLOW_HISTORY_CONNECTOR: %s\n' "$SECRET_UWFLOW_HISTORY_CONNECTOR"
printf 'SECRET_UWFLOW_HISTORY_DSN:       %s\n' "$SECRET_UWFLOW_HISTORY_DSN"
printf 'SECRET_UWFLOW_HISTORY_ROOT:      %s\n' "$SECRET_UWFLOW_HISTORY_ROOT"
printf '\nPersistent PostgreSQL volume: uwflow_history_pgdata (preserved)\n'
printf 'Kestra:                        running detached; logs: docker logs -f kestra\n'
printf 'Policy Studio:                 API + frontend running; stop with Step 16 only when finished\n'
printf '\nSynthetic FSTPD30 outcomes are software-test fixtures, not observed lending performance.\n'
