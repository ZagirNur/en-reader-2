# Задача M8.2 — API контента книги

**Размер.** S (~1 день)
**Зависимости.** M8.1 (books/pages в БД).
**Что строится поверх.** M9 (библиотека знает id книги и открывает её через этот эндпоинт), M10 (прогресс возвращается через этот же эндпоинт).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Фронт должен получать **одну книгу по id**, а не глобальную `demo.json`. API пагинированный: книга в 500 страниц не отдаётся разом. Контракт готовится сразу с полями прогресса (`last_page_index`, `last_page_offset`) — они заполнятся нулями на M8, а на M10 будут реальными.

---

## Что нужно сделать

Роут `GET /api/books/{id}/content?offset=N&limit=K`, замена `/api/demo` на новый контракт, обновление фронта.

---

## Что входит

### 1. Роут

```python
@app.get("/api/books/{book_id}/content")
def get_content(book_id: int, offset: int = 0, limit: int = 1):
    if limit > 20: limit = 20
    meta = storage.book_meta(book_id)
    if not meta:
        raise HTTPException(404)
    pages = storage.pages_load_slice(book_id, offset, limit)
    user_dict = storage.dict_all()
    # auto_unit_ids per page
    for p in pages:
        p["auto_unit_ids"] = [u["id"] for u in p["units"] if u["lemma"] in user_dict]
    return {
        "book_id": book_id,
        "total_pages": meta.total_pages,
        "last_page_index": 0,       # M10.1 заполнит
        "last_page_offset": 0.0,    # M10.1 заполнит
        "pages": pages,
        "user_dict": user_dict,
    }
```

### 2. Роут `GET /api/books/{id}/cover`

```python
@app.get("/api/books/{book_id}/cover")
def get_cover(book_id: int):
    meta = storage.book_meta(book_id)
    if not meta or not meta.cover_path:
        raise HTTPException(404)
    return FileResponse(meta.cover_path, headers={"Cache-Control": "public, max-age=86400"})
```

(На M8 у книг ещё нет обложек — все запросы к этому роуту вернут 404. Это нормально; обложки появятся в M12 с парсерами.)

### 3. Pydantic-модели ответа

Желательно явные response models — помогает документации:
```python
class TokenOut(BaseModel): ...
class UnitOut(BaseModel): ...
class PageOut(BaseModel):
    page_index: int
    text: str
    tokens: list[TokenOut]
    units: list[UnitOut]
    images: list[ImagePosOut]
    auto_unit_ids: list[int]

class ContentOut(BaseModel):
    book_id: int
    total_pages: int
    last_page_index: int
    last_page_offset: float
    pages: list[PageOut]
    user_dict: dict[str, str]
```

### 4. Удаление `/api/demo`

Роут полностью убрать. Seed-скрипт из M8.1 больше не пишет в `demo.json`.

### 5. Переделка фронта

В `app.js`:
- `loadBookContent(bookId, offset=0, limit=1)` через `apiGet`.
- `state.currentBook = {bookId, totalPages, pages: [...]}`.
- `renderReader()` использует новый state вместо `state.demo`.
- Пока нет библиотеки (M9) — при старте подставлять хардкод `bookId=1` и грузить первую страницу.
- Роутинг: `/books/:id` → reader.

### 6. Тесты `tests/test_content_api.py`

- `GET /api/books/1/content` возвращает 200 со структурой.
- `?offset=5&limit=3` возвращает страницы 5, 6, 7.
- `?limit=100` режется до 20.
- `GET /api/books/999/content` → 404.
- `auto_unit_ids` включает только Units, чья lemma в словаре.

### 7. Ручная проверка

- Seed небольшой книги → `curl http://localhost:8000/api/books/1/content?offset=0&limit=3` — три страницы.
- Открываем `/books/1` → видна первая страница.
- Клик по слову — работает (не сломался).

---

## Технические детали и ловушки

- **Десериализация tokens/units из gzip**. В `pages_load_slice` распаковывай и отдавай как dict/list (не dataclass — на API нужны серриализуемые структуры).
- **user_dict может быть большой**. При количестве уникальных слов > 1000 он весит мегабайт. ОК для MVP — позже можно оптимизировать (отдавать только lemma'ы, встречающиеся на запрошенных страницах).
- **`limit` ceiling**. 20 — разумный потолок для одного ответа. 100+ страниц разом — опасно для Safari.

---

## Acceptance

- [ ] `GET /api/books/{id}/content` работает с offset/limit.
- [ ] Фронт открывает страницу 0 книги 1 через новый эндпоинт.
- [ ] Клик по слову → inline перевод (не сломалось после замены `/api/demo`).
- [ ] `/api/demo` удалён.
- [ ] `GET /api/books/999/content` → 404.
- [ ] Тесты `test_content_api.py` зелёные.

---

## Что сдавать

- Ветка `task/M8-2-content-api`, PR в main.

---

## Что НЕ делать

- Не реализуй lazy-подгрузку (bidirectional sentinels) — это **M10.3**.
- Не реализуй сохранение прогресса (M10.1).
- Не добавляй экран библиотеки (M9).
- Не завязывайся на реальные обложки — их нет до M12.
