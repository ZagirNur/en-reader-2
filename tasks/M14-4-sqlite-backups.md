# Задача M14.4 — Ежедневные бэкапы SQLite

**Размер.** S (~1 день)
**Зависимости.** M13.1.
**Что строится поверх.** Data safety.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Все данные — один SQLite-файл. Потерять его = потерять всех пользователей, их библиотеки и словари. Решение: ежедневный автоматический бэкап в внешнее хранилище, с ротацией.

Варианты хранилища:
- S3-compatible (Hetzner Object Storage, Backblaze B2) + rclone.
- rsync на удалённый сервер.
- GitHub-Release (плохо для больших файлов).

Выбираем **rclone → Hetzner Storage** (недорого, надёжно).

---

## Что нужно сделать

`deploy/backup.sh`, systemd-timer, retention, documented restore.

---

## Что входит

### 1. rclone конфиг

На VPS:
```bash
apt install -y rclone
rclone config
# создать remote "hetzner" типа S3 с endpoint Hetzner Object Storage,
# key/secret из Hetzner консоли.
```

Документировать процедуру в `deploy/README.md`.

### 2. `deploy/backup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_HOME="/opt/en-reader"
BACKUP_DIR="/tmp/en-reader-backup"
REMOTE="hetzner:en-reader-backups"
RETENTION_DAYS=30

DATE=$(date -u +%Y-%m-%dT%H-%M-%SZ)
FILE="en-reader-${DATE}.db.gz"

mkdir -p "$BACKUP_DIR"

# 1. Безопасный снимок SQLite (VACUUM INTO — атомарно).
sudo -u enreader "$APP_HOME/.venv/bin/python" -c "
import sqlite3
c = sqlite3.connect('$APP_HOME/data/en-reader.db')
c.execute(\"VACUUM INTO '/tmp/en-reader-backup/en-reader-snapshot.db'\")
c.close()
"

# 2. gzip.
gzip -f "/tmp/en-reader-backup/en-reader-snapshot.db"
mv "/tmp/en-reader-backup/en-reader-snapshot.db.gz" "/tmp/en-reader-backup/$FILE"

# 3. Upload.
rclone copy "$BACKUP_DIR/$FILE" "$REMOTE/"

# 4. Local cleanup.
rm "$BACKUP_DIR/$FILE"

# 5. Remote retention.
rclone delete "$REMOTE/" --min-age "${RETENTION_DAYS}d"

echo "[backup] uploaded $FILE"
```

### 3. systemd-timer

`/etc/systemd/system/en-reader-backup.service`:
```ini
[Unit]
Description=en-reader SQLite backup

[Service]
Type=oneshot
ExecStart=/opt/en-reader/deploy/backup.sh
User=root
```

`/etc/systemd/system/en-reader-backup.timer`:
```ini
[Unit]
Description=Daily en-reader backup

[Timer]
OnCalendar=*-*-* 04:00:00 UTC
Persistent=true
Unit=en-reader-backup.service

[Install]
WantedBy=timers.target
```

`Persistent=true` — если VPS был выключен и пропустил 04:00, после включения сработает.

### 4. Установка

В `bootstrap.sh`:
```bash
apt install -y rclone
cp "$APP_HOME/deploy/en-reader-backup.service" /etc/systemd/system/
cp "$APP_HOME/deploy/en-reader-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable en-reader-backup.timer
systemctl start en-reader-backup.timer
```

### 5. Restore script

`deploy/restore.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_NAME="${1:?usage: restore.sh en-reader-YYYY-MM-DDTHH-MM-SSZ.db.gz}"
APP_HOME="/opt/en-reader"
REMOTE="hetzner:en-reader-backups"

echo "Stopping en-reader..."
systemctl stop en-reader

rclone copy "$REMOTE/$BACKUP_NAME" /tmp/
gunzip -f "/tmp/$BACKUP_NAME"

DB_NAME="${BACKUP_NAME%.gz}"
cp "$APP_HOME/data/en-reader.db" "$APP_HOME/data/en-reader.db.before-restore"
cp "/tmp/$DB_NAME" "$APP_HOME/data/en-reader.db"
chown enreader:enreader "$APP_HOME/data/en-reader.db"

systemctl start en-reader
echo "Restored from $BACKUP_NAME. Old DB at en-reader.db.before-restore"
```

### 6. Документация

`deploy/README.md` секция «Backups»:
```markdown
## Backups

Daily snapshot uploaded to Hetzner Object Storage at 04:00 UTC.
Retention: 30 days.

List backups: `rclone ls hetzner:en-reader-backups/`

Restore: `./deploy/restore.sh en-reader-2026-04-19T04-00-00Z.db.gz`
```

### 7. Ручная проверка

- Запустить `backup.sh` вручную → в remote появился файл.
- Проверить размер в rclone.
- Остановить en-reader, восстановить на тестовой VM → приложение поднимается.

---

## Технические детали и ловушки

- **`VACUUM INTO`** — SQLite-native способ сделать консистентный снимок при работающем приложении. Быстрый, атомарный, не блокирует писателей.
- **gzip** уменьшает ~10x (tokens_gz уже сжатые, books-мета сжимается хорошо).
- **rclone retention**. `rclone delete --min-age 30d` удаляет файлы старше 30 дней. Работает с S3-remote.
- **Перед тестовым restore**. Создай отдельную VM, не трогай прод. SQLite не умеет atomic swap в живой системе без stop.
- **Секреты rclone**. В `~/.config/rclone/rclone.conf` (root). Пароль к S3 там plain-text. Держи VPS защищённо.

---

## Acceptance

- [ ] `backup.sh` вручную работает, файл появляется в remote.
- [ ] `systemctl list-timers` показывает backup.timer.
- [ ] В 04:00 UTC прошёл автоматический бэкап (проверить через 24 ч).
- [ ] Retention удаляет старше 30 дней.
- [ ] `restore.sh` восстанавливает на тестовой VM.
- [ ] Документация в `deploy/README.md`.

---

## Что сдавать

- Ветка `task/M14-4-sqlite-backups`, PR в main.
- Скриншот списка файлов в remote — в описании.

---

## Что НЕ делать

- Не шифруй ДБ дополнительно (rclone поверх HTTPS достаточно).
- Не бэкапь `data/covers/` отдельно — для MVP они воссоздаваемы из parsers.
- Не храни SECRET_KEY в бэкапе (он отдельно, он в `data/.secret_key`). На самом деле — положи его рядом: без него все сессии отвалятся при restore. Добавь `data/.secret_key` в бэкап-tar.
