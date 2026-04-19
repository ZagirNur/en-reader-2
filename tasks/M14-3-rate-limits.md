# Задача M14.3 — Rate-limits на translate/upload/auth

**Размер.** S (~1 день)
**Зависимости.** M11.2 (auth есть), M12.4 (upload есть), M4.1 (translate).
**Что строится поверх.** Защита от злоупотреблений и runaway-кликов.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Без rate-limit пользователь, удерживая Enter на клавиатуре, может послать 1000 запросов `/api/translate` за секунду и сжечь весь бюджет на Gemini. Bot с пачкой email'ов может забить signup. Пользователь может пытаться загрузить 200 GB через 1000 раз по 200 МБ.

Решение — in-memory лимитер на уровне пользователя/IP. Redis не ставим — один процесс, счётчики в памяти достаточны.

---

## Что нужно сделать

Простой RateLimit-класс, применить к трём группам роутов, тесты.

---

## Что входит

### 1. Модуль `src/en_reader/ratelimit.py`

```python
import time
from collections import defaultdict
from threading import Lock

class RateLimit:
    def __init__(self, max_hits: int, window_seconds: int):
        self.max = max_hits
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits[key] if now - t < self.window]
            if len(hits) >= self.max:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True
```

### 2. Глобальные лимитеры

```python
rl_auth = RateLimit(max_hits=10, window_seconds=60)       # 10/min per IP
rl_translate = RateLimit(max_hits=60, window_seconds=60)  # 60/min per user
rl_upload = RateLimit(max_hits=5, window_seconds=3600)    # 5/hour per user
```

### 3. Применение в роутах

```python
@app.post("/auth/signup")
def signup(cred: Credentials, request: Request):
    if not rl_auth.check(request.client.host):
        raise HTTPException(429, "too many attempts")
    ...

@app.post("/auth/login")
def login(cred: Credentials, request: Request):
    if not rl_auth.check(request.client.host):
        raise HTTPException(429, "too many attempts")
    ...

@app.post("/api/translate")
def translate(req: TranslateRequest, user: User = Depends(get_current_user)):
    if not rl_translate.check(str(user.id)):
        raise HTTPException(429, "slow down")
    ...

@app.post("/api/books/upload")
async def upload_book(file: UploadFile, user: User = Depends(get_current_user)):
    if not rl_upload.check(str(user.id)):
        raise HTTPException(429, "too many uploads today")
    ...
```

Если M11.2 уже добавил rate-limit для auth — объедини с общей инфраструктурой, не дублируй.

### 4. Headers на 429

```python
raise HTTPException(
    429,
    "too many attempts",
    headers={"Retry-After": str(rl.window)},
)
```

### 5. Тесты `tests/test_ratelimit.py`

- Быстро 11 `POST /auth/login` с одного IP → 11-й 429.
- Быстро 61 `POST /api/translate` от одного user → 61-й 429.
- Быстро 6 upload в час → 6-й 429.
- После window переключается окно — снова можно.

Для тестов скорости — `monkeypatch time.time` на виртуальное время, чтобы не ждать 60 секунд.

### 6. UI-поведение

На фронте при 429:
- Translate: toast «Помедленнее, слишком часто».
- Auth: показать ошибку в форме, заблокировать submit на 60 с.
- Upload: toast «Слишком много загрузок за час. Попробуйте позже».

---

## Технические детали и ловушки

- **behind proxy** (Caddy → uvicorn). `request.client.host` — это IP Caddy (127.0.0.1). Нужно читать `X-Forwarded-For` или `X-Real-IP`. Starlette имеет `ProxyHeadersMiddleware`:
  ```python
  from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
  app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")
  ```
  Тогда `request.client.host` вернёт реальный IP.
- **Memory leak**. `_hits` растёт с каждым новым IP. Периодическая очистка не критична для MVP, но можно раз в час сбрасывать полностью.
- **Threading.Lock**. На `--workers 1` не обязательно, но не повредит. На > 1 воркер — в памяти у каждого свои счётчики; нужен Redis, но мы на 1 воркере.

---

## Acceptance

- [ ] Auth rate-limit — 10 попыток/IP/минуту.
- [ ] Translate rate-limit — 60/user/минуту.
- [ ] Upload rate-limit — 5/user/час.
- [ ] 429 отдаёт Retry-After.
- [ ] Реальный IP через X-Forwarded-For виден.
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M14-3-rate-limits`, PR в main.

---

## Что НЕ делать

- Не ставь Redis.
- Не добавляй глобальный rate-limit на все роуты — только критичные.
- Не делай сложные схемы (sliding window с весом) — MVP.
