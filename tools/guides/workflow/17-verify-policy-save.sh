#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment

python -m modules.lifecycle.tools.validate_workspace
python -m pytest -q
python -m core.underwriting.tools.runtime_bundle --check

python - <<'PY'
import json
from pathlib import Path
workspace_root = Path("var/workspaces/strategies")
items = [json.loads(path.read_text()) for path in workspace_root.glob("*/workspace.json")]
if not items:
    raise SystemExit("No strategy workspace exists.")
for item in items:
    print(f"Workspace: {item['workspace_id']} — {item['name']}")
    print(f"Source: {item.get('source', {})}")
PY

echo "Workspace policy validation passed. Core source and its default policy remain unchanged."
