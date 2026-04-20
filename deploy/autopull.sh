#!/usr/bin/env bash
# en-reader autopull (M13.2).
#
# Triggered by en-reader-autopull.timer every ~10s. Silent when origin/main
# hasn't moved (so M13.3's Telegram notify doesn't spam). On a new commit:
# pulls, re-installs deps if pyproject.toml changed, replaces the systemd
# unit if it changed, and restarts the service. Last deployed SHA is
# written to /tmp/en-reader-last-deploy.txt for M13.3 to pick up.

set -euo pipefail

APP_HOME="${APP_HOME:-/opt/en-reader}"
APP_USER="${APP_USER:-enreader}"
BRANCH="${BRANCH:-main}"
LOCK_FILE="/tmp/en-reader-autopull.lock"
LAST_DEPLOY_FILE="/tmp/en-reader-last-deploy.txt"

# M13.3: Telegram notify. `_updating` flips to 1 only after we've seen a
# real SHA change — so the ERR trap stays silent on pre-update failures
# (e.g. flock contention, fetch against an unreachable origin), and only
# fires when a deploy actually started.
_updating=0

notify_failure() {
  if [ "$_updating" = "0" ]; then
    return
  fi
  local sha
  sha=$(cd "$APP_HOME" && sudo -u "$APP_USER" git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  "$APP_HOME/deploy/notify.sh" "failed deploy at $sha" || true
}
trap notify_failure ERR

# 1. flock so slow pip installs don't overlap with the next tick.
exec 200>"$LOCK_FILE"
flock -n 200 || exit 0

cd "$APP_HOME"

# 2. Fetch quietly and compare SHAs. If nothing moved → silent exit.
sudo -u "$APP_USER" git fetch origin "$BRANCH" --quiet

BEFORE=$(sudo -u "$APP_USER" git rev-parse HEAD)
AFTER=$(sudo -u "$APP_USER" git rev-parse "origin/$BRANCH")

if [ "$BEFORE" = "$AFTER" ]; then
  exit 0
fi

_updating=1
echo "[autopull] updating from ${BEFORE:0:12} to ${AFTER:0:12}"

# 3. Fast-forward only — if there are local edits on the VPS, fail loudly
#    instead of silently merging.
sudo -u "$APP_USER" git merge --ff-only "origin/$BRANCH"

# Collect changed files for conditional reinstall / unit-swap.
CHANGED=$(sudo -u "$APP_USER" git diff --name-only "$BEFORE" "$AFTER")

# 4. pyproject.toml changed → reinstall the venv so new deps land.
if echo "$CHANGED" | grep -qx "pyproject.toml"; then
  echo "[autopull] pyproject.toml changed — reinstalling deps"
  sudo -u "$APP_USER" "$APP_HOME/.venv/bin/pip" install --upgrade pip >/dev/null
  sudo -u "$APP_USER" "$APP_HOME/.venv/bin/pip" install -e "$APP_HOME"
fi

# 5. systemd unit(s) changed → refresh from the repo + daemon-reload.
reload_systemd=0
for unit in en-reader.service en-reader-autopull.service en-reader-autopull.timer; do
  src="$APP_HOME/deploy/$unit"
  dst="/etc/systemd/system/$unit"
  if [ -f "$src" ] && ! cmp -s "$src" "$dst"; then
    echo "[autopull] $unit changed — reinstalling"
    install -m 0644 "$src" "$dst"
    reload_systemd=1
  fi
done
if [ "$reload_systemd" = "1" ]; then
  systemctl daemon-reload
fi

# 5a. Caddyfile (M17.6) — reverse-proxy config lives in the repo so a
#     pure push-to-main can swap "auto HTTPS" for "plain HTTP behind
#     Cloudflare" without a manual SSH session. Reload, don't restart,
#     so in-flight requests don't drop.
if [ -f "$APP_HOME/deploy/Caddyfile" ] && \
   ! cmp -s "$APP_HOME/deploy/Caddyfile" /etc/caddy/Caddyfile; then
  echo "[autopull] Caddyfile changed — reinstalling"
  install -m 0644 "$APP_HOME/deploy/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
fi

# 6. Restart the app. Uvicorn downtime is a few seconds — acceptable on MVP.
systemctl restart en-reader

# 7. Record the new SHA and ping Telegram on success.
echo "$AFTER" > "$LAST_DEPLOY_FILE"
SHORT_SHA=$(sudo -u "$APP_USER" git rev-parse --short HEAD)
echo "[autopull] deployed $AFTER"
"$APP_HOME/deploy/notify.sh" "deployed $SHORT_SHA" || true
