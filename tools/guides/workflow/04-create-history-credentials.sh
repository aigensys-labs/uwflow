#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command docker
docker info >/dev/null
load_python_environment

if [[ -f .env.history && -f .env.history.kestra ]]; then
  echo "Reusing the existing paired history credential files."
elif [[ ! -e .env.history && ! -e .env.history.kestra ]]; then
  if python -m tools.history.database.recover_credentials --root "$PWD"; then
    :
  else
    recovery_status=$?
    if [[ "$recovery_status" -ne 3 ]]; then
      exit "$recovery_status"
    fi
    bash tools/guides/workflow/lib/create-history-env.sh
    mkdir -p var/operator-state
    printf 'required\n' > var/operator-state/history-kestra-secrets-reload
    chmod 600 var/operator-state/history-kestra-secrets-reload
  fi
else
  echo "ERROR: only one history credential file exists." >&2
  echo "Restore the matching file from a protected backup, then rerun this step." >&2
  echo "No password was generated and no database state was changed." >&2
  exit 1
fi
load_history_credentials
chmod 600 .env.history .env.history.kestra
echo "Both history credential files are present and path-validated."
