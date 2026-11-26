#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "Missing .env. Run bash core/scripts/create-local-credentials.sh first." >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx 'kestra'; then
  if docker ps --format '{{.Names}}' | grep -qx 'kestra'; then
    echo "A container named 'kestra' is already running. Reuse it at http://localhost:8080." >&2
  else
    echo "A stopped container named 'kestra' already exists. Remove that container with 'docker rm kestra' and retry. Docker volumes are preserved." >&2
  fi
  exit 1
fi

# Kestra and its isolated replay task containers share this local-only network.
# The history database remains a separate service and separate persistence volume.
if ! docker network inspect uwflow-local >/dev/null 2>&1; then
  docker network create uwflow-local >/dev/null
fi

# LOCAL DEMO ONLY:
# - server local uses embedded H2 and local storage;
# - the Docker socket lets Kestra launch isolated Python task containers;
# - mounting the Docker socket grants powerful control over the host Docker daemon;
# - the optional Kestra env file contains only Base64-encoded read-only history DSN secret.
# Application Python files are NOT mounted from this machine. They are uploaded to
# Kestra Namespace Files separately by the first-run guide.

if [[ "${UWFLOW_KESTRA_DETACHED:-false}" == "true" ]]; then
  RUN_MODE=(-d)
else
  RUN_MODE=(-it)
fi

DOCKER_ARGS=(
  --pull=always "${RUN_MODE[@]}" -p 8080:8080 --user=root
  --name kestra
  --network uwflow-local
  -v kestra_data:/app/storage
  -v kestra_db:/app/data
  -v /var/run/docker.sock:/var/run/docker.sock
  -v /tmp:/tmp
  --env-file "${PROJECT_DIR}/.env"
)
if [[ -f "${PROJECT_DIR}/.env.history.kestra" ]]; then
  DOCKER_ARGS+=(--env-file "${PROJECT_DIR}/.env.history.kestra")
fi

docker run --rm "${DOCKER_ARGS[@]}" kestra/kestra:v2.0.10-slim server local
