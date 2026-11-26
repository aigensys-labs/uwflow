#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command curl
add_user_bin_to_path

if ! command -v kestractl >/dev/null 2>&1; then
  cat <<'MESSAGE'
The Kestra CLI (kestractl) is required for server-side flow validation,
Namespace Files publication and DEV flow deployment.
MESSAGE
  read -r -p "Install kestractl from the official Kestra installer now? [y/N] " install_answer || install_answer="n"
  case "${install_answer,,}" in
    y|yes)
      ;;
    *)
      echo "kestractl was not installed. No later deployment step can run without it." >&2
      echo "Install it manually, then rerun this command." >&2
      exit 2
      ;;
  esac

  if [[ -w /usr/local/bin ]]; then
    INSTALL_DIR=/usr/local/bin
  else
    INSTALL_DIR="$HOME/.local/bin"
    mkdir -p "$INSTALL_DIR"
  fi
  curl -fsSL https://raw.githubusercontent.com/kestra-io/kestractl/main/install-scripts/install.sh | INSTALL_DIR="$INSTALL_DIR" bash
fi

add_user_bin_to_path
require_command kestractl
kestractl --help >/dev/null
echo "kestractl is installed and executable. Deployment scripts load local credentials from .env."
