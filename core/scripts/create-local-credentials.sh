#!/usr/bin/env bash
set -Eeuo pipefail

CORE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "${CORE_ROOT}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if ! command -v openssl >/dev/null 2>&1; then
  echo "OpenSSL is required to generate local Kestra credentials. Install it and retry." >&2
  exit 127
fi

if [[ -e "${ENV_FILE}" ]]; then
  for key in KESTRA_SERVER_BASIC_AUTH_USERNAME KESTRA_SERVER_BASIC_AUTH_PASSWORD SECRET_UNDERWRITING_WEBHOOK_KEY; do
    grep -Eq "^${key}=.+$" "${ENV_FILE}" || {
      echo "ERROR: existing .env is missing ${key}; it was not modified." >&2
      exit 1
    }
  done
  chmod 600 "${ENV_FILE}"
  echo "Reusing existing .env; local Kestra credentials were not regenerated."
  exit 0
fi

USERNAME="admin@uwflow.local"
PASSWORD="UWflow-$(openssl rand -hex 18)"
WEBHOOK_RAW="$(openssl rand -hex 32)"
WEBHOOK_B64="$(printf '%s' "${WEBHOOK_RAW}" | openssl base64 -A)"

cat > "${ENV_FILE}" <<EOF
KESTRA_SERVER_BASIC_AUTH_USERNAME=${USERNAME}
KESTRA_SERVER_BASIC_AUTH_PASSWORD=${PASSWORD}
SECRET_UNDERWRITING_WEBHOOK_KEY=${WEBHOOK_B64}
EOF
chmod 600 "${ENV_FILE}"
printf 'Core-only Kestra credentials created in %s (permissions: 600).\n' "${ENV_FILE}"
printf 'Username: %s\nPassword: %s\n' "${USERNAME}" "${PASSWORD}"
printf 'Keep this password private. The webhook key is stored Base64-encoded.\n'
