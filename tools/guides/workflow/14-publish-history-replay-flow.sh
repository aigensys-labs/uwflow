#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment
load_kestra_cli

CANDIDATE_ID="$(require_candidate_id)"
BASELINE_RELEASE="$(read_state baseline-release 2.0.0)"
TOOLS_ID="$(read_state history-tools-bundle-id)"
FLOW_ID="$(read_state replay-flow-id)"
[[ "$TOOLS_ID" =~ ^ht-[0-9a-f]{16}$ ]] || {
  echo "ERROR: no exact history-tools bundle is recorded. Run workflow step 13 first." >&2
  exit 1
}
[[ "$FLOW_ID" =~ ^uwflow_dev_history_replay_[0-9a-f]{10}$ ]] || {
  echo "ERROR: no replay flow is recorded. Run workflow step 13 first." >&2
  exit 1
}

BASELINE_DIR="$(resolve_baseline_runtime "$BASELINE_RELEASE")"
CANDIDATE_DIR="var/artifacts/candidates/${CANDIDATE_ID}"
TOOLS_DIR="var/artifacts/tool-bundles/history/${TOOLS_ID}"
FLOW_FILE="var/artifacts/replay-flows/${FLOW_ID}.yaml"
for required_path in "$BASELINE_DIR/release-manifest.json" "$CANDIDATE_DIR/release-manifest.json" "$TOOLS_DIR/release-manifest.json" "$FLOW_FILE"; do
  [[ -f "$required_path" ]] || { echo "ERROR: required artifact is missing: $required_path" >&2; exit 1; }
done

# Verify the exact current v2 candidate contract, full History bundle and
# replay-flow references before any Namespace Files upload or deployment.
python - "$CANDIDATE_ID" "$BASELINE_RELEASE" "$TOOLS_ID" "$FLOW_ID" "$BASELINE_DIR" "$TOOLS_DIR" "$FLOW_FILE" <<'PYARTIFACTS'
import hashlib
import json
import sys
from pathlib import Path
from modules.lifecycle.workspaces import WorkspaceStore

candidate_id, baseline_id, tools_id, flow_id, baseline_dir, tools_dir, flow_file = sys.argv[1:]
root = Path.cwd()
_, candidate, _ = WorkspaceStore(root)._verify_candidate(candidate_id)
if candidate.get("based_on_production_release") != baseline_id:
    raise SystemExit("Candidate baseline does not match the selected baseline release.")

baseline_manifest = json.loads((Path(baseline_dir) / "release-manifest.json").read_text(encoding="utf-8"))
if baseline_manifest.get("release_version") != baseline_id:
    raise SystemExit("Baseline manifest identity does not match the selected baseline release.")

bundle_root = Path(tools_dir)
bundle_manifest = json.loads((bundle_root / "release-manifest.json").read_text(encoding="utf-8"))
if bundle_manifest.get("artifact_type") != "uwflow-history-tools" or bundle_manifest.get("bundle_id") != tools_id:
    raise SystemExit("History tooling bundle identity/type is invalid.")
files = bundle_manifest.get("files")
if not isinstance(files, dict) or not files:
    raise SystemExit("History tooling bundle manifest has no file checksums.")
for relative, expected in files.items():
    path = (bundle_root / relative).resolve()
    if bundle_root.resolve() not in path.parents or not path.is_file():
        raise SystemExit(f"History tooling bundle file is missing or unsafe: {relative}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"History tooling bundle checksum mismatch: {relative}")

flow_path = Path(flow_file)
flow_text = flow_path.read_text(encoding="utf-8")
for expected in (
    f"id: {flow_id}",
    f"baseline-release: {baseline_id}",
    f"candidate-id: {candidate_id}",
    f"history-tools-bundle: {tools_id}",
    f"history-tools/{tools_id}/",
    f"runtime/candidates/{candidate_id}/",
):
    if expected not in flow_text:
        raise SystemExit(f"Replay flow does not pin the selected artifact identity: {expected}")
print("Candidate, baseline, History bundle checksums and replay-flow identities verified.")
PYARTIFACTS

# The replay flow must pin the exact tooling bundle selected by Step 13. This
# catches stale var/operator-state copied from an older checkout before upload.
grep -Fq "\"release_version\": \"$BASELINE_RELEASE\"" "$BASELINE_DIR/release-manifest.json" || {
  echo "ERROR: baseline manifest does not match selected release $BASELINE_RELEASE." >&2
  exit 1
}
grep -Fq "\"candidate_id\": \"$CANDIDATE_ID\"" "$CANDIDATE_DIR/release-manifest.json" || {
  echo "ERROR: candidate manifest does not match selected candidate $CANDIDATE_ID." >&2
  exit 1
}
grep -Fq "\"bundle_id\": \"$TOOLS_ID\"" "$TOOLS_DIR/release-manifest.json" || {
  echo "ERROR: history-tools manifest does not match selected bundle $TOOLS_ID. Re-run Step 13." >&2
  exit 1
}
grep -Fq "history-tools/$TOOLS_ID/" "$FLOW_FILE" || {
  echo "ERROR: replay flow does not reference history-tools bundle $TOOLS_ID. Re-run Step 13." >&2
  exit 1
}

echo "Validating the replay flow against the configured Kestra server before publishing any bundles..."
kestractl flows validate "$FLOW_FILE"
echo "Kestra accepted the replay flow definition. Proceeding with immutable bundle publication."

publish_immutable_bundle com.ai.credit.dev "$BASELINE_DIR" "runtime/releases/${BASELINE_RELEASE}"
publish_immutable_bundle com.ai.credit.dev "$CANDIDATE_DIR" "runtime/candidates/${CANDIDATE_ID}"
publish_immutable_bundle com.ai.credit.dev "$TOOLS_DIR" "history-tools/${TOOLS_ID}"

kestractl flows deploy "$FLOW_FILE" --override --fail-fast
write_state replay-flow-id "$FLOW_ID"
echo "Deployed DEV history replay flow: $FLOW_ID"
