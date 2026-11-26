#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root

for command_name in docker python3 curl openssl bash; do require_command "$command_name"; done
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required")
print(f"Python: {sys.version.split()[0]}")
PY
if ! python3 -m venv --help >/dev/null 2>&1; then
  cat >&2 <<'MESSAGE'
ERROR: the Python venv module is not installed for the selected python3 interpreter.
Install the matching operating-system package, then rerun the Fast Route.
On Debian/Ubuntu this is usually python3-venv or python3.X-venv.
No package was installed automatically.
MESSAGE
  exit 1
fi
echo "Python venv module: available"

docker --version
docker compose version
docker info >/dev/null
echo "Docker daemon: available"
openssl version
printf 'Repository root: %s\n' "$(pwd -P)"
