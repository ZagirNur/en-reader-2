# Задача M10.1 — Модель и API прогресса чтения

**Размер.** S (~1 день)
**Зависимости.** M8.1 (books/pages), M8.2 (content API).
**Что строится поверх.** M10.2 (восстановление скролла), M10.4 (сохранение), M10.5 (current-book), M11.1 (user_id миграция).

---

## О проекте (контекст)

**en-reader** — веб-читалка. «Закрыл книгу, открыл — продолжил с того же места» — базовая функция. Позиция чтения — это **page_index** (какая страница) **и offset ∈ [0, 1]** (какая часть этой страницы прокручена). Один offset без страницы — бесполезен при N страниц в книге.

На этой задаче — только БД-таблица и REST-контракт. Сам сбор/восстановление позиции на фронте — в M10.2–10.4.

---

## Что нужно сделать

Таблица `reading_progress`, миграция, storage-методы, API `POST` для сохранения, возврат полей в `/content`.

---

## Что входит

### 1. Миграция v3 → v4

```sql
CREATE TABLE reading_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  last_page_index INTEGER NOT NULL DEFAULT 0,
  last_page_offset REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  UNIQUE(book_id)
);
```

`user_id` появится в миграции M11.1.

### 2. Storage-методы

```python
def progress_set(book_id: int, page_index: int, page_offset: float) -> None:
    # UPSERT по book_id
    ...

def progress_get(book_id: int) -> tuple[int, float]:
    # возвращает (page_index, page_offset), по умолчанию (0, 0.0)
    ...
```

UPSERT:
```sql
INSERT INTO reading_progress(book_id, last_page_index, last_page_offset, updated_at)
VALUES(?,?,?,?)
ON CONFLICT(book_id) DO UPDATE SET
  last_page_index=excluded.last_page_index,
  last_page_offset=excluded.last_page_offset,
  updated_at=excluded.updated_at;
```

### 3. Роут `POST /api/books/{id}/progress`

```python
class ProgressIn(BaseModel):
    last_page_index: int = Field(ge=0)
    last_page_offset: float = Field(ge=0.0, le=1.0)

@app.post("/api/books/{book_id}/progress", status_code=204)
def save_progress(book_id: int, p: ProgressIn):
    meta = storage.book_meta(book_id)
    if not meta:
        raise HTTPException(404)
    if p.last_page_index >= meta.total_pages:
        raise HTTPException(400, "page_index out of range")
    storage.progress_set(book_id, p.last_page_index, p.last_page_offset)
```

### 4. Обогащение `GET /api/books/{id}/content`

Заменить жёстко прописанные нули на:
```python
page_index, offset = storage.progress_get(book_id)
return {
    ...,
    "last_page_index": page_index,
    "last_page_offset": offset,
    ...
}
```

### 5. Каскад при удалении книги

- `ON DELETE CASCADE` уже в FK. Проверь, что `PRAGMA foreign_keys=ON` в `get_db()`.
- В `book_delete` можно явно не удалять `reading_progress` — каскад справится.

### 6. Тесты `tests/test_progress.py`

- `progress_set(1, 10, 0.5)` → `progress_get(1) == (10, 0.5)`.
- Повторный set обновляет, не создаёт дубль.
- `progress_get` несуществующей книги → `(0, 0.0)`.
- `POST /api/books/1/progress {last_page_index: 10, last_page_offset: 0.5}` → 204.
- `GET /api/books/1/content` возвращает эти значения.
- `POST` с offset=1.5 → 422.
- `POST` с page_index >= total_pages → 400.
- Удаление книги → progress-запись исчезает.

---

## Технические детали и ловушки

- **offset ∈ [0, 1]**. Pydantic `Field(ge=0.0, le=1.0)` — строгая валидация.
- **`UNIQUE(book_id)`** — один прогресс на книгу. Когда появится `user_id` (M11.1), UNIQUE станет `(user_id, book_id)`.
- **updated_at** — полезен для сортировки «недавно читал» в будущем. Храни в ISO.
- **Округление offset**. Не округляй на сервере — принимай как есть (float precision). Фронт сам считает.
- **Пустой прогресс в `/content`**. Для новой книги возвращай `(0, 0.0)`, не null. Фронт так проще.

---

## Acceptance

- [ ] Миграция v3→v4 применяется, таблица `reading_progress` создана.
- [ ] `progress_set` + `progress_get` работают.
- [ ] `POST /api/books/{id}/progress` сохраняет.
- [ ] `GET /api/books/{id}/content` возвращает `last_page_index`, `last_page_offset`.
- [ ] Валидация: offset вне [0,1] → 422; page_index вне диапазона → 400.
- [ ] Удаление книги каскадно удаляет прогресс.
- [ ] Тесты `test_progress.py` зелёные.

---

## Что сдавать

- Ветка `task/M10-1-progress-api`, PR в main.

---

## Что НЕ делать

- Не добавляй `user_id` (M11.1).
- Не реализуй фронт — задачи M10.2–M10.4.
- Не делай current-book (M10.5).
- Не добавляй историю прогресса — только текущее значение.
