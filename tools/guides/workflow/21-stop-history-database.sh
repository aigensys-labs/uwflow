#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command docker

if docker inspect uwflow-history-db >/dev/null 2>&1; then
  status="$(docker inspect --format '{{.State.Status}}' uwflow-history-db)"
  if [[ "$status" == "running" ]]; then
    docker stop uwflow-history-db >/dev/null
    echo "Historical PostgreSQL container stopped."
  else
    echo "Historical PostgreSQL container is already stopped (state: $status)."
  fi
else
  echo "Historical PostgreSQL container does not exist."
fi

echo "Persistent volume uwflow_history_pgdata was not removed."
