#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command openssl

if [[ ! -e .env ]]; then
  bash tools/guides/workflow/lib/create-local-env.sh
else
  echo "Reusing existing .env; credentials were not regenerated."
fi
for key in KESTRA_SERVER_BASIC_AUTH_USERNAME KESTRA_SERVER_BASIC_AUTH_PASSWORD SECRET_UNDERWRITING_WEBHOOK_KEY; do
  grep -q "^${key}=" .env || { echo "ERROR: .env is missing $key; it was not overwritten." >&2; exit 1; }
done
chmod 600 .env
echo "Local Kestra credentials are present and protected (mode 600)."
