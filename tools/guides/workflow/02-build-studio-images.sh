#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
source tools/guides/workflow/lib/studio-compose.sh
require_repository_root
require_command docker

docker compose version >/dev/null 2>&1 || {
  echo "ERROR: Docker Compose V2 is required." >&2
  exit 1
}

export UWFLOW_DOCKER_UID="$(id -u)"
export UWFLOW_DOCKER_GID="$(id -g)"
"${STUDIO_COMPOSE[@]}" build
