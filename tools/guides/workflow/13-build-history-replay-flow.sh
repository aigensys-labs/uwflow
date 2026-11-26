#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
load_python_environment

CANDIDATE_ID="$(require_candidate_id)"
BASELINE_RELEASE="$(read_state baseline-release 2.0.0)"

BUNDLE_OUTPUT="$(python -m modules.history.tools.history_tools_bundle)"
printf '%s\n' "$BUNDLE_OUTPUT"
TOOLS_ID="$(printf '%s\n' "$BUNDLE_OUTPUT" | sed -n 's/^HISTORY_TOOLS_BUNDLE_ID=//p' | tail -n 1)"
[[ "$TOOLS_ID" =~ ^ht-[0-9a-f]{16}$ ]] || {
  echo "ERROR: history-tools builder did not return a valid immutable bundle ID." >&2
  exit 1
}

FLOW_OUTPUT="$(python -m modules.evaluation.tools.history_replay_flow --candidate-id "$CANDIDATE_ID" --baseline-release "$BASELINE_RELEASE")"
printf '%s\n' "$FLOW_OUTPUT"
FLOW_ID="$(printf '%s\n' "$FLOW_OUTPUT" | sed -n 's/^REPLAY_FLOW_ID=//p' | tail -n 1)"
[[ -f "var/artifacts/replay-flows/${FLOW_ID}.yaml" ]] || {
  echo "ERROR: expected replay flow was not generated: $FLOW_ID" >&2
  exit 1
}

write_state history-tools-bundle-id "$TOOLS_ID"
write_state replay-flow-id "$FLOW_ID"
echo "Exact immutable history-tools bundle recorded: $TOOLS_ID"
echo "Replay flow recorded: $FLOW_ID"
