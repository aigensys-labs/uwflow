#!/usr/bin/env bash
# Shared Docker Compose identity and persistent dependency-volume setup.
# This helper manages only the current stable Studio project. It never searches
# for, stops, renames, or removes containers from other Compose projects.

STUDIO_COMPOSE_PROJECT="uwflow-studio"
STUDIO_COMPOSE_FILE="modules/policy-studio/compose.yml"
STUDIO_NODE_MODULES_VOLUME="uwflow_studio_node_modules"
STUDIO_COMPOSE=(docker compose --project-name "$STUDIO_COMPOSE_PROJECT" -f "$STUDIO_COMPOSE_FILE")

studio_ensure_node_modules_volume() {
  if docker volume inspect "$STUDIO_NODE_MODULES_VOLUME" >/dev/null 2>&1; then
    return 0
  fi
  echo "Creating persistent Policy Studio dependency volume: $STUDIO_NODE_MODULES_VOLUME"
  docker volume create "$STUDIO_NODE_MODULES_VOLUME" >/dev/null
}

studio_prepare_compose_stack() {
  studio_ensure_node_modules_volume
}
