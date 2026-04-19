# Задача M11.2 — Auth API + сессии + persistent SECRET_KEY

**Размер.** M (~2 дня)
**Зависимости.** M11.1 (таблица users есть).
**Что строится поверх.** M11.3 (изоляция и экран логина).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Появляется реальная аутентификация: signup (email + пароль), login, logout, текущий пользователь. Пароль — bcrypt. Сессия — подписанная cookie (Starlette SessionMiddleware), TTL 30 дней, переживает рестарт сервера.

Ключевое требование: **SECRET_KEY переживает рестарт**. Если генерировать заново при каждом старте — пользователей будет выкидывать на каждый deploy. Решение — файл `data/.secret_key`, генерируемый при первом старте.

---

## Что нужно сделать

bcrypt, persistent SECRET_KEY, SessionMiddleware, 4 auth-роута, dependency `get_current_user`, rate-limit.

---

## Что входит

### 1. Зависимости

В `pyproject.toml`:
- `bcrypt`
- `itsdangerous` (для starlette sessions — обычно уже в зависимостях starlette)
- `slowapi` (rate limit; или собственный простой лимитер в памяти)

### 2. Модуль `src/en_reader/auth.py`

```python
import bcrypt
from email_validator import validate_email, EmailNotValidError

BCRYPT_MAX = 72

def hash_password(password: str) -> str:
    pw = password.encode()[:BCRYPT_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode()

def check_password(password: str, hashed: str) -> bool:
    if hashed == "__migration_placeholder__":
        return False
    pw = password.encode()[:BCRYPT_MAX]
    try:
        return bcrypt.checkpw(pw, hashed.encode())
    except Exception:
        return False

def normalize_email(email: str) -> str:
    try:
        v = validate_email(email, check_deliverability=False)
        return v.normalized.lower()
    except EmailNotValidError as e:
        raise ValueError(str(e))
```

Убедись, что `email-validator` в зависимостях.

### 3. Persistent SECRET_KEY

В `app.py` на импорте модуля (до `app = FastAPI()`):

```python
def _secret_key() -> str:
    path = Path("data/.secret_key")
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    path.write_text(key)
    os.chmod(path, 0o600)
    return key

SECRET_KEY = _secret_key()
```

### 4. SessionMiddleware

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="sess",
    max_age=60 * 60 * 24 * 30,   # 30 days
    same_site="lax",
    https_only=os.getenv("ENV") == "prod",
    http_only=True,
)
```

### 5. Storage для пользователей

```python
def user_create(email: str, password_hash: str) -> int: ...
def user_by_email(email: str) -> User | None: ...
def user_by_id(user_id: int) -> User | None: ...
```

UNIQUE constraint на email даёт IntegrityError при дубле — превращаем в `EmailExistsError`.

### 6. Роуты

```python
class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=8)

@app.post("/auth/signup")
def signup(cred: Credentials, request: Request):
    email = normalize_email(cred.email)
    if storage.user_by_email(email):
        raise HTTPException(409, "email exists")
    user_id = storage.user_create(email, hash_password(cred.password))
    request.session["user_id"] = user_id
    return {"email": email}

@app.post("/auth/login")
def login(cred: Credentials, request: Request):
    email = normalize_email(cred.email)
    user = storage.user_by_email(email)
    if not user or not check_password(cred.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    request.session["user_id"] = user.id
    return {"email": user.email}

@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return Response(status_code=200)

@app.get("/auth/me")
def me(request: Request):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(401)
    user = storage.user_by_id(uid)
    if not user:
        request.session.clear()
        raise HTTPException(401)
    return {"email": user.email}
```

### 7. Dependency `get_current_user`

```python
def get_current_user(request: Request) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(401)
    user = storage.user_by_id(uid)
    if not user:
        raise HTTPException(401)
    return user
```

На этой задаче НЕ применять ко всем роутам — это M11.3.

### 8. Rate-limit на auth

Простейший in-memory лимитер:
```python
class AuthRateLimit:
    def __init__(self):
        self._hits = defaultdict(list)   # ip -> [timestamps]
    def check(self, ip: str) -> bool:
        now = time.time()
        self._hits[ip] = [t for t in self._hits[ip] if now - t < 60]
        if len(self._hits[ip]) >= 10:
            return False
        self._hits[ip].append(now)
        return True
```

Проверка в signup/login:
```python
if not _ratelimit.check(request.client.host):
    raise HTTPException(429, "too many attempts")
```

### 9. Тесты `tests/test_auth.py`

- `POST /auth/signup` → 200 + session cookie; `GET /auth/me` возвращает email.
- `POST /auth/signup` с тем же email → 409.
- `POST /auth/login` с верными credentials → 200; с неверными → 401.
- `POST /auth/logout` → `GET /auth/me` → 401.
- Пароль < 8 → 422.
- bcrypt round-trip: `hash_password + check_password` работает.
- 11-й login подряд с одного IP → 429.
- Сессия переживает «рестарт»: создай новое FastAPI-приложение с тем же SECRET_KEY, закинь старую cookie — `/auth/me` возвращает email (важно: проверка на стабильность ключа).

---

## Технические детали и ловушки

- **bcrypt 72-byte truncate**. Длинные пароли обрезаем до 72 байт — это ограничение bcrypt. Пользователь этого не заметит для обычных паролей.
- **Email normalization**. `user@EXAMPLE.com` и `user@example.com` — один юзер. Нормализуй в `.lower()`.
- **Session middleware** ставится **до** определения роутов? Нет, в любой момент до `app.run`. Но если другие middleware-ы что-то делают с `request.session` — порядок важен.
- **`https_only` в prod**. Контролируется env `ENV=prod`. Локально без HTTPS.
- **SameSite=Lax** — защита от CSRF базовая. Строгая CSRF-проверка — в M14.2.

---

## Acceptance

- [ ] signup → login → me → logout → me(401) — сценарий отрабатывает.
- [ ] Рестарт приложения (test через `monkeypatch` SECRET_KEY файла): сессия всё ещё валидна.
- [ ] Email занят → 409.
- [ ] Невалидный email / короткий пароль → 422.
- [ ] 11 попыток login → 429.
- [ ] `data/.secret_key` создаётся с правами 0o600.
- [ ] Все тесты зелёные.

---

## Что сдавать

- Ветка `task/M11-2-auth-api`, PR в main.

---

## Что НЕ делать

- Не добавляй «забыл пароль» — не делаем email-отправку.
- Не добавляй email-подтверждение.
- Не реализуй изоляцию ресурсов (**M11.3**).
- Не применяй `get_current_user` к `/api/*` — это M11.3.
