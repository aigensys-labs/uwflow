#!/usr/bin/env bash
set -euo pipefail
source tools/guides/workflow/lib/common.sh
require_repository_root
require_command git

for required in README.md LICENSE pyproject.toml; do
  [[ -f "$required" ]] || { echo "ERROR: expected project file is missing: $required" >&2; exit 1; }
done

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git init -b main
fi

for secret in .env .env.history .env.history.kestra; do
  if git ls-files --error-unmatch "$secret" >/dev/null 2>&1; then
    echo "ERROR: $secret is already tracked by Git. Remove it from the index and review history before publishing." >&2
    exit 1
  fi
  if [[ -e "$secret" ]] && ! git check-ignore -q --no-index "$secret"; then
    echo "ERROR: $secret is not ignored by Git. Refusing to stage a potentially sensitive file." >&2
    exit 1
  fi
done

branch="$(git branch --show-current)"
if [[ "$branch" != "main" ]]; then
  echo "ERROR: current branch is '$branch', expected 'main'. Review the existing repository before continuing." >&2
  exit 1
fi

current_remote=""
if git remote get-url origin >/dev/null 2>&1; then
  current_remote="$(git remote get-url origin)"
fi
read -r -p "GitHub repository URL (leave blank to keep ${current_remote:-unset}): " remote_url
remote_url="${remote_url:-$current_remote}"
if [[ -z "$remote_url" ]]; then
  echo "ERROR: an origin URL is required before publishing." >&2
  exit 1
fi

if [[ -n "$current_remote" && "$remote_url" != "$current_remote" ]]; then
  read -r -p "Replace origin URL '$current_remote' with '$remote_url'? [y/N] " answer
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "Cancelled; existing origin was not changed."
    exit 0
  fi
  git remote set-url origin "$remote_url"
elif [[ -z "$current_remote" ]]; then
  git remote add origin "$remote_url"
fi

git add --all
printf '\n== Files staged for the initial repository commit ==\n'
git diff --cached --stat
if ! git diff --cached --quiet; then
  read -r -p 'Commit the staged repository contents? Review the list above first [y/N] ' answer
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    echo "Staged files were left untouched. Review them with 'git status' and rerun this script."
    exit 0
  fi
  git commit -m "Initial UWflow governed Kestra underwriting demo"
elif ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "ERROR: there is no commit to publish. Stage and commit the reviewed files, then rerun." >&2
  exit 1
else
  echo "No staged changes; keeping the existing commit history."
fi

read -r -p "Push branch main to $remote_url now? [y/N] " answer
if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
  git push -u origin main
else
  echo "Local Git repository is ready. Push later with 'git push -u origin main'."
fi
