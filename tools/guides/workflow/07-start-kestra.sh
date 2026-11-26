#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
[[ -r .env ]] || { echo "ERROR: .env is missing; run workflow step 03 first." >&2; exit 1; }
if [[ -e .env.history || -e .env.history.kestra ]]; then
  [[ -r .env.history.kestra ]] || {
    echo "ERROR: .env.history.kestra is missing. Run workflow step 04 to create/reconcile the paired history credential files." >&2
    exit 1
  }
  load_history_credentials
fi

if [[ -f var/operator-state/history-kestra-secrets-reload ]]; then
  restart_local_kestra_for_history_secret_reload
fi

if docker ps --format '{{.Names}}' | grep -qx 'kestra'; then
  echo "Kestra is already running at http://localhost:8080."
  if [[ "${UWFLOW_KESTRA_DETACHED:-false}" == "true" ]]; then
    exit 0
  fi
  echo "Open the existing UI, or stop it before starting a foreground session." >&2
  exit 0
fi

if [[ "${UWFLOW_KESTRA_DETACHED:-false}" == "true" ]]; then
  echo "Starting local Kestra in detached DEV mode. Container logs: docker logs -f kestra"
else
  echo "Starting local Kestra in the foreground. Keep this terminal open."
fi
bash ./docker-run.sh
rm -f var/operator-state/history-kestra-secrets-reload
