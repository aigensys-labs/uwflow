#!/usr/bin/env bash
# Shared setup for the documented, one-command UWflow operator workflow.
# All workflow scripts are launched from the UWflow repository root.

set -euo pipefail

require_repository_root() {
  if [[ ! -f pyproject.toml || ! -f docker-run.sh || ! -d core/docker || ! -d core/kestra || ! -d tools ]]; then
    cat >&2 <<'MESSAGE'
ERROR: this command must be run from the UWflow repository root.
Open a terminal in the extracted 'uwflow' folder: the folder containing
pyproject.toml, docker-run.sh, core/ and modules/.
Then run the one-line command from the guide again.
MESSAGE
    exit 2
  fi
}

add_user_bin_to_path() {
  local user_bin="${HOME}/.local/bin"
  if [[ -d "$user_bin" && ":${PATH}:" != *":${user_bin}:"* ]]; then
    export PATH="${user_bin}:${PATH}"
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $command_name" >&2
    exit 127
  fi
}

ensure_python_environment() {
  require_command python3
  mkdir -p var

  if [[ -e var/venv && ! -d var/venv ]]; then
    echo "ERROR: var/venv exists but is not a directory. Move or remove that file, then rerun Step 01." >&2
    return 1
  fi

  # A directory alone is not a usable virtual environment. Older/incomplete
  # checkouts can leave an empty var/venv or one without its activation script.
  # Validate both entry points and the interpreter prefix before reusing it.
  if [[ -x var/venv/bin/python && -r var/venv/bin/activate ]] \
    && var/venv/bin/python -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' >/dev/null 2>&1; then
    echo "Reusing valid var/venv"
    return 0
  fi

  if [[ -e var/venv ]]; then
    echo "Found an incomplete or invalid var/venv; rebuilding the project environment."
    echo "Only the managed var/venv directory will be cleared; repository files and data are untouched."
    python3 -m venv --clear var/venv || {
      echo "ERROR: unable to repair var/venv. Ensure the Python venv module is installed for this interpreter." >&2
      echo "On Debian/Ubuntu, the system package is usually: python3-venv (or python3.12-venv for a versioned interpreter)." >&2
      return 1
    }
  else
    echo "Creating project virtual environment: var/venv"
    python3 -m venv var/venv || {
      echo "ERROR: unable to create var/venv. Ensure the Python venv module is installed for this interpreter." >&2
      echo "On Debian/Ubuntu, the system package is usually: python3-venv (or python3.12-venv for a versioned interpreter)." >&2
      return 1
    }
  fi

  if [[ ! -x var/venv/bin/python || ! -r var/venv/bin/activate ]] \
    || ! var/venv/bin/python -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' >/dev/null 2>&1; then
    echo "ERROR: Python did not create a valid project virtual environment at var/venv." >&2
    return 1
  fi
  echo "Project virtual environment is ready."
}

load_python_environment() {
  if [[ ! -x var/venv/bin/python || ! -r var/venv/bin/activate ]]; then
    echo "ERROR: the project virtual environment is missing or incomplete." >&2
    echo "Run Step 1 in core/kestra/README.md to create the minimal Core var/venv, then retry." >&2
    exit 1
  fi
  # Every workflow script gets its own activation. A newly opened terminal
  # never inherits another terminal's var/venv state.
  # shellcheck disable=SC1091
  source var/venv/bin/activate
  export PYTHONUNBUFFERED=1
  python -c 'import sys; assert sys.prefix != sys.base_prefix, "Project var/venv is not active"'
}

load_local_kestra_credentials() {
  [[ -r .env ]] || {
    echo "ERROR: .env is missing. Run: bash tools/guides/workflow/03-create-local-credentials.sh" >&2
    exit 1
  }
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  : "${KESTRA_SERVER_BASIC_AUTH_USERNAME:?Missing username in .env}"
  : "${KESTRA_SERVER_BASIC_AUTH_PASSWORD:?Missing password in .env}"
  export KESTRACTL_HOST="http://localhost:8080"
  export KESTRACTL_TENANT="main"
  export KESTRACTL_USERNAME="$KESTRA_SERVER_BASIC_AUTH_USERNAME"
  export KESTRACTL_PASSWORD="$KESTRA_SERVER_BASIC_AUTH_PASSWORD"
}

