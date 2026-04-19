# Задача M13.1 — VPS bootstrap + systemd + :80

**Размер.** M (~2 дня)
**Зависимости.** M11.3 (готов работающий продукт).
**Что строится поверх.** M13.2 (autopull), M13.3 (Telegram notify), M13.4 (TLS).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Продакшн — одна маленькая ARM VPS (например, Hetzner cax11). Ubuntu LTS. Стек: Python + uvicorn + sqlite; без nginx, без Docker. На MVP это ок: нагрузка низкая, простота > масштабируемость.

Uvicorn слушает **напрямую на 80 порту**. Для этого systemd дарит ему `CAP_NET_BIND_SERVICE` — без root'а, но с правом биндить low-port.

Цель задачи — один скрипт, который на чистой Ubuntu поднимает рабочий сервис.

---

## Что нужно сделать

`deploy/bootstrap.sh`, `deploy/en-reader.service`, `deploy/README.md`.

---

## Что входит

### 1. `deploy/bootstrap.sh`

Идемпотентный скрипт. Можно запускать многократно.

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_USER="enreader"
APP_HOME="/opt/en-reader"
REPO_URL="https://github.com/YOUR_ORG/en-reader.git"

# 1. Пакеты.
apt update
apt install -y python3.11 python3.11-venv python3-pip git ufw

# 2. Пользователь.
id -u "$APP_USER" &>/dev/null || useradd --system --shell /bin/bash --home "$APP_HOME" "$APP_USER"
mkdir -p "$APP_HOME"
chown -R "$APP_USER:$APP_USER" "$APP_HOME"

# 3. Репо.
sudo -u "$APP_USER" bash -c "
  cd $APP_HOME
  if [ ! -d .git ]; then
    git clone $REPO_URL .
  else
    git pull
  fi
"

# 4. venv + deps.
sudo -u "$APP_USER" bash -c "
  cd $APP_HOME
  python3.11 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -e .
  .venv/bin/python -m spacy download en_core_web_sm
"

# 5. Data dir.
sudo -u "$APP_USER" mkdir -p "$APP_HOME/data/covers"

# 6. .env заготовка.
if [ ! -f "$APP_HOME/.env" ]; then
  cat > "$APP_HOME/.env" <<EOF
GEMINI_API_KEY=SET_ME
GEMINI_MODEL=gemini-2.5-flash-lite
ENV=prod
EOF
  chown "$APP_USER:$APP_USER" "$APP_HOME/.env"
  chmod 600 "$APP_HOME/.env"
fi

# 7. systemd.
cp "$APP_HOME/deploy/en-reader.service" /etc/systemd/system/en-reader.service
systemctl daemon-reload
systemctl enable en-reader
systemctl restart en-reader

# 8. ufw.
ufw allow 22/tcp
ufw allow 80/tcp
ufw --force enable

echo "Bootstrap OK. Set GEMINI_API_KEY in $APP_HOME/.env and restart."
```

### 2. `deploy/en-reader.service`

```ini
[Unit]
Description=en-reader web service
After=network.target

[Service]
Type=simple
User=enreader
Group=enreader
WorkingDirectory=/opt/en-reader
EnvironmentFile=/opt/en-reader/.env
ExecStart=/opt/en-reader/.venv/bin/uvicorn en_reader.app:app --host 0.0.0.0 --port 80 --workers 1
Restart=on-failure
RestartSec=3

# Дать право биндить low-ports без root.
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 3. `deploy/README.md`

```markdown
# Deploy en-reader

## Первичный деплой

На чистой Ubuntu 22.04+ (root):

    curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/en-reader/main/deploy/bootstrap.sh | bash

После первого запуска:
1. Открой `/opt/en-reader/.env`, поставь `GEMINI_API_KEY=...`.
2. `systemctl restart en-reader`.
3. Открой `http://<ip>/` — должен быть экран логина.

## Логи

    journalctl -u en-reader -f

## Рестарт

    systemctl restart en-reader

## Статус

    systemctl status en-reader
```

### 4. Проверка на чистой VM

- Создать VM Ubuntu 22.04.
- `curl | bash` bootstrap.
- Поставить API key в `.env`, перезапустить.
- Открыть `http://<ip>/` → виден экран логина.
- Signup → upload тестовой книги → прочитать пару страниц → перевод работает.

---

## Технические детали и ловушки

- **`AmbientCapabilities=CAP_NET_BIND_SERVICE`** — единственный красивый способ привязать uvicorn к :80 без root. Проверь, что systemd ≥ 229.
- **`ProtectSystem=full`** — `/usr`, `/boot` read-only. `/opt/en-reader` пишется (это не `/usr`). `/var/log` тоже пишется.
- **`ProtectHome=read-only`** — `/home` недоступен на запись. Нас это не трогает, мы в `/opt`.
- **Workers = 1**. SQLite + одна connection — не масштабируется на несколько workers без WAL и аккуратности. MVP — 1.
- **ufw правила**. SSH (22) обязательно впусти ДО включения ufw — иначе отрубишься.
- **git URL** — замени YOUR_ORG на актуальный. В идеале — параметр скрипта.

---

## Acceptance

- [ ] На чистой Ubuntu 22.04 `bootstrap.sh` успешно прогоняется.
- [ ] `systemctl status en-reader` показывает active.
- [ ] `curl http://localhost/` возвращает HTML.
- [ ] `journalctl -u en-reader` показывает startup-логи.
- [ ] После `reboot` сервис поднимается автоматически.
- [ ] Без root: приложение крутится от `enreader`.
- [ ] `.env` с правами 0600, принадлежит `enreader`.

---

## Что сдавать

- Ветка `task/M13-1-vps-systemd-bootstrap`, PR в main.
- В PR — IP тестовой VM, куда можно зайти посмотреть (или скринкаст).

---

## Что НЕ делать

- Не ставь nginx.
- Не используй Docker.
- Не храни ключи в репозитории.
- Не пиши автопулл — это **M13.2**.
- Не настраивай TLS — это **M13.4**.
