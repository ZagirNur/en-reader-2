#!/usr/bin/env bash
# en-reader restore (M14.4).
#
# Usage: restore.sh en-reader-YYYY-MM-DDTHH-MM-SSZ.tar.gz
#
# Downloads the archive from the rclone remote, stops the service, backs
# up the current DB to `.before-restore`, restores DB + signing key, fixes
# ownership, and brings the service back up. Test on a fresh VM first —
# this is destructive on the live DB.

set -euo pipefail

BACKUP_NAME="${1:?usage: restore.sh en-reader-YYYY-MM-DDTHH-MM-SSZ.tar.gz}"
APP_HOME="${APP_HOME:-/opt/en-reader}"
APP_USER="${APP_USER:-enreader}"
REMOTE="${BACKUP_REMOTE:-hetzner:en-reader-backups}"
STAGE="/tmp/en-reader-restore"

rm -rf "$STAGE"
mkdir -p "$STAGE"

echo "[restore] downloading $BACKUP_NAME"
rclone copy "$REMOTE/$BACKUP_NAME" "$STAGE/"
tar -C "$STAGE" -xzf "$STAGE/$BACKUP_NAME"

if [ ! -f "$STAGE/en-reader.db" ]; then
  echo "[restore] archive missing en-reader.db — aborting" >&2
  exit 1
fi

echo "[restore] stopping en-reader"
systemctl stop en-reader

# Keep the pre-restore DB alongside for a one-line rollback.
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
if [ -f "$APP_HOME/data/en-reader.db" ]; then
  cp "$APP_HOME/data/en-reader.db" \
    "$APP_HOME/data/en-reader.db.before-restore-${TIMESTAMP}"
fi

install -m 0644 -o "$APP_USER" -g "$APP_USER" \
  "$STAGE/en-reader.db" "$APP_HOME/data/en-reader.db"
if [ -f "$STAGE/.secret_key" ]; then
  install -m 0600 -o "$APP_USER" -g "$APP_USER" \
    "$STAGE/.secret_key" "$APP_HOME/data/.secret_key"
fi

systemctl start en-reader
echo "[restore] done. Previous DB saved as en-reader.db.before-restore-${TIMESTAMP}"
