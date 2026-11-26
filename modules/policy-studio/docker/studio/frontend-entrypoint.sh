#!/bin/sh
set -eu

cd /workspace

# The source tree is mounted read-only at /workspace/frontend. Keep npm's
# writable package root, node_modules volume and Vite optimizer cache alongside
# it, not beneath that bind mount.
cp frontend/package.json package.json
current_marker="$(sha256sum frontend/package.json | awk '{print $1}') $(node --version)"
installed_marker=""
if [ -r node_modules/.uwflow-package-hash ]; then
  installed_marker="$(cat node_modules/.uwflow-package-hash)"
fi

if [ ! -x node_modules/.bin/vite ] || [ "$current_marker" != "$installed_marker" ]; then
  echo "Installing Policy Studio frontend dependencies inside the Docker volume..."
  npm install --prefix /workspace --no-package-lock --no-audit --no-fund
  printf '%s\n' "$current_marker" > node_modules/.uwflow-package-hash
fi

cache_dir="${UWFLOW_VITE_CACHE_DIR:-/workspace/node_modules/.vite}"
if ! mkdir -p "$cache_dir" || [ ! -w "$cache_dir" ]; then
  echo "ERROR: the Policy Studio dependency volume is not writable at: $cache_dir" >&2
  echo "Check ownership of Docker volume: uwflow_studio_node_modules" >&2
  exit 1
fi

exec npm --prefix /workspace run dev -- \
  --config /workspace/frontend/vite.config.ts \
  /workspace/frontend \
  --host 0.0.0.0 \
  --port 5173
