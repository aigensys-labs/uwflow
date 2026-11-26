#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
ensure_python_environment
load_python_environment
python -m pip install --upgrade pip
python -m pip install -e ".[dev,studio,history-postgres,history-parquet]"
python -W error -c 'import httpx2; from fastapi.testclient import TestClient; print(f"Starlette TestClient transport: httpx2 {httpx2.__version__}")'
python -m pytest -q
python -m tools.policy.compiler --check
python -m core.underwriting.tools.runtime_bundle --check
# History tooling is a derived immutable artifact, not a pre-populated package file.
# Build/reuse it from tracked Module sources before checking its manifest and payload.
python -m modules.history.tools.history_tools_bundle
python -m modules.history.tools.history_tools_bundle --check
