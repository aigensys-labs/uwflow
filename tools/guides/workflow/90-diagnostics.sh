#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
source tools/guides/workflow/lib/studio-compose.sh
require_repository_root

printf '\n== Local containers: Kestra ==\n'
docker ps -a --filter name=kestra
printf '\n== Local containers: History PostgreSQL ==\n'
docker ps -a --filter name=uwflow-history-db
printf '\n== Local containers: Policy Studio ==\n'
docker ps -a --filter name=uwflow-studio
printf '\n== Kestra recent logs ==\n'
docker logs --tail 80 kestra 2>&1 || true
printf '\n== History PostgreSQL recent logs ==\n'
docker logs --tail 80 uwflow-history-db 2>&1 || true
printf '\n== Policy Studio container status ==\n'
"${STUDIO_COMPOSE[@]}" ps --all 2>&1 || true
printf '\n== Policy Studio recent logs ==\n'
"${STUDIO_COMPOSE[@]}" logs --no-color --tail 100 studio-api studio-frontend 2>&1 || true
printf '\n== Local environment file names and permissions ==\n'
for file in .env .env.history .env.history.kestra; do [[ -e "$file" ]] && ls -l "$file" || echo "$file: missing"; done
printf '\n== Workflow state ==\n'
if [[ -d var/operator-state ]]; then
  for file in var/operator-state/*; do [[ -f "$file" ]] && printf '%s: %s\n' "${file##*/}" "$(cat "$file")"; done
else
  echo "No workflow state recorded yet."
fi
