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

# 6. Restart the app. Uvicorn downtime is a few seconds — acceptable on MVP.
systemctl restart en-reader

# 7. Record the new SHA so M13.3 can notify.
echo "$AFTER" > "$LAST_DEPLOY_FILE"
echo "[autopull] deployed $AFTER"
