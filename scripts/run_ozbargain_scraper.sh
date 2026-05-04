#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

if [[ -z "${RESEND_API_KEY:-}" ]]; then
  echo "CRITICAL ERROR: RESEND_API_KEY is not set. Script aborted." >&2
  exit 1
fi

python3 -m venv .venv

REQUIREMENTS_HASH="$(shasum -a 256 requirements.txt | awk '{print $1}')"
REQUIREMENTS_STAMP=".venv/.requirements.sha256"

if [[ ! -f "$REQUIREMENTS_STAMP" ]] || [[ "$(cat "$REQUIREMENTS_STAMP")" != "$REQUIREMENTS_HASH" ]]; then
  .venv/bin/python -m pip install -r requirements.txt
  printf "%s\n" "$REQUIREMENTS_HASH" > "$REQUIREMENTS_STAMP"
fi

export URL="${URL:-https://www.ozbargain.com.au/search/node/gaming%20pc%20option%3Anoexpired%2Ctitleonly%20category%3A12#}"
export LAST_POSTS_FILE="${LAST_POSTS_FILE:-data/posts/gaming_pc.csv}"
export SENDER_EMAIL="${SENDER_EMAIL:-ozbargain-alerts@notifications.legalcents.com.au}"
export RECIPIENT_EMAIL="${RECIPIENT_EMAIL:-joe@legalcents.com.au}"
export TITLE="${TITLE:-Gaming PC Deals}"

exec .venv/bin/python alert_on_new_posts.py
