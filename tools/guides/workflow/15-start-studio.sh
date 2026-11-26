#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
source tools/guides/workflow/lib/studio-compose.sh
require_repository_root
require_command docker
require_command curl
require_command python3

docker compose version >/dev/null 2>&1 || {
  echo "ERROR: Docker Compose V2 is required." >&2
  exit 1
}

# Map API-created policy and candidate files back to the current user's UID/GID.
# The frontend source remains read-only; dependencies and Vite cache use a
# persistent external volume shared by every extracted release directory.
export UWFLOW_DOCKER_UID="$(id -u)"
export UWFLOW_DOCKER_GID="$(id -g)"
studio_prepare_compose_stack

if [[ "${UWFLOW_STUDIO_DETACHED:-false}" == "true" ]]; then
  API_PORT="${UWFLOW_STUDIO_API_PORT:-9000}"
  WEB_PORT="${UWFLOW_STUDIO_WEB_PORT:-5173}"

  echo "Starting the complete Dockerized Policy Studio in detached mode..."
  echo "The API, frontend, and frontend-to-API proxy must all pass readiness checks."
  if ! "${STUDIO_COMPOSE[@]}" up --build -d; then
    echo "ERROR: Docker Compose could not start the Policy Studio stack." >&2
    echo "Policy Studio container status:" >&2
    "${STUDIO_COMPOSE[@]}" ps --all >&2 || true
    echo "Policy Studio startup logs:" >&2
    "${STUDIO_COMPOSE[@]}" logs --no-color --tail 150 studio-api studio-frontend >&2 || true
    exit 1
  fi

  ready=false
  for attempt in $(seq 1 90); do
    api_id="$("${STUDIO_COMPOSE[@]}" ps -q studio-api 2>/dev/null || true)"
    frontend_id="$("${STUDIO_COMPOSE[@]}" ps -q studio-frontend 2>/dev/null || true)"
    api_state="$(docker inspect --format '{{.State.Status}}' "$api_id" 2>/dev/null || true)"
    api_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$api_id" 2>/dev/null || true)"
    frontend_state="$(docker inspect --format '{{.State.Status}}' "$frontend_id" 2>/dev/null || true)"
    frontend_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$frontend_id" 2>/dev/null || true)"

    if [[ "$api_state" == "running" && "$api_health" == "healthy" \
      && "$frontend_state" == "running" && "$frontend_health" == "healthy" ]] \
      && curl --silent --fail --max-time 3 "http://127.0.0.1:${API_PORT}/api/health" >/dev/null \
      && curl --silent --fail --max-time 3 "http://127.0.0.1:${API_PORT}/api/stages" >/dev/null \
      && curl --silent --fail --max-time 3 "http://127.0.0.1:${WEB_PORT}/" >/dev/null \
      && curl --silent --fail --max-time 3 "http://127.0.0.1:${WEB_PORT}/src/main.tsx" >/dev/null \
      && curl --silent --fail --max-time 3 "http://127.0.0.1:${WEB_PORT}/src/App.tsx" >/dev/null \
      && curl --silent --fail --max-time 3 "http://127.0.0.1:${WEB_PORT}/api/stages" >/dev/null; then
      ready=true
      break
    fi

    if [[ "$api_state" == "exited" || "$api_state" == "dead" || "$api_health" == "unhealthy" \
      || "$frontend_state" == "exited" || "$frontend_state" == "dead" \
      || "$frontend_health" == "unhealthy" ]]; then
      echo "ERROR: a Policy Studio container exited or became unhealthy." >&2
      "${STUDIO_COMPOSE[@]}" ps >&2 || true
      "${STUDIO_COMPOSE[@]}" logs --tail 100 >&2 || true
      exit 1
    fi
    sleep 2
  done

  if [[ "$ready" != "true" ]]; then
    echo "ERROR: Policy Studio did not become ready within 180 seconds." >&2
    "${STUDIO_COMPOSE[@]}" ps >&2 || true
    "${STUDIO_COMPOSE[@]}" logs --tail 100 >&2 || true
    exit 1
  fi

  # A 200 from Vite alone is not enough: verify the complete frontend proxy and
  # API catalogue contract used by the React application.
  python3 - "$API_PORT" "$WEB_PORT" <<'PY'
import json
import sys
from urllib.request import urlopen

api_port, web_port = sys.argv[1:3]
expected_editable = {"stage_1_hard_gates", "stage_3_source_plan"}

for label, url in (
    ("Studio API", f"http://127.0.0.1:{api_port}/api/stages"),
    ("Frontend API proxy", f"http://127.0.0.1:{web_port}/api/stages"),
):
    with urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(f"{label} returned HTTP {response.status}.")
        stages = json.loads(response.read())
    if not isinstance(stages, list) or len(stages) != 7:
        raise SystemExit(f"{label} did not return the expected seven-stage catalogue.")
    editable = {stage["id"] for stage in stages if stage.get("editable") is True}
    if editable != expected_editable:
        raise SystemExit(f"{label} returned unexpected editable stages: {sorted(editable)}")
    print(f"PASS  {label}: seven stages; Stage 1 and Stage 3 are editable.")
PY

  "${STUDIO_COMPOSE[@]}" ps
  echo "Policy Studio API, React frontend, and frontend API proxy are healthy."
  echo "Frontend: http://127.0.0.1:${WEB_PORT}"
  echo "API:      http://127.0.0.1:${API_PORT}/docs"
  echo "Compose project: ${STUDIO_COMPOSE_PROJECT}"
  echo "Persistent frontend dependencies/cache: ${STUDIO_NODE_MODULES_VOLUME}"
  echo "No Node.js or npm installation is required on the host."
else
  echo "Starting the complete Dockerized Policy Studio..."
  echo "Frontend: http://127.0.0.1:${UWFLOW_STUDIO_WEB_PORT:-5173}"
  echo "API:      http://127.0.0.1:${UWFLOW_STUDIO_API_PORT:-9000}/docs"
  echo "Compose project: ${STUDIO_COMPOSE_PROJECT}"
  echo "No Node.js or npm installation is required on the host."
  exec "${STUDIO_COMPOSE[@]}" up --build
fi
