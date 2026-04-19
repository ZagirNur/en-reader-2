# Задача M11.3 — Изоляция ресурсов + экран логина

**Размер.** M (~2 дня)
**Зависимости.** M11.1, M11.2.
**Что строится поверх.** Все следующие вехи — работают в мульти-пользовательском режиме.

---

## О проекте (контекст)

**en-reader** — веб-читалка. После M11.2 у нас есть сессии, но роуты `/api/*` всё ещё работают на `SEED_USER_ID`. Нужно:
1. Защитить все `/api/*` — требовать сессию.
2. В каждом роуте использовать `current_user.id` вместо `SEED_USER_ID`.
3. При попытке доступа к чужому ресурсу — 403 (не 404, чтобы не вводить в заблуждение через timing-атаки — впрочем, можно и 404, если ресурс «не виден»).
4. Экран логина на фронте с переключением signup/login.
5. Redirect на `/login` если сессии нет.

---

## Что нужно сделать

Подключить `get_current_user` ко всем API, проверять владельца ресурса, собрать экран логина, добавить logout-кнопку.

---

## Что входит

### 1. Защита всех `/api/*` роутов

Через FastAPI Dependency:
```python
@app.get("/api/books", dependencies=[Depends(get_current_user)])
```

Ещё лучше — через dependency-аргумент, если нужен user внутри:
```python
@app.get("/api/books")
def list_books(user: User = Depends(get_current_user)):
    return storage.book_list(user.id)
```

Применить **ко всем** `/api/*` кроме... ни одного исключения. Даже `/api/me/current-book` требует auth.

### 2. Замена `SEED_USER_ID` на `user.id`

Все вызовы storage-методов заменить:
- `storage.book_list(SEED_USER_ID)` → `storage.book_list(user.id)`
- `storage.dict_all(SEED_USER_ID)` → `storage.dict_all(user.id)`
- И так далее.

Константу `SEED_USER_ID` можно удалить (или оставить только для тестов/seed-скрипта).

### 3. Проверка владельца в `/api/books/{id}/*`

```python
def _ensure_book_owner(book_id: int, user_id: int) -> BookMeta:
    meta = storage.book_meta(book_id)
    if not meta or meta.user_id != user_id:
        raise HTTPException(403)
    return meta

@app.get("/api/books/{book_id}/content")
def get_content(book_id: int, offset: int = 0, limit: int = 1,
                user: User = Depends(get_current_user)):
    meta = _ensure_book_owner(book_id, user.id)
    ...
```

То же для `/content`, `/cover`, `/images/{image_id}`, `/progress`, `DELETE`.

**Важно**: 403 (а не 404 для чужой книги) — тимлид решает «не раскрывать, существует ли чужая книга». Альтернативно — 404. Для консистентности выбери **404** (одинаковый ответ «не видно» для несуществующей и для чужой — лучшая приватность). В тестах используй 404.

### 4. Seed-скрипт

`scripts/seed.py` должен принять `--email` или работать на seed-user (user_id=1, если нет — создать). Альтернатива: требовать предварительного signup, и скрипт берёт указанный email.

Рекомендация: скрипт `--email=admin@local` → найдёт или создаст юзера (с дефолтным паролем, который пишется в stdout при создании) → сохранит книгу на него.

### 5. Фронт: экран `/login`

HTML:
```html
<main class="auth-view">
  <h1 id="auth-title">Войти</h1>
  <form id="auth-form">
    <input type="email" name="email" required placeholder="email">
    <input type="password" name="password" required minlength="8" placeholder="пароль (≥ 8)">
    <button type="submit">Войти</button>
    <div id="auth-error" class="error"></div>
  </form>
  <button id="auth-switch">Зарегистрироваться</button>
</main>
```

Логика:
- Переключение signup/login — меняет title, action, кнопку.
- Submit: `POST /auth/signup` или `/auth/login`.
- Успех: `navigate("/")` + reload state.
- Ошибка: показать текст (409 — «email занят», 401 — «неверные данные», 422 — «пароль слишком короткий»).

