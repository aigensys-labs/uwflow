#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment

printf '\n== Check Python formatting and lint ==\n'
ruff format --check core modules tests tools
ruff check core modules tests tools

printf '\n== Compile canonical policies ==\n'
python -m tools.policy.compiler
python -m tools.policy.compiler --check

printf '\n== Run repository tests ==\n'
python -m pytest -q

printf '\n== Verify immutable and content-addressed bundles ==\n'
python -m core.underwriting.tools.runtime_bundle --check
python -m modules.history.tools.history_tools_bundle
python -m modules.history.tools.history_tools_bundle --check
