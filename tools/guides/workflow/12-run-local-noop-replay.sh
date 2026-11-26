#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment
load_history_credentials
require_history_database_healthy

DATASET_ID="$(require_dataset_id)"
CANDIDATE_ID="$(require_candidate_id)"
BASELINE_RELEASE="$(read_state baseline-release 2.0.0)"
BASELINE_DIR="$(resolve_baseline_runtime "$BASELINE_RELEASE")"
CANDIDATE_DIR="var/artifacts/candidates/${CANDIDATE_ID}"
[[ -f "$BASELINE_DIR/release-manifest.json" ]] || { echo "Baseline bundle is missing: $BASELINE_DIR" >&2; exit 1; }
[[ -f "$CANDIDATE_DIR/release-manifest.json" ]] || { echo "Candidate bundle is missing: $CANDIDATE_DIR" >&2; exit 1; }
python - "$BASELINE_DIR/release-manifest.json" "$CANDIDATE_DIR/release-manifest.json" "$BASELINE_RELEASE" "$CANDIDATE_ID" <<'PY'
import json, sys
from pathlib import Path
baseline_path, candidate_path, baseline_release, candidate_id = sys.argv[1:]
baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
assert candidate.get("candidate_id") == candidate_id
assert candidate.get("based_on_production_release") == baseline_release
assert candidate.get("files") == baseline.get("files"), "Included no-op candidate is not identical to the baseline"
print("No-op candidate parent and runtime-module checksums match the baseline.")
PY

OUTPUT_DIR="var/reports/history/local-${CANDIDATE_ID}"
mkdir -p "$OUTPUT_DIR"
python -m tools.history.replay.run_batch --dataset-id "$DATASET_ID" --runtime-root "$BASELINE_DIR" --output "$OUTPUT_DIR/baseline.jsonl" --batch-size 2000 --offset 0 --max-cases 100
python -m tools.history.replay.run_batch --dataset-id "$DATASET_ID" --runtime-root "$CANDIDATE_DIR" --output "$OUTPUT_DIR/candidate.jsonl" --batch-size 2000 --offset 0 --max-cases 100
python -m tools.history.replay.compare_batches --baseline "$OUTPUT_DIR/baseline.jsonl" --candidate "$OUTPUT_DIR/candidate.jsonl" --output-dir "$OUTPUT_DIR/comparison"
cat "$OUTPUT_DIR/comparison/comparison.json"
echo "Local 100-case replay completed. The no-op comparison should report zero decision, score and amount differences."
