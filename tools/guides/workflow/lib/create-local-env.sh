#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../" && pwd)"
ENV_FILE="${ROOT}/.env"

if [[ -e "${ENV_FILE}" ]]; then
  echo "${ENV_FILE} already exists. It was not changed." >&2
  echo "Keep it, or remove it deliberately before generating new local credentials." >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "OpenSSL is required to generate local credentials. Install openssl and retry." >&2
  exit 1
fi

USERNAME="admin@uwflow.local"
PASSWORD="UWflow-$(openssl rand -hex 18)"
WEBHOOK_RAW="$(openssl rand -hex 32)"
WEBHOOK_B64="$(printf '%s' "${WEBHOOK_RAW}" | openssl base64 -A)"

cat > "${ENV_FILE}" <<EOF
KESTRA_SERVER_BASIC_AUTH_USERNAME=${USERNAME}
KESTRA_SERVER_BASIC_AUTH_PASSWORD=${PASSWORD}
SECRET_UNDERWRITING_WEBHOOK_KEY=${WEBHOOK_B64}
UWFLOW_STUDIO_API_PORT=9000
UWFLOW_STUDIO_WEB_PORT=5173
EOF
chmod 600 "${ENV_FILE}"

printf '\nLocal Kestra credentials created in .env (file permissions: 600).\n'
if [[ "${UWFLOW_SUPPRESS_CREDENTIAL_OUTPUT:-false}" == "true" ]]; then
  printf 'Credential values will be displayed once at the end of the DEV Fast Route.\n'
else
  printf 'Username: %s\n' "${USERNAME}"
  printf 'Password: %s\n\n' "${PASSWORD}"
  printf 'The webhook key is stored base64-encoded for Kestra Open Source.\n'
  printf 'Do not commit .env or share these credentials.\n\n'
fi
