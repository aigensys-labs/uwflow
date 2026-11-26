#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment
load_history_credentials
require_history_database_healthy
ensure_history_admin_connection

# This process always activates the repository var/venv itself, even in a newly
# opened Terminal B. Do not depend on activation state from another terminal.
UWFLOW_HISTORY_READ_ONLY=false python -m tools.history.database.initialize --allow-write
python -m tools.history.datasets.list_datasets
rm -f var/operator-state/history-owner-password-reconcile-approved
