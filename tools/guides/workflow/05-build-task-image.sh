#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command docker

VERSION="$(python3 -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
CORE_IMAGE="ai/uwflow-core-runtime:${VERSION}"
IMAGE="ai/uwflow-runtime:${VERSION}"
if docker image inspect "$CORE_IMAGE" >/dev/null 2>&1 && docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Reusing existing Core and platform task images."
else
  bash tools/docker/build-images.sh
fi
docker image inspect "$CORE_IMAGE" >/dev/null
docker image inspect "$IMAGE" >/dev/null
echo "Core image ready: $CORE_IMAGE"
echo "Platform image ready: $IMAGE"
