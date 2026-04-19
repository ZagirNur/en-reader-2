# Задача M15.2 — Покрытие storage и контентных API

**Размер.** M (~2 дня)
**Зависимости.** M10.5 (полный single-user backend), M11.3 (isolation).
**Что строится поверх.** Регрессионная страховка для БД и основных роутов.

---

## О проекте (контекст)

**en-reader** — веб-читалка. После M10.5 есть весь backend-контракт кроме загрузки (парсеры — M12). До E2E-тестов (M15.6) нужно зачехлить все API-ручки юнит-/интеграционными тестами, чтобы поломка бэка ловилась на CI, а не на проде.

---

## Что нужно сделать

Аудит и расширение тестов `storage.py` и API `/api/books/*`, `/api/translate`, `/api/dictionary`, `/api/books/{id}/progress`, `/api/me/current-book`. Coverage ≥ 90%.

---

## Что входит

### 1. Фикстуры

`tests/conftest.py`:
```python
@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    _reset_storage_singleton()
    migrate()
    yield
    _reset_storage_singleton()

@pytest.fixture
def client_authed(tmp_db):
    """TestClient с залогиненным тестовым юзером."""
    from fastapi.testclient import TestClient
    from en_reader.app import app
    c = TestClient(app)
    c.post("/auth/signup", json={"email": "test@test.com", "password": "testtest"})
    yield c

@pytest.fixture
def seed_book(client_authed):
    """Сидит одну книгу. Возвращает book_id."""
    # Удобнее всего через прямую вставку в storage, а не через upload (парсеры могут быть ещё не готовы).
    from en_reader.storage import book_save
    from en_reader.parsers import ParsedBook
    parsed = ParsedBook(
        title="Test Book", author="Tester",
        language="en", source_format="txt",
        source_bytes_size=len("..."),
        text="The cat sat on the mat. She whispered.",
        images=[], cover=None,
    )
    return book_save(user_id=1, parsed=parsed)
```

### 2. test_storage.py

- `book_save` → `book_meta` возвращает корректный BookMeta.
- `pages_load_slice` порядок + границы.
- `book_delete` каскад.
- `dict_add`/`dict_remove`/`dict_all` с user_id — изоляция.
- `progress_set`/`progress_get` UPSERT.
- `current_book_set`/`current_book_get` — один юзер.
- Миграция на пустой БД — без ошибок.
- `_pack`/`_unpack` round-trip.

### 3. test_books_api.py

- `GET /api/books` — список своих книг.
- `GET /api/books/{id}/content` — happy path с offset/limit.
- `GET /api/books/{foreign_id}/content` — 404.
- `DELETE /api/books/{id}` — 204, каскад.
- `GET /api/books/{id}/cover` — 404 если нет; 200 если есть.
- Без auth все 401.

### 4. test_translate_api.py

(Часть уже в M6.2.)
- Мок LLM. `POST /api/translate` с новым lemma → LLM called once, dict updated.
- Повторный POST → LLM not called, dict unchanged.
- Pydantic-валидация.
- 502 при failing LLM.

### 5. test_dictionary.py

- `GET /api/dictionary` — все записи юзера.
- `DELETE /api/dictionary/{lemma}` — 204.
- `DELETE несуществующий lemma` — 204 (idempotent) или 404 (выбери консистентность). Рекомендую 204.
- Изоляция по user_id.

### 6. test_progress.py

- `POST /api/books/{id}/progress` — happy.
- offset = 1.5 → 422.
- page_index > total_pages → 400.
- `/content` возвращает сохранённое.

### 7. test_current_book.py

- GET/POST — happy.
- POST с несуществующим book_id → 404.
- DELETE book, которая current-book → автоматически null.

### 8. test_isolation.py

- Юзер A, B.
- A не видит книги B.
- A не видит словарь B.
- A не может удалить книгу B → 404.
- A не может писать progress по книге B → 404.

### 9. Coverage

Целевой coverage ≥ 90% для:
- `src/en_reader/storage.py`
- `src/en_reader/app.py` (роуты)
- `src/en_reader/auth.py`

---

## Технические детали и ловушки

- **Мок LLM** — через `monkeypatch.setattr("en_reader.translate.translate_one", fake)`.
- **Test isolation**. Фикстура `tmp_db` обязательно обнуляет connection, иначе тесты делят БД.
- **Sessions в TestClient**. Каждый `client_authed` — свой TestClient, свои cookie. Для двух юзеров — два клиента.
- **migrate() в фикстуре**. Каждый тест начинает с чистой свежесозданной БД — это медленно. Можно переиспользовать через `scope="session"` но тогда тесты зависят друг от друга. Предпочитаем изоляцию.

---

## Acceptance

- [ ] Coverage ≥ 90% для storage.py, app.py роутов, auth.py.
- [ ] Все perms-тесты (isolation) зелёные.
- [ ] Все роуты покрыты happy path + 4xx.
- [ ] Никаких реальных LLM-вызовов в тестах.
- [ ] Тесты прогоняются за ≤ 30 с локально.

---

## Что сдавать

- Ветка `task/M15-2-storage-api-coverage`, PR в main.

---

## Что НЕ делать

- Не тестируй SQLite (ORM-прослойки — нет).
- Не делай E2E (**M15.6**).
- Не ходи на реальный Gemini.
