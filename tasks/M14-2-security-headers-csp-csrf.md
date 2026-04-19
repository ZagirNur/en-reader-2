# Задача M14.2 — Security headers + CSP + CSRF

**Размер.** S (~1 день)
**Зависимости.** M11.2 (session middleware), M13.4 (HTTPS).
**Что строится поверх.** Baseline-защита от XSS, CSRF, clickjacking.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Базовая hardening-гигиена:
- CSP запрещает загрузку чужих скриптов (защита от XSS-injection).
- X-Frame-Options: DENY — нельзя встроить в iframe.
- Referrer-Policy ограничивает утечку URL.
- Проверка Origin/Referer на POST/DELETE — вторая линия против CSRF, поверх SameSite=Lax.

---

## Что нужно сделать

Middleware с security headers, проверка Origin на мутациях, тесты.

---

## Что входит

### 1. Security headers middleware

```python
from starlette.middleware.base import BaseHTTPMiddleware

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "style-src 'self'; "
    "script-src 'self'; "
    "frame-ancestors 'none'"
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp

app.add_middleware(SecurityHeadersMiddleware)
```

CSP `'self'` — разрешает только тот origin, что отдавал страницу. Никаких inline-скриптов. Никаких внешних CDN.

### 2. CSRF-проверка Origin

```python
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin") or request.headers.get("referer", "")
            if origin:
                expected = str(request.base_url).rstrip("/")
                if not origin.startswith(expected):
                    return JSONResponse({"error": "forbidden origin"}, status_code=403)
            # Если Origin и Referer отсутствуют — допускаем (sendBeacon, например).
        return await call_next(request)

app.add_middleware(OriginCheckMiddleware)
```

Комментарий к «отсутствию Origin»: sendBeacon в некоторых браузерах не отправляет Origin, но CSRF через beacon делать тяжело (нет ответа). Допускаем.

### 3. Инлайн-обработчик стилей/скриптов

Проверь, что во фронте нет:
- `<script>...</script>` с кодом — только `<script src="/static/app.js">`.
- `onclick="..."` атрибутов — заменить на `addEventListener`.
- `<style>...</style>` inline — только подключённый `style.css`.

Если есть — перенеси в файлы.

### 4. Cookie-флаги

В M11.2 уже: `HttpOnly`, `SameSite=Lax`. Добавь `Secure=True` в prod (через `https_only`):
```python
app.add_middleware(
    SessionMiddleware,
    ...,
    https_only=(os.getenv("ENV") == "prod"),
)
```

### 5. HSTS

В M13.4 уже в Caddy. Проверь, что `Strict-Transport-Security: max-age=31536000` приходит.

### 6. Тесты `tests/test_security.py`

- Ответ на `/` содержит CSP, X-Frame-Options=DENY, etc.
- POST `/api/books/upload` с Origin=`http://evil.com` → 403.
- POST с Origin=own → 200 (или 401 если не авторизован — но проходит через middleware).
- GET — без проверки Origin.

### 7. Ручная проверка

- `securityheaders.com/?q=<domain>` — цель B+ или лучше.
- Проверка в DevTools: нет ошибок CSP.

---

## Технические детали и ловушки

- **CSP и inline-стили**. Если фронт использует `element.style.width = ...` — это не inline `<style>`, CSP это не блокирует. Блокируется только прямой `<style>X</style>` и `style="..."` атрибуты. `style=""` через JS — тоже ок.
- **CSP и `javascript:` URLs** — блокируются `'self'`.
- **Origin-check на `/auth/login`**. Нужно, иначе злой сайт может логинить наших пользователей.
- **Middleware order**. SecurityHeaders должен идти **после** SessionMiddleware в FastAPI. Убедись в порядке `add_middleware` (добавленные позже — внешние, т.е. первые в обработке).

---

## Acceptance

- [ ] Все response'ы имеют CSP/XFO/XCTO/RP/PP заголовки.
- [ ] `securityheaders.com` даёт не хуже B.
- [ ] POST с чужим Origin → 403.
- [ ] В dev нет ошибок CSP.
- [ ] Inline-скрипты и стили в `static/` отсутствуют.
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M14-2-security-headers`, PR в main.
- Ссылка на securityheaders.com отчёт — в описании PR.

---

## Что НЕ делать

- Не ослабляй CSP до `unsafe-inline` ради скорости разработки.
- Не включай CORS — фронт и бэк на одном origin.
- Не пиши собственный CSRF-токен — SameSite+Origin достаточно.
