#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../" && pwd)"
ENV_FILE="${ROOT}/.env.history"
KESTRA_ENV_FILE="${ROOT}/.env.history.kestra"

if [[ -e "${ENV_FILE}" || -e "${KESTRA_ENV_FILE}" ]]; then
  echo "A history environment file already exists. Nothing was changed." >&2
  echo "Keep the existing credentials, or back up and remove both files deliberately before regenerating." >&2
  exit 1
fi

for command in openssl base64 docker; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done

# Never mint new passwords when a persistent database already exists. The
# POSTGRES_PASSWORD supplied by Compose is only used during first-time initdb;
# changing .env.history later does not change the password stored in the volume.
if docker inspect uwflow-history-db >/dev/null 2>&1 || docker volume inspect uwflow_history_pgdata >/dev/null 2>&1; then
  cat >&2 <<'MESSAGE'
ERROR: a historical PostgreSQL container or persistent volume already exists,
but the paired credential files are absent. Refusing to generate new passwords.

Restore the original .env.history and .env.history.kestra from a protected backup,
or use the documented credential-reconciliation workflow after restoring a
valid, internally consistent .env.history. Do not delete or recreate the volume.
MESSAGE
  exit 1
fi

# Create the shared network before writing credential files so a Docker
# failure cannot leave half-configured secrets that block a clean retry.
if ! docker network inspect uwflow-local >/dev/null 2>&1; then
  docker network create uwflow-local >/dev/null
fi

DB_PASSWORD="$(openssl rand -hex 24)"
READ_PASSWORD="$(openssl rand -hex 24)"
WRITE_PASSWORD="$(openssl rand -hex 24)"

DB="uwflow_history"
OWNER="uwflow_history_owner"
READER="uwflow_history_reader"
WRITER="uwflow_history_writer"
PORT="55432"

ADMIN_DSN="postgresql+psycopg://${OWNER}:${DB_PASSWORD}@127.0.0.1:${PORT}/${DB}"
READ_DSN="postgresql+psycopg://${READER}:${READ_PASSWORD}@127.0.0.1:${PORT}/${DB}"
WRITE_DSN="postgresql+psycopg://${WRITER}:${WRITE_PASSWORD}@127.0.0.1:${PORT}/${DB}"
KESTRA_READ_DSN="postgresql+psycopg://${READER}:${READ_PASSWORD}@uwflow-history-db:5432/${DB}"
KESTRA_READ_DSN_B64="$(printf '%s' "${KESTRA_READ_DSN}" | base64 | tr -d '\n')"
KESTRA_CONNECTOR_B64="$(printf '%s' 'postgres' | base64 | tr -d '\n')"
KESTRA_HISTORY_ROOT_B64="$(printf '%s' '/data/uwflow/history' | base64 | tr -d '\n')"

cat > "${ENV_FILE}" <<EOF
# Local-only historical store credentials. Never commit this file.
UWFLOW_HISTORY_CONNECTOR=postgres
UWFLOW_HISTORY_DB=${DB}
UWFLOW_HISTORY_PORT=${PORT}
UWFLOW_HISTORY_OWNER_USER=${OWNER}
UWFLOW_HISTORY_OWNER_PASSWORD=${DB_PASSWORD}
UWFLOW_HISTORY_READ_USER=${READER}
UWFLOW_HISTORY_READ_PASSWORD=${READ_PASSWORD}
UWFLOW_HISTORY_WRITE_USER=${WRITER}
UWFLOW_HISTORY_WRITE_PASSWORD=${WRITE_PASSWORD}
UWFLOW_HISTORY_ADMIN_DSN=${ADMIN_DSN}
UWFLOW_HISTORY_DSN=${READ_DSN}
UWFLOW_HISTORY_WRITE_DSN=${WRITE_DSN}
# These values are consumed both by Bash (source) and Docker Compose (--env-file).
# Quote them so repository paths containing spaces remain a single value.
UWFLOW_HISTORY_ROOT="${ROOT}/var/data/history"
UWFLOW_HISTORY_WRITE_ROOT="${ROOT}/var/data/history"
UWFLOW_HISTORY_DOCKER_ROOT="${ROOT}/var/data/history"
UWFLOW_HISTORY_BATCH_SIZE=2000
UWFLOW_HISTORY_READ_ONLY=true
EOF

cat > "${KESTRA_ENV_FILE}" <<EOF
# Kestra OSS secret variables must be Base64-encoded.
SECRET_UWFLOW_HISTORY_CONNECTOR=${KESTRA_CONNECTOR_B64}
SECRET_UWFLOW_HISTORY_DSN=${KESTRA_READ_DSN_B64}
SECRET_UWFLOW_HISTORY_ROOT=${KESTRA_HISTORY_ROOT_B64}
EOF

chmod 600 "${ENV_FILE}" "${KESTRA_ENV_FILE}"

printf '\nCreated local history credentials:\n'
printf '  %s\n' "${ENV_FILE}" "${KESTRA_ENV_FILE}"
printf '\nDocker network ready: uwflow-local\n'
printf 'The Kestra secret file contains only the read-only DSN in Kestra OSS Base64 secret format.\n'
printf 'Do not commit either file or share their contents.\n'
printf '\nNext: docker compose --env-file .env.history -f modules/history/compose.yml up -d\n'
