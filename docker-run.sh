#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "Missing .env. Run ./tools/create-local-env.sh first." >&2
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

# LOCAL DEMO ONLY:
# - server local uses embedded H2 and local storage;
# - the Docker socket lets Kestra launch isolated Python task containers;
# - mounting the Docker socket grants powerful control over the host Docker daemon.
# Application Python files are NOT mounted from this machine. They are uploaded to
# Kestra Namespace Files separately by the first-run guide.

docker run --pull=always --rm -it -p 8080:8080 --user=root \
  --name kestra \
  -v kestra_data:/app/storage \
  -v kestra_db:/app/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp:/tmp \
  --env-file "${PROJECT_DIR}/.env" \
  kestra/kestra:v2.0.10-slim server local
