#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment
load_kestra_cli

VERSION="$(python -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
VERSION_UNDERSCORE="${VERSION//./_}"
RUNTIME_DIR="core/kestra/namespace-files/runtime/releases/${VERSION}"
FLOW_FILE="core/kestra/dev/flows/uwflow_dev_baseline_v${VERSION_UNDERSCORE}.yaml"
[[ -f "$RUNTIME_DIR/release-manifest.json" ]] || { echo "Missing runtime manifest: $RUNTIME_DIR" >&2; exit 1; }
[[ -f "$FLOW_FILE" ]] || { echo "Missing DEV baseline flow: $FLOW_FILE" >&2; exit 1; }

echo "Validating the DEV baseline flow against the configured Kestra server before publishing..."
kestractl flows validate "$FLOW_FILE"

publish_immutable_bundle \
  com.ai.credit.dev \
  "$RUNTIME_DIR" \
  "runtime/releases/${VERSION}"

if [[ "${UWFLOW_FAST_ROUTE_AUTO_DEPLOY:-false}" == "true" ]]; then
  echo "Fast Route: deploying the validated manual-only DEV baseline flow."
  kestractl flows deploy "$FLOW_FILE" --override --fail-fast
else
  read -r -p "Deploy the manual DEV baseline flow ${FLOW_FILE}? [y/N] " deploy_answer
  case "${deploy_answer,,}" in
    y|yes) kestractl flows deploy "$FLOW_FILE" --override --fail-fast ;;
    *) echo "Runtime bundle is present; flow deployment skipped." ;;
  esac
fi
