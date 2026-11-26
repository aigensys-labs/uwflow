#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment
load_history_credentials
require_history_database_healthy

DATASETS_JSON="$(python -m tools.history.datasets.list_datasets)"
printf '%s\n' "$DATASETS_JSON" | python -m json.tool
if [[ "${UWFLOW_FAST_ROUTE_DEFAULT_DATASET:-false}" == "true" ]]; then
  DATASET_ID=""
  echo "Fast Route selected the canonical FSTPD30 dataset (reuse today's immutable dataset or create it)."
else
  read -r -p "Enter an existing dataset_id to validate/reuse, or press Enter to create/reuse today's canonical dataset: " DATASET_ID
fi

contains_dataset() {
  printf '%s' "$DATASETS_JSON" | python -c \
    'import json,sys; wanted=sys.argv[1]; data=json.load(sys.stdin); sys.exit(0 if any(item.get("dataset_id")==wanted for item in data) else 1)' \
    "$1"
}

if [[ -n "$DATASET_ID" ]]; then
  if ! contains_dataset "$DATASET_ID"; then
    echo "ERROR: dataset_id is not present in this history store. No data was written." >&2
    exit 1
  fi
  echo "Validating existing immutable dataset: $DATASET_ID"
else
  AS_OF_DATE="$(date -u +%F)"
  AS_OF_COMPACT="${AS_OF_DATE//-/}"
  DATASET_ID="synthetic-eur-v4-fstpd30-seed-17-n-5000-asof-${AS_OF_COMPACT}"
  if contains_dataset "$DATASET_ID"; then
    echo "Today's canonical dataset already exists; validating and reusing it: $DATASET_ID"
  else
    echo "Creating a new immutable canonical dataset: $DATASET_ID"
    UWFLOW_HISTORY_READ_ONLY=false python -m tools.history.datasets.generate_synthetic \
      --dataset-id "$DATASET_ID" --count 5000 --seed 17 \
      --as-of-date "$AS_OF_DATE" --history-months 36 --allow-write
  fi
fi

# Refresh the manifest list after a newly generated dataset has been committed.
# The initial listing above is used only for the reuse/create decision.
DATASETS_JSON="$(python -m tools.history.datasets.list_datasets)"

# The analyst/CRO impact report requires a matured FSTPD30 target. Refuse to
# Select only a dataset that declares the required target contract.
python - "$DATASETS_JSON" "$DATASET_ID" <<'PYDATASET'
import json
import sys
manifests = json.loads(sys.argv[1])
selected = next((item for item in manifests if item.get("dataset_id") == sys.argv[2]), None)
if selected is None:
    raise SystemExit(f"ERROR: dataset manifest disappeared: {sys.argv[2]}")
metadata = selected.get("metadata") or {}
contract = str(selected.get("outcome_definition") or "").upper()
if metadata.get("target_name") != "FSTPD30" and "FSTPD30" not in contract:
    raise SystemExit(
        "ERROR: this dataset does not declare FSTPD30. The Champion/Challenger portfolio report "
        "requires a dataset with the first/second/third-payment 30+ DPD target. Select or create "
        "a synthetic-eur-v4-fstpd30 dataset. Older immutable datasets remain untouched."
    )
PYDATASET

# Do not record the dataset as selected until an independent read-back validates it.
python -m tools.history.datasets.validate_dataset --dataset-id "$DATASET_ID"
BASELINE_RELEASE="${UWFLOW_BASELINE_RELEASE:-$(read_state baseline-release 2.0.0)}"
[[ "$BASELINE_RELEASE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "ERROR: baseline release must be an exact semantic version (for example 2.0.0)." >&2
  exit 1
}
BASELINE_DIR="$(resolve_baseline_runtime "$BASELINE_RELEASE")"
[[ -f "$BASELINE_DIR/release-manifest.json" ]] || {
  echo "ERROR: selected baseline has no runtime release manifest: $BASELINE_DIR" >&2
  exit 1
}

if [[ "${UWFLOW_FAST_ROUTE:-false}" == "true" ]]; then
  # The infrastructure control must not reuse a candidate built from an
  # analyst workspace. Create a fresh Core-default workspace and package it.
  WORKSPACE_ID="$(python - <<'PYWORKSPACE'
from pathlib import Path
from modules.lifecycle.workspaces import WorkspaceStore
workspace = WorkspaceStore(Path.cwd()).create(
    "Fast Route Core-default control",
    source_type="fast-route-control",
    source_id="core-default",
)
print(workspace["workspace_id"])
PYWORKSPACE
)"
  CANDIDATE_JSON="$(python -m modules.lifecycle.tools.dev_candidate --baseline-release "$BASELINE_RELEASE" --workspace-id "$WORKSPACE_ID" --json)"
  CANDIDATE_ID="$(printf '%s' "$CANDIDATE_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["candidate_id"])')"
  echo "Fast Route created a fresh Core-default no-op candidate: $CANDIDATE_ID"
else
  CANDIDATE_ID="$(read_state candidate-id)"
  if [[ -n "$CANDIDATE_ID" ]]; then
    python - "$CANDIDATE_ID" "$BASELINE_RELEASE" <<'PYCANDIDATE'
import json
import sys
from pathlib import Path
from modules.lifecycle.workspaces import WorkspaceStore
candidate_id, baseline = sys.argv[1:]
root = Path.cwd()
source, manifest, _ = WorkspaceStore(root)._verify_candidate(candidate_id)
if manifest.get("based_on_production_release") != baseline:
    raise SystemExit(
        f"Candidate {candidate_id} was built against {manifest.get('based_on_production_release')}, "
        f"not selected baseline {baseline}. Rebuild or select a matching candidate."
    )
print(f"Verified selected v2 candidate: {candidate_id}")
PYCANDIDATE
  fi
fi

write_state dataset-id "$DATASET_ID"
write_state baseline-release "$BASELINE_RELEASE"
if [[ -n "${CANDIDATE_ID:-}" ]]; then
  write_state candidate-id "$CANDIDATE_ID"
fi
printf '\nValidated dataset selected for every replay: %s\n' "$DATASET_ID"
echo "Baseline selected: $BASELINE_RELEASE"
if [[ -n "${CANDIDATE_ID:-}" ]]; then
  echo "Candidate selected: $CANDIDATE_ID"
else
  echo "No candidate is selected yet. Build one in Policy Studio and verify it with workflow step 18."
fi
echo "Selection saved in var/operator-state (ignored by Git)."
echo "Target confirmed: FSTPD30; synthetic labels mature after the third-payment 30-day observation window."
