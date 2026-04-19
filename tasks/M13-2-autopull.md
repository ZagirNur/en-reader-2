# Задача M13.2 — Autopull-пайплайн

**Размер.** M (~2 дня)
**Зависимости.** M13.1.
**Что строится поверх.** M13.3 (Telegram после autopull).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Нужен простой CD: `git push main` → через ≤ 30 с прод обновлён. Без GitHub Actions runner'а на VPS, без Kubernetes. Простой systemd-timer, который каждые 10 секунд дёргает скрипт.

Скрипт должен быть **self-healing**: если поменялся `pyproject.toml` — переустановить зависимости; если поменялся сам systemd-юнит в репозитории — подменить файл на `/etc/systemd/system/` и `daemon-reload`; затем рестарт сервиса.

И **тишина по умолчанию**: если `git pull` ничего не подтянул — скрипт ничего не делает. Без этого Telegram-notify (M13.3) будет спамить.

---

## Что нужно сделать

`deploy/autopull.sh`, `deploy/en-reader-autopull.service`, `deploy/en-reader-autopull.timer`.

---

## Что входит

### 1. `deploy/autopull.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_HOME="/opt/en-reader"
LOCK_FILE="/tmp/en-reader-autopull.lock"

# 1. Lock — не запускать параллельно.
exec 200>"$LOCK_FILE"
flock -n 200 || exit 0

cd "$APP_HOME"

# 2. fetch — тихо.
sudo -u enreader git fetch origin main --quiet

BEFORE=$(sudo -u enreader git rev-parse HEAD)
AFTER=$(sudo -u enreader git rev-parse origin/main)

if [ "$BEFORE" = "$AFTER" ]; then
  exit 0   # ничего нового
fi

echo "[autopull] updating from $BEFORE to $AFTER"

# 3. pull.
sudo -u enreader git merge --ff-only origin/main

# 4. pyproject изменился — переустановить deps.
if sudo -u enreader git diff --name-only "$BEFORE" "$AFTER" | grep -q "pyproject.toml"; then
  echo "[autopull] pyproject changed — reinstalling deps"
  sudo -u enreader "$APP_HOME/.venv/bin/pip" install -e "$APP_HOME"
fi

# 5. systemd-unit изменился — подменить.
if ! cmp -s "$APP_HOME/deploy/en-reader.service" /etc/systemd/system/en-reader.service; then
  echo "[autopull] service unit changed — reinstalling"
  cp "$APP_HOME/deploy/en-reader.service" /etc/systemd/system/en-reader.service
  systemctl daemon-reload
fi

# 6. Рестарт.
systemctl restart en-reader

# 7. Статус в stdout (для journalctl).
echo "[autopull] deployed $AFTER"

# 8. Экспортировать для notify (M13.3 прочитает переменную).
echo "$AFTER" > /tmp/en-reader-last-deploy.txt
```

Права: `chmod +x deploy/autopull.sh`, владелец root.

### 2. `deploy/en-reader-autopull.service`

```ini
[Unit]
Description=en-reader autopull
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/en-reader/deploy/autopull.sh
User=root
```

Root — потому что надо `systemctl daemon-reload` и `restart`. Git-операции внутри скрипта делает `sudo -u enreader`.

### 3. `deploy/en-reader-autopull.timer`

```ini
[Unit]
Description=en-reader autopull timer

[Timer]
OnBootSec=30
OnUnitActiveSec=10
Unit=en-reader-autopull.service

[Install]
WantedBy=timers.target
```

### 4. Обновление `bootstrap.sh`

Добавить в секцию «7. systemd»:
```bash
cp "$APP_HOME/deploy/en-reader-autopull.service" /etc/systemd/system/
cp "$APP_HOME/deploy/en-reader-autopull.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable en-reader-autopull.timer
systemctl start en-reader-autopull.timer
```

### 5. Проверка

- Коммит в main → через ≤ 30 с в `journalctl -u en-reader-autopull` видно «deployed <sha>».
- `curl http://<ip>/` возвращает обновлённый фронт.
- Подряд два pull без изменений: второй — ни одной строки в журнале (тишина).
- Изменение `deploy/en-reader.service` в main → после pull systemd daemon-reload отрабатывает, сервис рестартует.
- Изменение `pyproject.toml` с добавлением зависимости → autopull её ставит.

---

## Технические детали и ловушки

- **flock** предотвращает наложение запусков. Если один прогон медленный (pip install), второй пропустит свой тик.
- **--ff-only** защищает от случайных merge-коммитов при локальных изменениях (которых не должно быть, но лучше явно).
- **cmp -s** тихая проверка равенства файлов.
- **Root в autopull**. Альтернатива — дать `enreader` право на `systemctl restart en-reader` через `/etc/sudoers.d/`. Но root проще для MVP.
- **Локальные изменения в репо на VPS**. Их быть не должно. Если есть — `git pull --ff-only` упадёт; это ок, пусть лучше упадёт, чем тихо сделать merge.
- **uvicorn downtime при restart** — несколько секунд. На MVP приемлемо. Для zero-downtime нужен nginx + два воркера, это overkill.

---

## Acceptance

- [ ] `systemctl list-timers` показывает autopull.timer (каждые 10 с).
- [ ] Push в main → через ≤ 30 с новая версия на проде.
- [ ] No-op pull — тишина в journal.
- [ ] pyproject.toml изменился — pip install применился.
- [ ] systemd-unit в репозитории изменился — автоматически подхватился.
- [ ] Документация в `deploy/README.md` обновлена.

---

## Что сдавать

- Ветка `task/M13-2-autopull`, PR в main.

---

## Что НЕ делать

- Не используй GitHub Actions runner on-VPS.
- Не реализуй rollback — MVP.
- Не notify в этой задаче (M13.3).
- Не TLS в этой задаче (M13.4).