load_history_credentials() {
  [[ -r .env.history ]] || {
    echo "ERROR: .env.history is missing or unreadable." >&2
    echo "Run: bash tools/guides/workflow/04-create-history-credentials.sh" >&2
    exit 1
  }
  set -a
  # shellcheck disable=SC1091
  . ./.env.history
  set +a

  : "${UWFLOW_HISTORY_CONNECTOR:?Missing history connector setting}"
  : "${UWFLOW_HISTORY_ADMIN_DSN:?Missing history admin DSN}"
  : "${UWFLOW_HISTORY_DSN:?Missing history read-only DSN}"
  : "${UWFLOW_HISTORY_WRITE_DSN:?Missing history writer DSN}"

  local expected_history_root="$(pwd -P)/var/data/history"
  local name
  for name in UWFLOW_HISTORY_ROOT UWFLOW_HISTORY_WRITE_ROOT UWFLOW_HISTORY_DOCKER_ROOT; do
    if [[ "${!name:-}" != "$expected_history_root" ]]; then
      echo "ERROR: $name is not the expected complete path." >&2
      echo "Expected: $expected_history_root" >&2
      echo "Actual:   ${!name:-<missing>}" >&2
      echo "Check that the setting is double-quoted in .env.history." >&2
      exit 1
    fi
  done
}

write_state() {
  local name="$1"
  local value="$2"
  mkdir -p var/operator-state
  printf '%s\n' "$value" > "var/operator-state/$name"
}

read_state() {
  local name="$1"
  local default_value="${2:-}"
  local file="var/operator-state/$name"
  if [[ -s "$file" ]]; then
    cat "$file"
  else
    printf '%s' "$default_value"
  fi
}

load_kestra_cli() {
  # The official installer may choose ~/.local/bin when /usr/local/bin is not writable.
  # Add it in every terminal, rather than relying on installer shell startup edits.
  add_user_bin_to_path
  require_command kestractl
  load_local_kestra_credentials
}


nsfiles_list_directory() {
  local namespace="$1"
  local namespace_path="$2"
  local listing
  local command_status=0

  if listing="$(kestractl nsfiles list "$namespace" --path "$namespace_path" --recursive 2>&1)"; then
    printf '%s\n' "$listing"
    return 0
  else
    command_status=$?
  fi

  # kestractl returns a non-zero API result when a Namespace Files directory
  # has never been uploaded. That is a normal first-publication state, not an
  # operational error. Match the exact requested path; all other errors remain
  # visible and fatal to the caller.
  if [[ "$listing" == *"Directory not found: $namespace_path"* ]]; then
    printf 'Namespace Files directory has not been created yet: %s\n' "$namespace_path"
    return 10
  fi

  printf '%s\n' "$listing" >&2
  return "$command_status"
}

publish_immutable_bundle() {
  local namespace="$1"
  local source_directory="$2"
  local namespace_path="$3"
  local listing
  local command_status=0
  local answer=""
  local staging_parent
  local staged_directory

  if [[ ! -d "$source_directory" ]]; then
    echo "ERROR: local immutable bundle directory is missing: $source_directory" >&2
    return 1
  fi
  if [[ ! -f "$source_directory/release-manifest.json" ]]; then
    echo "ERROR: bundle manifest is missing: $source_directory/release-manifest.json" >&2
    return 1
  fi

  # Verify every manifest checksum and construct a clean upload directory.
  # This deliberately excludes local __pycache__, .pyc and other unmanifested files.
  staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/uwflow-nsfiles.XXXXXX")"
  staged_directory="$staging_parent/bundle"
  if ! python tools/kestra/namespace_files.py stage \
      --source "$source_directory" \
      --destination "$staged_directory"; then
    rm -rf "$staging_parent"
    return 1
  fi

  echo
  echo "Checking DEV Namespace Files path: $namespace_path"
  if listing="$(nsfiles_list_directory "$namespace" "$namespace_path" 2>&1)"; then
    printf '%s\n' "$listing"
    echo "The immutable path already exists. UWflow will never upload over it."
    read -r -p "Have you confirmed every manifest-listed file is present in this remote listing? [y=reuse / anything else=stop] " answer
    case "${answer,,}" in
      y|yes)
        rm -rf "$staging_parent"
        echo "Reusing existing immutable bundle: $namespace_path"
        return 0
        ;;
      *)
        rm -rf "$staging_parent"
        echo "STOP: existing immutable path was not confirmed. No files were changed." >&2
        echo "Investigate the remote contents; do not overwrite an immutable bundle." >&2
        return 2
        ;;
    esac
  else
    command_status=$?
  fi

  if [[ "$command_status" -ne 10 ]]; then
    rm -rf "$staging_parent"
    printf '%s\n' "$listing" >&2
    echo "ERROR: unable to inspect DEV Namespace Files path: $namespace_path" >&2
    return "$command_status"
  fi

  printf '%s\n' "$listing"
  if [[ "${UWFLOW_FAST_ROUTE_AUTO_UPLOAD:-false}" == "true" ]]; then
    echo "Fast Route: uploading this new immutable content-addressed path."
  else
    read -r -p "This path is absent. Upload the immutable bundle now? [Y/n] " answer
    case "${answer,,}" in
      n|no)
        rm -rf "$staging_parent"
        echo "Upload skipped. The required Namespace Files bundle is still absent." >&2
        return 2
        ;;
      ""|y|yes)
        ;;
      *)
        rm -rf "$staging_parent"
        echo "ERROR: answer y/Enter to upload, or n to stop." >&2
        return 2
        ;;
    esac
  fi

  if ! kestractl nsfiles upload \
    "$namespace" \
    "$staged_directory" \
    "$namespace_path" \
    --no-root \
    --fail-fast \
    --allow-missing-namespace; then
    rm -rf "$staging_parent"
    return 1
  fi
  rm -rf "$staging_parent"

  echo "Verifying uploaded immutable bundle: $namespace_path"
  if listing="$(nsfiles_list_directory "$namespace" "$namespace_path" 2>&1)"; then
    :
  else
    command_status=$?
    printf '%s\n' "$listing" >&2
    echo "ERROR: upload returned success, but the destination could not be listed." >&2
    return "$command_status"
  fi
  printf '%s\n' "$listing"
  echo "Namespace Files path is now present: $namespace_path"
}

