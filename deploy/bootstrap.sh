#!/usr/bin/env bash
# en-reader VPS bootstrap (M13.1).
#
# Idempotent: safe to re-run. Installs system packages, creates the
# unprivileged `enreader` user, clones/pulls the repo into /opt/en-reader,
# sets up a Python 3.11 venv, writes a .env template on first run, installs
# the systemd unit, and opens the firewall on :22 + :80.
#
# Usage on a fresh Ubuntu 22.04+:
#   sudo ./deploy/bootstrap.sh
# or remotely via curl (see deploy/README.md).

set -euo pipefail

APP_USER="${APP_USER:-enreader}"
APP_HOME="${APP_HOME:-/opt/en-reader}"
REPO_URL="${REPO_URL:-https://github.com/ZagirNur/en-reader-2.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"

if [[ $EUID -ne 0 ]]; then
  echo "bootstrap.sh must run as root (use sudo)" >&2
  exit 1
fi

# 1. Packages.
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3.11 python3.11-venv python3-pip git ufw ca-certificates curl

# 2. Unprivileged service user.
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --shell /bin/bash --home "$APP_HOME" "$APP_USER"
fi
mkdir -p "$APP_HOME"
chown -R "$APP_USER:$APP_USER" "$APP_HOME"

# 3. Repo (clone or pull).
sudo -u "$APP_USER" bash -c "
  set -euo pipefail
  cd '$APP_HOME'
  if [ ! -d .git ]; then
    git clone --branch '$REPO_BRANCH' '$REPO_URL' .
  else
    git fetch --prune
    git checkout '$REPO_BRANCH'
    git pull --ff-only
  fi
"

# 4. venv + deps + spaCy model. `pip install -e .` pulls the model wheel
#    pinned in pyproject.toml, so a separate `python -m spacy download` is
#    not needed (that step was retired in M1.5).
sudo -u "$APP_USER" bash -c "
  set -euo pipefail
  cd '$APP_HOME'
  if [ ! -d .venv ]; then
    python3.11 -m venv .venv
  fi
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -e .
"

# 5. Writable data dirs (covers + SQLite).
sudo -u "$APP_USER" mkdir -p "$APP_HOME/data" "$APP_HOME/data/covers"

# 6. .env seeded on first run only — never overwrite existing secrets.
if [ ! -f "$APP_HOME/.env" ]; then
  cat > "$APP_HOME/.env" <<'EOF'
GEMINI_API_KEY=SET_ME
GEMINI_MODEL=gemini-2.5-flash-lite
ENV=prod
EOF
  chown "$APP_USER:$APP_USER" "$APP_HOME/.env"
  chmod 600 "$APP_HOME/.env"
fi

# 7. systemd unit.
install -m 0644 "$APP_HOME/deploy/en-reader.service" \
  /etc/systemd/system/en-reader.service
systemctl daemon-reload
systemctl enable en-reader
systemctl restart en-reader

# 8. Firewall — SSH must go up BEFORE enabling ufw or we lock ourselves out.
ufw allow 22/tcp
ufw allow 80/tcp
ufw --force enable

cat <<EOF

Bootstrap OK.

Next steps:
  1. Edit $APP_HOME/.env and set GEMINI_API_KEY=<your key>.
  2. sudo systemctl restart en-reader
  3. Open http://<this-host>/ — you should see the login screen.

Logs:    journalctl -u en-reader -f
Status:  systemctl status en-reader
EOF
