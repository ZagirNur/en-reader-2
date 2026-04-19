# Задача M13.3 — Telegram deploy-notify

**Размер.** S (~0.5 дня)
**Зависимости.** M13.2.
**Что строится поверх.** Оперативная видимость деплоя без лазания по `journalctl`.

---

## О проекте (контекст)

**en-reader** — веб-читалка. После каждого **успешного** деплоя в Telegram-чат разработчика прилетает сообщение `deployed <sha>`. После неудачного — `failed <sha>: <reason>`. No-op деплой (git pull ничего не подтянул) — тишина.

Бот уже создан, токен и chat_id — у тимлида. На MVP — лежат в `.env`. На случай если `.env` недоступен в autopull-скрипте (root vs enreader) — hardcoded fallback в скрипте (тимлид даст значения).

---

## Что нужно сделать

`deploy/notify.sh`, интеграция в `autopull.sh`, обработка ошибок.

---

## Что входит

### 1. `deploy/notify.sh`

```bash
#!/usr/bin/env bash
# Usage: notify.sh <message>

MESSAGE="${1:-deployed}"

# Получить токен/chat из env или fallback.
if [ -f /opt/en-reader/.env ]; then
  set -a
  source /opt/en-reader/.env
  set +a
fi

TG_BOT_TOKEN="${TG_BOT_TOKEN:-HARDCODED_BOT_TOKEN}"
TG_CHAT_ID="${TG_CHAT_ID:-HARDCODED_CHAT_ID}"

if [ -z "$TG_BOT_TOKEN" ] || [ -z "$TG_CHAT_ID" ]; then
  exit 0   # нет токенов — тихо выходим
fi

curl -sS \
  --max-time 10 \
  -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}" \
  > /dev/null || true
```

`HARDCODED_BOT_TOKEN` / `HARDCODED_CHAT_ID` — тимлид заменит реальными в коде; они считаются «ок хардкодить, т.к. бот выделен под этот деплой».

### 2. Интеграция в `autopull.sh`

Заменить финальную секцию:

```bash
# ... успешный deploy ...
SHORT_SHA=$(sudo -u enreader git rev-parse --short HEAD)
"$APP_HOME/deploy/notify.sh" "deployed $SHORT_SHA"

# при ошибке (оборачиваем весь критичный блок):
trap 'SHORT_SHA=$(cd '$APP_HOME' && git rev-parse --short HEAD 2>/dev/null || echo unknown); "$APP_HOME/deploy/notify.sh" "failed $SHORT_SHA"' ERR
```

Пример обёртки с `trap`:
```bash
set -euo pipefail
trap 'notify_failure' ERR

notify_failure() {
  local sha
  sha=$(cd "$APP_HOME" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  "$APP_HOME/deploy/notify.sh" "failed deploy at $sha"
}
```

Trap срабатывает на любой `set -e` exit. Через него — автоматический failure-notify.

### 3. `.env.example` обновить

```
TG_BOT_TOKEN=
TG_CHAT_ID=
```

### 4. Формат сообщений

- Успех: `deployed a1b2c3d4` (короткий SHA).
- Ошибка: `failed deploy at a1b2c3d4` (можно добавить ссылку на journalctl: `failed deploy at a1b2c3d4\njournalctl -u en-reader-autopull -n 50`).
- Никакого шума при no-op.

### 5. Ручная проверка

- Коммит → Telegram сообщение в течение 30 с.
- Поломай миграцию (или другую критичную часть) → autopull упадёт → failure-сообщение в Telegram.
- Ничего не коммить 5 минут → никаких сообщений.

---

## Технические детали и ловушки

- **curl --max-time** — обязательно, иначе висячий Telegram может задержать autopull.
- **`|| true`** после curl — чтобы сбой Telegram не ломал deploy.
- **Hardcoded fallback**. Плохо с точки зрения security, но бот изолирован и не имеет доступа к прод-данным. Для MVP приемлемо.
- **Trap ERR** — срабатывает при любом ошибочном exit под `set -e`. Не сработает, если `git pull` ничего не подтянул (`exit 0` штатный).

---

## Acceptance

- [ ] Успешный push → Telegram `deployed <sha>` в течение 30 с.
- [ ] Падающий deploy → Telegram `failed deploy at <sha>`.
- [ ] No-op → тишина.
- [ ] Telegram-таймаут не блокирует autopull дольше 10 с.

---

## Что сдавать

- Ветка `task/M13-3-telegram-notify`, PR в main.

---

## Что НЕ делать

- Не шлёт сообщения в чат в Slack/Discord.
- Не шли deployment status для каждого HTTP-запроса.
- Не посылай диагностическую информацию с секретами.
