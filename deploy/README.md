# Deploy en-reader

One-box deployment: Ubuntu 22.04+ / ARM or x86, systemd, uvicorn listening
directly on :80 via `CAP_NET_BIND_SERVICE`. No nginx, no Docker.

## First run

On a fresh VM as root:

```
curl -fsSL https://raw.githubusercontent.com/ZagirNur/en-reader-2/main/deploy/bootstrap.sh \
  | sudo bash
```

or, if you already ssh-cloned the repo:

```
sudo ./deploy/bootstrap.sh
```

The script:

1. Installs `python3.11`, `git`, `ufw`.
2. Creates the system user `enreader` with home `/opt/en-reader`.
3. Clones (or pulls) the repo into `/opt/en-reader`.
4. Creates the venv and `pip install -e .` (this pulls the pinned spaCy
   model wheel, no separate `spacy download` step needed).
5. Writes a first-time `/opt/en-reader/.env` with `GEMINI_API_KEY=SET_ME`.
6. Installs and enables the `en-reader.service` systemd unit.
7. Opens :22 and :80 on `ufw`, then enables the firewall.

After the first run:

1. Edit `/opt/en-reader/.env` and set `GEMINI_API_KEY=<real key>`.
2. `sudo systemctl restart en-reader`.
3. Open `http://<this-host>/` in a browser — login screen should load.

Re-running `bootstrap.sh` is safe — existing `.env` is never overwritten
and the user is created only if missing.

## Day-to-day

```
# logs (follow)
sudo journalctl -u en-reader -f

# status
sudo systemctl status en-reader

# restart
sudo systemctl restart en-reader

# pull latest code manually (autopull lands in M13.2)
sudo -u enreader -H bash -c 'cd /opt/en-reader && git pull --ff-only'
sudo systemctl restart en-reader
```

## Files created by the bootstrap

| Path | Purpose |
|---|---|
| `/opt/en-reader/` | Repo checkout, owned by `enreader` |
| `/opt/en-reader/.venv/` | Python venv |
| `/opt/en-reader/.env` | Secrets (`GEMINI_API_KEY`, `ENV=prod`). `chmod 600`. |
| `/opt/en-reader/data/en-reader.db` | SQLite DB (plus `-wal`/`-shm` sidecars) |
| `/opt/en-reader/data/covers/` | Book cover files persisted by uploads |
| `/opt/en-reader/data/.secret_key` | Session-cookie signing key, 0o600 |
| `/etc/systemd/system/en-reader.service` | Service unit |

## Troubleshooting

- **Port 80 in use**: another process is listening. `sudo ss -lntp | grep :80`.
- **`en-reader` won't start**: `sudo journalctl -u en-reader -n 100`.
  Common cause: missing `GEMINI_API_KEY` — first real translate call will
  still serve a 502, not a boot failure.
- **Locked out of SSH after ufw**: the bootstrap explicitly opens :22 before
  enabling ufw. If you still lose access, use the hosting provider's web
  console to run `sudo ufw disable`.

## Autopull (M13.2)

Installed by `bootstrap.sh` automatically. A systemd timer runs
`deploy/autopull.sh` every ~10 s (30 s after boot). The script is silent
when `origin/main` hasn't moved and only logs to journal on real deploys.

On a new commit it:

1. `git fetch` → diff HEAD vs `origin/main`; exit 0 if equal.
2. `git merge --ff-only` (fails loudly on local edits — there shouldn't be
   any on the VPS).
3. If `pyproject.toml` changed: `pip install -e .` inside the venv.
4. If any of `en-reader.service`, `en-reader-autopull.service`,
   `en-reader-autopull.timer` changed: copy to `/etc/systemd/system/` and
   `systemctl daemon-reload`.
5. `systemctl restart en-reader`.
6. Writes the new SHA to `/tmp/en-reader-last-deploy.txt` (consumed by
   M13.3's Telegram notify).

Watch the timer and recent runs:

```
systemctl list-timers en-reader-autopull.timer
journalctl -u en-reader-autopull -n 50
```

To pause autopull while debugging on the box:

```
sudo systemctl stop en-reader-autopull.timer
# ... poke around ...
sudo systemctl start en-reader-autopull.timer
```

## Telegram notify (M13.3)

Autopull pings Telegram after every real deploy. Set `TG_BOT_TOKEN` and
`TG_CHAT_ID` in `/opt/en-reader/.env` (see `.env.example`); leave them
empty to keep the notifier silent.

Messages:

- `deployed a1b2c3d4` — fast-forward succeeded and the service restarted.
- `failed deploy at a1b2c3d4` — something after the SHA check raised under
  `set -e` (pip install, systemd reload, restart). Fires exactly once per
  broken deploy, never on no-op runs.

Test manually:

```
sudo TG_BOT_TOKEN=... TG_CHAT_ID=... \
  /opt/en-reader/deploy/notify.sh "hello from $(hostname)"
```

A curl timeout or missing creds are swallowed — notify never blocks
autopull longer than 10 s and never fails the deploy on a Telegram outage.

## Scope

- **M13.4** — Let's Encrypt TLS termination in front of uvicorn (or on :443
  with the same capability trick).
