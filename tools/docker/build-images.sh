#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Build the immutable-version-tagged UWflow task images from the repository root.

Usage: bash tools/docker/build-images.sh [--core-only] [--push] [--replace-existing] [--no-cache] [--version VERSION]

Options:
  --core-only         Build only the reusable Core task image.
  --push              Push the resulting image tag(s) to the configured registry.
  --replace-existing  Rebuild tags that already exist in the local Docker daemon.
  --no-cache          Disable Docker layer cache.
  --version VERSION   Override the project version used for image tags.
USAGE
}

CORE_ONLY=0
PUSH=0
REPLACE=0
NO_CACHE=0
VERSION=""
while (($#)); do
  case "$1" in
    --core-only) CORE_ONLY=1; shift ;;
    --push) PUSH=1; shift ;;
    --replace-existing) REPLACE=1; shift ;;
    --no-cache) NO_CACHE=1; shift ;;
    --version)
      [[ $# -ge 2 && -n "$2" ]] || { echo "ERROR: --version requires a value." >&2; exit 2; }
      VERSION="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 1; }
if [[ -z "$VERSION" ]]; then
  VERSION="$(python3 -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
fi
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || {
  echo "ERROR: invalid image version: $VERSION" >&2; exit 2;
}

CORE_IMAGE="ai/uwflow-core-runtime:${VERSION}"
PLATFORM_IMAGE="ai/uwflow-runtime:${VERSION}"
DOCKER_FLAGS=()
(( NO_CACHE == 0 )) || DOCKER_FLAGS+=(--no-cache)

build_image() {
  local image="$1"; shift
  if (( REPLACE == 0 )) && docker image inspect "$image" >/dev/null 2>&1; then
    echo "Reusing existing image: $image"
    return
  fi
  docker build "${DOCKER_FLAGS[@]}" "$@" --tag "$image" .
}

build_image "$CORE_IMAGE" \
  --file core/docker/Dockerfile \
  --build-arg "UWFLOW_VERSION=${VERSION}"

if (( CORE_ONLY == 0 )); then
  build_image "$PLATFORM_IMAGE" \
    --file modules/platform-runtime/Dockerfile \
    --build-arg "CORE_IMAGE=ai/uwflow-core-runtime" \
    --build-arg "UWFLOW_VERSION=${VERSION}"
fi

if (( PUSH == 1 )); then
  docker push "$CORE_IMAGE"
  if (( CORE_ONLY == 0 )); then docker push "$PLATFORM_IMAGE"; fi
fi

echo "Core image ready: $CORE_IMAGE"
if (( CORE_ONLY == 0 )); then echo "Platform image ready: $PLATFORM_IMAGE"; fi
if (( PUSH == 1 )); then
  echo "Resolve the pushed Core image's registry digest and pass the exact repo@sha256 digest to the approved-release assembler."
fi
