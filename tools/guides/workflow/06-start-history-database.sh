#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command docker
load_python_environment
load_history_credentials

if ! docker network inspect uwflow-local >/dev/null 2>&1; then
  docker network create uwflow-local >/dev/null
fi

# Reuse an existing named container first. This is important when the source
# package was replaced/extracted to a new directory: the database container and
# named volume are independent of the source checkout location.
if docker inspect uwflow-history-db >/dev/null 2>&1; then
  container_state="$(docker inspect --format '{{.State.Status}}' uwflow-history-db)"
  if [[ "$container_state" != "running" ]]; then
    echo "Starting existing PostgreSQL container (state: $container_state)."
    docker start uwflow-history-db >/dev/null
  else
    echo "Reusing the existing PostgreSQL container."
  fi
else
  docker compose --env-file .env.history -f modules/history/compose.yml up -d
fi

attached_volume="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' uwflow-history-db)"
if [[ "$attached_volume" != "uwflow_history_pgdata" ]]; then
  echo "ERROR: uwflow-history-db is not using the expected persistent volume." >&2
  echo "Expected: uwflow_history_pgdata" >&2
  echo "Attached: ${attached_volume:-<none>}" >&2
  echo "Stop here; do not recreate or delete any volume." >&2
  exit 1
fi

status=""
for attempt in $(seq 1 60); do
  status="$(docker inspect --format '{{.State.Health.Status}}' uwflow-history-db 2>/dev/null || true)"
  [[ "$status" == "healthy" ]] && break
  sleep 2
done
if [[ "$status" != "healthy" ]]; then
  echo "ERROR: PostgreSQL did not become healthy (status: ${status:-not found}). Recent logs:" >&2
  docker logs --tail 100 uwflow-history-db >&2 || true
  exit 1
fi

docker ps --filter name='^/uwflow-history-db$' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
ensure_history_admin_connection
echo "Historical PostgreSQL is healthy and the configured admin credentials authenticate. Persistent volume: uwflow_history_pgdata."
