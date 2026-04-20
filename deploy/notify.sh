#!/usr/bin/env bash
# en-reader Telegram deploy notify (M13.3).
#
# Usage: notify.sh <message>
#
# Reads TG_BOT_TOKEN / TG_CHAT_ID from /opt/en-reader/.env (if readable) or
# environment. If both are set, POSTs the message to Telegram's sendMessage
# API with a 10s timeout. Any failure (missing creds, network, Telegram
# down) is swallowed so autopull is never blocked by notification.

set -u  # do NOT use -e — a failed curl should not turn into a script exit.

MESSAGE="${1:-deployed}"

if [ -f /opt/en-reader/.env ] && [ -r /opt/en-reader/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source /opt/en-reader/.env
  set +a
fi

# Optional hardcoded fallback for the team-lead bot. Empty by default so a
# fresh clone stays silent until creds are provisioned.
TG_BOT_TOKEN="${TG_BOT_TOKEN:-}"
TG_CHAT_ID="${TG_CHAT_ID:-}"

if [ -z "$TG_BOT_TOKEN" ] || [ -z "$TG_CHAT_ID" ]; then
  exit 0
fi

curl --silent --show-error --max-time 10 \
  -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}" \
  >/dev/null 2>&1 || true
