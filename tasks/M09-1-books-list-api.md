# Задача M9.1 — API списка книг и удаление

**Размер.** S (~0.5 дня)
**Зависимости.** M8.1, M8.2.
**Что строится поверх.** M9.2 (экран библиотеки), M12.4 (upload — тот же контракт).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Для экрана библиотеки фронту нужен список всех книг пользователя и возможность удалить книгу. API максимально простой.

---

## Что нужно сделать

Роут `GET /api/books` (список), роут `DELETE /api/books/{id}` (каскадное удаление).

---

## Что входит

### 1. Роут `GET /api/books`

```python
@app.get("/api/books")
def list_books():
    metas = storage.book_list()   # уже реализовано в M8.1
    return [
        {
            "id": m.id,
            "title": m.title,
            "author": m.author,
            "total_pages": m.total_pages,
            "has_cover": bool(m.cover_path),
        }
        for m in metas
    ]
```

Сортировка — по `created_at DESC` (самые новые первыми).

### 2. Роут `DELETE /api/books/{id}`

```python
@app.delete("/api/books/{book_id}")
def delete_book(book_id: int):
    meta = storage.book_meta(book_id)
    if not meta:
        raise HTTPException(404)
    storage.book_delete(book_id)
    return Response(status_code=204)
```

`book_delete` уже каскадно удаляет pages и book_images (M8.1). Cover-файл на диске — тоже удалить.

### 3. Pydantic-модели

```python
class BookListItem(BaseModel):
    id: int
    title: str
    author: str | None
    total_pages: int
    has_cover: bool
```

### 4. Тесты `tests/test_books_api.py`

- Seed двух книг → `GET /api/books` возвращает список из 2, новая первой.
- `DELETE /api/books/{id}` → 204 → `GET /api/books` возвращает 1 книгу.
- Пытаемся `GET /api/books/{deleted_id}/content` → 404.
- В таблице `pages` и `book_images` нет osiротевших записей после удаления.
- `DELETE /api/books/999` → 404.

---

## Технические детали и ловушки

- **Cover-файл на диске**. Если реализация сохраняет обложку файлом — не забудь удалить его в `book_delete`. Если храним в БД (альтернативный путь M7.1) — это часть каскада.
- **reading_progress каскад**. На M9 таблицы ещё нет. Когда появится в M10.1, нужно добавить `ON DELETE CASCADE` и перепроверить каскад в `book_delete`.
- **Double-delete**. Если параллельно два запроса `DELETE /api/books/1` — одно получит 404, второе 204. Норм для MVP.

---

## Acceptance

- [ ] `GET /api/books` возвращает все книги.
- [ ] Новая книга попадает в начало списка.
- [ ] `DELETE /api/books/{id}` каскадно очищает pages, book_images.
- [ ] Cover-файл удаляется с диска (если есть).
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M9-1-books-list-api`, PR в main.

---

## Что НЕ делать

- Не делай фронт библиотеки (**M9.2**).
- Не делай upload (**M12.4**).
- Не добавляй фильтры/поиск — список всегда полный.