require_history_database_healthy() {
  require_command docker
  local status
  status="$(docker inspect --format '{{.State.Health.Status}}' uwflow-history-db 2>/dev/null || true)"
  if [[ "$status" != "healthy" ]]; then
    echo "ERROR: uwflow-history-db is not healthy (status: ${status:-not found})." >&2
    echo "Run: bash tools/guides/workflow/06-start-history-database.sh" >&2
    exit 1
  fi
}


ensure_history_admin_connection() {
  local status=0
  local answer=""

  if python -m tools.history.database.check_connection; then
    return 0
  else
    status=$?
  fi

  if [[ "$status" -ne 3 ]]; then
    echo "ERROR: historical PostgreSQL credentials could not be verified." >&2
    return "$status"
  fi

  if [[ -f var/operator-state/history-owner-password-reconcile-approved ]]; then
    echo "Applying the owner-password reconciliation approved during Step 04."
    python -m tools.history.database.reconcile_owner_password
    python -m tools.history.database.check_connection
    return 0
  fi

  cat >&2 <<'MESSAGE'

The PostgreSQL container is healthy, but the owner password in .env.history does
not match the password stored in the existing PostgreSQL volume.

The repair changes only the PostgreSQL owner-role login password. It does not
recreate the container, remove the volume, alter schemas, or modify historical
application data.
MESSAGE
  if ! read -r -p "Synchronize the database owner password with .env.history? [y/N] " answer; then
    answer="n"
  fi
  case "${answer,,}" in
    y|yes)
      python -m tools.history.database.reconcile_owner_password
      python -m tools.history.database.check_connection
      ;;
    *)
      echo "No database changes made. Stop here and preserve the existing volume." >&2
      return 1
      ;;
  esac
}

