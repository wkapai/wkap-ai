#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${WKAP_LEDGER_DEPLOY_KEY_BASE64:-}" ]]; then
  mkdir -p "$HOME/.ssh"
  printf '%s' "$WKAP_LEDGER_DEPLOY_KEY_BASE64" | base64 -d > "$HOME/.ssh/wkap_ledger_deploy_key"
  chmod 600 "$HOME/.ssh/wkap_ledger_deploy_key"
  ssh-keyscan github.com >> "$HOME/.ssh/known_hosts"
  export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/wkap_ledger_deploy_key -o IdentitiesOnly=yes"
fi

if [[ -n "${WKAP_LEDGER_REPO_PATH:-}" && -n "${WKAP_LEDGER_REPO_URL:-}" ]]; then
  mkdir -p "$(dirname "$WKAP_LEDGER_REPO_PATH")"
  if [[ -d "$WKAP_LEDGER_REPO_PATH/.git" ]]; then
    git -C "$WKAP_LEDGER_REPO_PATH" fetch origin "${WKAP_LEDGER_BRANCH:-main}"
    git -C "$WKAP_LEDGER_REPO_PATH" checkout "${WKAP_LEDGER_BRANCH:-main}"
    git -C "$WKAP_LEDGER_REPO_PATH" pull --ff-only origin "${WKAP_LEDGER_BRANCH:-main}"
  else
    rm -rf "$WKAP_LEDGER_REPO_PATH"
    git clone --branch "${WKAP_LEDGER_BRANCH:-main}" "$WKAP_LEDGER_REPO_URL" "$WKAP_LEDGER_REPO_PATH"
  fi
  git -C "$WKAP_LEDGER_REPO_PATH" config user.name "${WKAP_GIT_USER_NAME:-WKAP Ledger Bot}"
  git -C "$WKAP_LEDGER_REPO_PATH" config user.email "${WKAP_GIT_USER_EMAIL:-ledger@wkap.ai}"
fi

python manage.py migrate --noinput
python manage.py check --deploy
python manage.py wkap --json environment-check
python manage.py wkap --json rebuild-indexes
python manage.py wkap --json validate-all
