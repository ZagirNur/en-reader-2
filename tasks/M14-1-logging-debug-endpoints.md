# Задача M14.1 — Структурированные логи, /debug/logs, /debug/health

**Размер.** M (~2 дня)
**Зависимости.** M13.1 (прод есть).
**Что строится поверх.** Базовая наблюдаемость — смотреть что происходит без SSH.

---

## О проекте (контекст)

**en-reader** — веб-читалка. На проде критически важно быстро увидеть, что сломалось, не заходя в SSH. Решение:
1. **Structured logs** — JSON в prod, pretty в dev.
2. **RingBufferHandler** — последние 1000 строк в памяти.
3. **`/debug/logs`** — HTTP-эндпоинт, отдающий tail этого буфера (с basic-auth или admin-флагом).
4. **`/debug/health`** — мета-информация: git SHA, uptime, счётчики.

Это не замена journalctl, а быстрый просмотр с браузера.

---

## Что нужно сделать

Logger, ring-buffer handler, два debug-роута, подключение к uvicorn/fastapi logger'ам.

---

## Что входит

### 1. Логгер

В `src/en_reader/logs.py`:

```python
import logging
import sys
import json
from collections import deque
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "ts": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)

class RingBufferHandler(logging.Handler):
    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self.buffer: deque = deque(maxlen=maxlen)

    def emit(self, record):
        self.buffer.append(self.format(record))

    def tail(self, n: int = 200) -> list[str]:
        return list(self.buffer)[-n:]

_ring = RingBufferHandler()

def install():
    is_prod = (os.getenv("ENV") == "prod")
    fmt = JsonFormatter() if is_prod else logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    _ring.setFormatter(fmt)
    root.addHandler(_ring)

    # Подключить uvicorn и fastapi логгеры.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True

def get_ring() -> RingBufferHandler:
    return _ring
```

### 2. Вызов `install()`

В `app.py` перед созданием FastAPI-app:

```python
from en_reader.logs import install, get_ring
install()
logger = logging.getLogger("en_reader")
```

### 3. Роут `/debug/logs`

```python
@app.get("/debug/logs")
def debug_logs(request: Request, n: int = 200, user: User = Depends(get_current_user)):
    # Только для admin (первый юзер в БД или специальный email).
    if not _is_admin(user):
        raise HTTPException(403)
    n = min(max(n, 1), 1000)
    return Response(
        content="\n".join(get_ring().tail(n)),
        media_type="text/plain; charset=utf-8",
    )

def _is_admin(user: User) -> bool:
    admin_email = os.getenv("ADMIN_EMAIL", "")
    return bool(admin_email) and user.email == admin_email
```

Альтернатива — basic-auth. Выбирай одну. Admin через ADMIN_EMAIL в `.env` проще.

### 4. Роут `/debug/health`

```python
import subprocess
from datetime import datetime

_startup_ts = datetime.utcnow()
_git_sha = None

def _get_git_sha():
    global _git_sha
    if _git_sha is None:
        try:
            _git_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            _git_sha = "unknown"
    return _git_sha

@app.get("/debug/health")
def health():
    return {
        "status": "ok",
        "git_sha": _get_git_sha(),
        "uptime_seconds": int((datetime.utcnow() - _startup_ts).total_seconds()),
        "counts": {
            "users": storage.count_users(),
            "books": storage.count_books(),
        },
        "translate_counters": {
            "hit": Counters.translate_hit,
            "miss": Counters.translate_miss,
        },
    }
```

`/debug/health` публичный (без auth) — для мониторинга / uptimerobot.

### 5. Логирование ключевых событий

- Старт приложения: `logger.info("en-reader starting, sha=%s", _get_git_sha())`.
- Signup/login: `logger.info("user signed up: email=%s", email)` / `"user logged in: email=%s"`.
- Upload: `logger.info("book uploaded: id=%d title=%r size=%d", ...)`.
- Translate: уже есть в M4.1/M6.2.
- Errors: уже через `logger.exception(...)`.

### 6. Тесты `tests/test_debug_endpoints.py`

- `/debug/health` доступен без auth, возвращает корректную структуру.
- `/debug/logs` без auth → 401.
- `/debug/logs` авторизованным non-admin → 403.
- `/debug/logs` admin → 200 со строками.
- Ring-buffer хранит ≤ 1000 записей (после 1001 появляется первая выпадает).

---

## Технические детали и ловушки

- **Handlers на корневом logger'е**. Если uvicorn имеет свой handler'ы — мы их снимаем (`log.handlers.clear()`). Альтернатива — прикрутить ring-buffer к их логам отдельно.
- **Size 1000**. На prod это ~100 кБ памяти. Достаточно для последних 10-30 минут при нашей нагрузке.
- **Git SHA в runtime**. Работает, если `.git` доступен. В Docker — обычно нет. У нас — обычная установка из git, ок.
- **`/debug/health` публичный**. Не содержит секретов, только агрегаты. Допустимо.

---

## Acceptance

- [ ] `/debug/health` отдаёт валидный JSON.
- [ ] `/debug/logs` с admin-credentials отдаёт последние строки.
- [ ] Логи в prod — JSON, в dev — pretty.
- [ ] Signup/login/translate/upload залогированы.
- [ ] `/debug/logs` без auth → 401.
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M14-1-logging-debug-endpoints`, PR в main.

---

## Что НЕ делать

- Не пиши логи в файл — только stdout (journald собирает).
- Не подключай Sentry — отдельная задача на будущее.
- Не делай Prometheus-метрики — /debug/health достаточен.