restart_local_kestra_for_history_secret_reload() {
  local container="kestra"
  local container_id=""
  local mounts=""
  local running="false"
  local inspect_attempt

  # Credential recovery can happen before Kestra has ever been started. In
  # that case there is nothing to reload: Step 07 will create the first
  # container with the regenerated .env.history.kestra values.
  if ! docker inspect "$container" >/dev/null 2>&1; then
    if ! docker info >/dev/null 2>&1; then
      echo "ERROR: Docker is unavailable while checking the Kestra container." >&2
      return 1
    fi
    echo "No existing Kestra container found; the new container will start with the regenerated history secrets."
    return 0
  fi

  # Capture a stable container ID. If the container is concurrently removed
  # between the name lookup and this inspection, treat it as already reloaded.
  if ! container_id="$(docker inspect --format '{{.Id}}' "$container" 2>/dev/null)"; then
    if ! docker inspect "$container" >/dev/null 2>&1; then
      echo "The existing Kestra container was removed during the reload check; continuing with a fresh start."
      return 0
    fi
    echo "ERROR: unable to identify the existing Kestra container." >&2
    return 1
  fi

  mounts="$(docker inspect --format '{{range .Mounts}}{{.Name}}|{{.Destination}}{{"\n"}}{{end}}' "$container_id" 2>/dev/null)" || {
    if ! docker inspect "$container_id" >/dev/null 2>&1; then
      echo "The existing Kestra container disappeared during the reload check; continuing with a fresh start."
      return 0
    fi
    echo "ERROR: unable to inspect the existing Kestra container mounts." >&2
    return 1
  }
  if ! grep -Fqx 'kestra_data|/app/storage' <<<"$mounts" || \
     ! grep -Fqx 'kestra_db|/app/data' <<<"$mounts"; then
    echo "ERROR: the existing Kestra container does not use the expected named data volumes." >&2
    echo "It was not stopped or removed. Inspect its mounts before continuing." >&2
    return 1
  fi

  running="$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null)" || {
    if ! docker inspect "$container_id" >/dev/null 2>&1; then
      echo "The existing Kestra container disappeared before it could be stopped; continuing with a fresh start."
      return 0
    fi
    echo "ERROR: unable to read the existing Kestra container state." >&2
    return 1
  }

  echo "Reloading Kestra with the regenerated history secrets."
  if [[ "$running" == "true" ]]; then
    if ! docker stop --time 30 "$container_id" >/dev/null; then
      # Docker's --rm option removes the container object as it stops. Another
      # cleanup process can also remove it between inspect and stop. A missing
      # object is therefore success only after verifying that it is actually
      # gone; other stop failures remain fatal.
      if docker inspect "$container_id" >/dev/null 2>&1; then
        echo "ERROR: Docker could not stop the existing Kestra container." >&2
        return 1
      fi
      echo "The Kestra container was already removed while stopping; continuing with a fresh start."
    fi
  fi

  # docker-run.sh creates Kestra with --rm. A successful stop automatically
  # removes the container object while preserving both named volumes. Wait for
  # that removal before considering a manual container-object cleanup; this
  # avoids racing Docker's automatic removal with a separate `docker rm`.
  for inspect_attempt in $(seq 1 30); do
    if ! docker inspect "$container_id" >/dev/null 2>&1; then
      echo "The previous Kestra container is gone; named data volumes are preserved."
      return 0
    fi
    sleep 0.2
  done

  # A stopped container created without --rm may still exist. Remove only the
  # container object (never -v), and tolerate it disappearing between the
  # final inspect and rm.
  if ! docker rm "$container_id" >/dev/null 2>&1; then
    if docker inspect "$container_id" >/dev/null 2>&1; then
      echo "ERROR: unable to remove the stopped Kestra container object." >&2
      return 1
    fi
  fi

  if docker inspect "$container" >/dev/null 2>&1; then
    echo "ERROR: a Kestra container still occupies the expected name after reload." >&2
    return 1
  fi
  echo "Previous Kestra container removed; both named data volumes are preserved."
}

require_dataset_id() {
  local dataset_id
  dataset_id="$(read_state dataset-id)"
  if [[ -z "$dataset_id" ]]; then
    echo "ERROR: no workflow dataset is selected." >&2
    echo "Run: bash tools/guides/workflow/11-select-or-create-dataset.sh" >&2
    exit 1
  fi
  printf '%s\n' "$dataset_id"
}

require_candidate_id() {
  local candidate_id
  candidate_id="$(read_state candidate-id)"
  if [[ ! "$candidate_id" =~ ^dev-[0-9a-f]{16}$ ]]; then
    echo "ERROR: no valid candidate ID is recorded in var/operator-state." >&2
    echo "Build and verify a candidate in Policy Studio, then record it with workflow step 18." >&2
    echo "For the infrastructure-only no-op control, run Step 11 with UWFLOW_FAST_ROUTE=true." >&2
    exit 1
  fi
  printf '%s\n' "$candidate_id"
}

resolve_baseline_runtime() {
  local release_id="$1"
  local approved="var/releases/approved/${release_id}"
  local core_snapshot="core/kestra/namespace-files/runtime/releases/${release_id}"

  if [[ -e "$approved" ]]; then
    if [[ ! -d "$approved/runtime" || ! -f "$approved/production-flow.yaml" ]]; then
      echo "ERROR: approved release ${release_id} exists but is incomplete. Refusing to use a Core snapshot instead." >&2
      return 1
    fi
    printf '%s\n' "$approved/runtime"
    return 0
  fi
  if [[ -d "$core_snapshot" && -f "$core_snapshot/release-manifest.json" ]]; then
    printf '%s\n' "$core_snapshot"
    return 0
  fi
  echo "ERROR: baseline ${release_id} is neither a complete approved release nor a checked-in Core runtime snapshot." >&2
  return 1
}
