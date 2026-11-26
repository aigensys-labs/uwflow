#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment

read -r -p "Paste the candidate ID shown by Policy Studio (dev- plus 16 hex characters): " CANDIDATE_ID
read -r -p "Baseline release used in Policy Studio [2.0.0]: " BASELINE_RELEASE
BASELINE_RELEASE="${BASELINE_RELEASE:-$(read_state baseline-release 2.0.0)}"
if [[ ! "$CANDIDATE_ID" =~ ^dev-[0-9a-f]{16}$ ]]; then
  echo "ERROR: candidate ID format is invalid: $CANDIDATE_ID" >&2
  exit 2
fi
MANIFEST="var/artifacts/candidates/${CANDIDATE_ID}/release-manifest.json"
[[ -f "$MANIFEST" ]] || { echo "Candidate manifest not found: $MANIFEST. Ensure the Studio saved the candidate into this repository." >&2; exit 1; }
python - "$MANIFEST" "$CANDIDATE_ID" "$BASELINE_RELEASE" <<'PY'
import json, sys
from pathlib import Path
manifest_path, candidate_id, baseline_release = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
assert manifest.get("candidate_id") == candidate_id
assert manifest.get("based_on_production_release") == baseline_release
assert manifest.get("files"), "Candidate manifest has no runtime file hashes"
print("Candidate:", candidate_id)
print("Frozen baseline:", manifest["based_on_production_release"])
print("Production release ID:", "not assigned at candidate-build time")
print("Runtime module count:", len(manifest["files"]))
PY
write_state candidate-id "$CANDIDATE_ID"
write_state baseline-release "$BASELINE_RELEASE"
echo "Candidate ID and baseline saved for later replay steps."
