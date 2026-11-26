#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
source tools/guides/workflow/lib/studio-compose.sh
require_repository_root
require_command docker

# Stop only services belonging to the explicitly named current Studio project.
# The separately named dependency volume is external and remains untouched.
"${STUDIO_COMPOSE[@]}" down

echo "Policy Studio services stopped. The persistent frontend dependency volume was preserved."
