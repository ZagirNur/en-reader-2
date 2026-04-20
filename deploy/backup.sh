#!/usr/bin/env bash
# en-reader daily SQLite backup (M14.4).
#
# Produces a consistent snapshot via SQLite's ``VACUUM INTO`` (atomic, safe
# while the app is writing), bundles it with ``data/.secret_key`` so the
# restore never invalidates live sessions, gzips, and pushes to the
# rclone remote. Old backups are pruned after RETENTION_DAYS.
#
# Requires rclone configured with a remote named "hetzner" pointing at an
# S3-compatible bucket (see deploy/README.md for the `rclone config` walk-
# through). Triggered by en-reader-backup.timer at 04:00 UTC daily.

set -euo pipefail

APP_HOME="${APP_HOME:-/opt/en-reader}"
APP_USER="${APP_USER:-enreader}"
BACKUP_DIR="/tmp/en-reader-backup"
REMOTE="${BACKUP_REMOTE:-hetzner:en-reader-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

DATE=$(date -u +%Y-%m-%dT%H-%M-%SZ)
ARCHIVE="en-reader-${DATE}.tar.gz"

mkdir -p "$BACKUP_DIR"
rm -rf "$BACKUP_DIR/stage"
mkdir -p "$BACKUP_DIR/stage"

# 1. Consistent SQLite snapshot. VACUUM INTO is atomic and doesn't block
#    writers; the target file must not exist beforehand.
sudo -u "$APP_USER" "$APP_HOME/.venv/bin/python" - <<PY
import sqlite3
from pathlib import Path
src = "$APP_HOME/data/en-reader.db"
dst = "$BACKUP_DIR/stage/en-reader.db"
Path(dst).unlink(missing_ok=True)
conn = sqlite3.connect(src)
conn.execute(f"VACUUM INTO '{dst}'")
conn.close()
PY

# 2. Include the session signing key so restore doesn't log everyone out.
if [ -f "$APP_HOME/data/.secret_key" ]; then
  install -m 0600 "$APP_HOME/data/.secret_key" "$BACKUP_DIR/stage/.secret_key"
fi

# 3. Bundle + compress.
tar -C "$BACKUP_DIR/stage" -czf "$BACKUP_DIR/$ARCHIVE" .

# 4. Upload and drop the local copy.
rclone copy "$BACKUP_DIR/$ARCHIVE" "$REMOTE/"
rm -rf "$BACKUP_DIR/stage" "$BACKUP_DIR/$ARCHIVE"

# 5. Retention — rclone drops remote objects older than RETENTION_DAYS.
rclone delete "$REMOTE/" --min-age "${RETENTION_DAYS}d"

echo "[backup] uploaded $ARCHIVE (retention ${RETENTION_DAYS}d)"