### 6. Bootstrap с auth-check

```js
async function bootstrap() {
  try {
    await apiGet("/auth/me");
    // авторизован → обычный flow с current-book
    const {book_id} = await apiGet("/api/me/current-book");
    if (book_id && location.pathname === "/") {
      navigate(`/books/${book_id}`);
      return;
    }
    renderRoute(location.pathname);
  } catch (e) {
    if (e.status === 401) {
      if (location.pathname !== "/login" && location.pathname !== "/signup") {
        navigate("/login");
      } else {
        renderRoute(location.pathname);
      }
    } else {
      // offline / 500
      setState({view: "error", error: "..."});
    }
  }
}
```

### 7. Logout-кнопка

В шапке читалки и/или библиотеки — кнопка «Выйти». Клик → `POST /auth/logout` → `navigate("/login")`.

### 8. Стили

Минимально пристойный экран логина:
```css
.auth-view { max-width: 360px; margin: 5rem auto; padding: 2rem; text-align: center; }
.auth-view input { width: 100%; padding: 0.7rem; margin: 0.5rem 0; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
.auth-view button[type=submit] { width: 100%; padding: 0.7rem; background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer; }
#auth-switch { background: none; border: none; color: #666; text-decoration: underline; cursor: pointer; }
.error { color: #c0392b; margin-top: 0.5rem; min-height: 1.2em; }
```

### 9. Тесты `tests/test_isolation.py`

- Создать юзеров A и B, у каждого по книге.
- `GET /api/books` для A возвращает только его книги.
- `GET /api/books/{B's book}/content` для A → 404.
- `DELETE /api/books/{B's book}` для A → 404 (не удалить чужое).
- `POST /api/translate` с lemma добавляет только в словарь A.
- `GET /api/dictionary` для A не содержит слов B.
- `/api/me/current-book` изолирован.

### 10. Обновлённые старые тесты

Там, где раньше шли «глобальные» запросы — теперь фикстура с authenticated client (нужно cookie).

---

## Технические детали и ловушки

- **403 vs 404 для чужого**. 404 лучше по приватности. Фиксируем **404**.
- **Сохранение сессии в TestClient**. `TestClient(app)` поддерживает cookies автоматически между запросами (использует один requests.Session). Создавай новый TestClient на каждого юзера.
- **Все `/api/*` защищены**. Проверь, что ни одна старая ручка не осталась без `Depends(get_current_user)`.
- **SSE/WebSocket нет** — не надо про них думать.

---

## Acceptance

- [ ] Все `/api/*` → 401 без сессии.
- [ ] Чужая книга → 404.
- [ ] Юзер A не видит книги/словарь/прогресс B.
- [ ] Экран логина работает (signup и login с переключением).
- [ ] Logout-кнопка очищает сессию и переводит на `/login`.
- [ ] `/login` и `/signup` — роуты фронта, не требуют сессии.
- [ ] Bootstrap редиректит на `/login` если сессии нет.
- [ ] Тесты `test_isolation.py` зелёные.

---

## Дизайн

Auth-экран в прототипе отдельно не проработан, но следует тем же editorial-токенам. Контейнер 360 px центр, `h1 "Войти"/"Регистрация"` 30 px 600, inputs — `border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; font-size: 15px; background: var(--card)`, submit — `btn primary full`, переключатель signup/login — `btn ghost`. Ошибки — цвет `var(--accent)`.

Токены — [`design-spec.md`](./_assets/design/design-spec.md). Классы `.btn`, `.card`, `.uplabel` готовятся в M16.1.

---

## Что сдавать

- Ветка `task/M11-3-isolation-login-ui`, PR в main.
- GIF «signup → library → upload → read» в описании.

---

## Что НЕ делать

- Не делай «забыл пароль» — нет email-отправки.
- Не делай подтверждение email.
- Не меняй контракт API без необходимости.
- Не делай социальный логин (OAuth).
