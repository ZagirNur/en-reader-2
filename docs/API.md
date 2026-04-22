# en-reader API (v1)

Backend для iOS/Android клиентов и браузерных расширений. Полная OpenAPI-спека живёт в [`openapi.json`](./openapi.json); регенерируется через `python -m scripts.dump_openapi`.

Все `/api/*` эндпоинты автоматически доступны также под префиксом **`/api/v1/*`**. Контракт v1: только добавляем поля, никогда не переименовываем и не удаляем. Сервер делает path-rewrite внутри себя, OpenAPI показывает один набор путей.

## Аутентификация

Два параллельных пути, оба работают на всех `/api/*` эндпоинтах:

| Способ | Клиент | Заголовки |
|---|---|---|
| Cookie-сессия | Web SPA, Telegram Mini App | `Cookie: sess=…` (автоматически) |
| Bearer-токен | iOS/Android, браузерные расширения | `Authorization: Bearer er_<token>` |

### `POST /auth/token`

Обменять login/password или Telegram `initData` на пару `access + refresh`.

```json
// password-режим
{
  "mode": "password",
  "email": "me@example.com",
  "password": "correct horse"
}

// telegram-режим
{
  "mode": "telegram",
  "init_data": "<raw initData from Telegram.WebApp.initData>"
}
```

Ответ:

```json
{
  "access_token": "er_ABC...",
  "refresh_token": "er_XYZ...",
  "token_type": "Bearer",
  "access_expires_at": "2026-01-01T13:00:00+00:00",
  "refresh_expires_at": "2026-01-31T12:00:00+00:00"
}
```

- Access-токен живёт 1 час, refresh — 30 дней.
- Rate-limit: 10 попыток / IP / 60 сек (общий с `/auth/login`).

### `POST /auth/token/refresh`

Single-use refresh: старый refresh сразу инвалидируется, выдаётся свежая пара.

```json
{ "refresh_token": "er_XYZ..." }
```

Если отправить тот же `refresh_token` дважды — второй вызов вернёт 401 (защита от перехваченного refresh).

### `POST /auth/token/revoke`

Явный logout одного токена (access или refresh). Идемпотентен — 204 в любом случае.

```json
{ "token": "er_ABC..." }
```

### Все существующие `/auth/*` маршруты

`/auth/signup`, `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/telegram`, `/auth/link/telegram/*` — работают как раньше. `GET /auth/me` принимает и cookie, и Bearer.

## Перевод и упрощение

### `POST /api/translate`

```json
{
  "unit_text": "sprinted",
  "lemma": "sprint",
  "sentence": "She sprinted across the meadow.",
  "prev_sentence": "",
  "next_sentence": "",
  "source_book_id": 42,
  "mode": "translate"
}
```

- `mode`: `"translate"` (default, RU-перевод + сохраняется в словарь) или `"simplify"` (простой EN-синоним в той же грамматической форме, без side-effect-ов).
- `prev_sentence` / `next_sentence` — контекст для однозначности ± 1 предложение.

Ответ:

```json
{
  "ru": "пробежала",
  "source": "llm",
  "text": null,
  "is_simplest": false,
  "mode": "translate"
}
```

- `source`: `"dict"` (лемма уже в словаре юзера) / `"cache"` (промпт-хэш hit в серверном `llm_cache`) / `"llm"` (реальный вызов Gemini) / `"mock"` (E2E).
- В simplify-режиме `text` содержит замену (либо `null` если вход уже простейший) и `is_simplest: true` сигнализирует «просто открой карточку».

Rate-limit: 300 запросов / мин / user.

### `POST /api/translate/batch`

До 50 item-ов за один round-trip. Каждый item считается отдельным rate-limit-hit-ом.

```json
{
  "mode": "translate",
  "items": [
    { "unit_text": "drop", "lemma": "drop", "sentence": "...", ... },
    { "unit_text": "ran",  "lemma": "run",  "sentence": "...", ... }
  ]
}
```

Ответ: `{ "results": [<TranslateResponse>, ...] }`. Отказ одного item-а не ломает батч — слот получит `{"ru":"","source":"error",...}`.

## Словарь и синхронизация

### `GET /api/dictionary/sync?since=<ISO-8601>`

Delta-sync для мобильного клиента.

```json
{
  "server_time": "2026-01-01T12:34:56+00:00",
  "since": "2025-12-31T12:00:00+00:00",
  "upserts": [ { "lemma": "...", "translation": "...", "status": "...", "updated_at": "...", "card_json": "..." } ],
  "deletes": [ { "lemma": "...", "deleted_at": "..." } ]
}
```

- Первый вызов: без `?since` → полный снапшот + `server_time`.
- Последующие: передавай полученный ранее `server_time` как `?since=`.
- Удалённые слова приходят в `deletes` (tombstones) — клиент стирает у себя локально.

### Остальные словарные эндпоинты

`GET /api/dictionary` (плоский `{lemma: translation}`), `GET /api/dictionary/words` (полный list-of-objects), `GET /api/dictionary/stats`, `GET /api/dictionary/training`, `POST /api/dictionary/training/result`, `DELETE /api/dictionary/{lemma}`, `GET /api/dictionary/{lemma}/card` — без изменений.

## Книги и контент

- `POST /api/books/upload` (multipart) — EPUB/FB2/TXT.
- `GET /api/books` — список юзера.
- `GET /api/books/{book_id}/content?offset=&limit=` — страницы.
- `GET /api/books/{book_id}/cover` / `/images/{image_id}` — медиа.
- `POST /api/books/{book_id}/progress` — сохранить позицию.
- `DELETE /api/books/{book_id}` — удалить.

## CORS и origin-policy

Backend поддерживает:

- Cookie (same-site) — для web SPA и Mini App.
- Bearer (cross-origin) — для мобильных и расширений.

Env `CORS_ALLOW_ORIGINS` — список явных origin-ов через запятую. Регексом всегда разрешены `chrome-extension://*`, `moz-extension://*`, `safari-web-extension://*`.

`OriginCheckMiddleware` (CSRF-защита) проверяет POST/DELETE от cookie-клиентов; Bearer-клиенты её обходят — как и положено для не-браузерных запросов.

## Errors

| Код | Когда |
|---|---|
| 400 | Невалидное тело (деталь в `detail`) |
| 401 | Нет/протухла cookie И нет/невалидный Bearer |
| 403 | Origin-check (CSRF) или подтверждение вне whitelisted origins |
| 404 | Не найдено ИЛИ не принадлежит юзеру (чтобы не палить существование) |
| 422 | Pydantic-валидация не прошла |
| 429 | Rate-limit (см. `Retry-After`) |
| 502 | Gemini/внешний сервис сдох |
| 503 | Конфигурация недоступна (например bot token не задан) |

## Observability

- `GET /debug/health` — публичный liveness-пробник с метриками (`git_sha`, `session_key_id`, `llm_cache` hit/miss/rows, `translate_counters`).
- `GET /debug/tail?n=100&grep=translate|auth` — последние N строк из кольцевого буфера логов, только для авторизованного юзера.
- `GET /debug/logs?n=200` — полный буфер, требует `ADMIN_EMAIL`.
