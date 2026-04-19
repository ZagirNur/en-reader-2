# Задача M8.1 — Таблицы books/pages, save/load, сжатие

**Размер.** M (~2 дня)
**Зависимости.** M6.1 (SQLite + миграции), M7.1 (картинки).
**Что строится поверх.** M8.2 (API контента), M9.x (библиотека), M10.x (прогресс), M11.1 (user_id).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пришло время положить книги и страницы в БД. Без этого нельзя иметь несколько книг, загрузку, прогресс. До этого всё жило в `demo.json` — он уйдёт.

Схема намеренно «без user_id» — в M11.1 мы добавим его миграцией и переселим seed-контент на «первого пользователя». Это упрощает M8-M10: никакого переписывания роутов ради auth.

tokens/units — большие структуры, их мы сжимаем gzip-JSON перед INSERT'ом.

---

## Что нужно сделать

Таблицы `books` и `pages`, миграцию, функции save/load, seed-скрипт записывает в БД вместо JSON.

---

## Что входит

### 1. Миграция v2 → v3

```sql
CREATE TABLE books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  author TEXT,
  language TEXT NOT NULL DEFAULT 'en',
  source_format TEXT NOT NULL,
  source_bytes_size INTEGER NOT NULL DEFAULT 0,
  total_pages INTEGER NOT NULL,
  cover_path TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  page_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  tokens_gz BLOB NOT NULL,      -- gzip(json(tokens))
  units_gz BLOB NOT NULL,       -- gzip(json(units))
  images_gz BLOB NOT NULL,      -- gzip(json(images positions))
  UNIQUE(book_id, page_index)
);
CREATE INDEX idx_pages_book ON pages(book_id);
```

`cover_path` — относительный путь в `data/covers/<book_id>.<ext>`.

### 2. Функции storage

```python
def book_save(parsed: ParsedBook) -> int: ...   # возвращает book_id
def book_meta(book_id: int) -> BookMeta | None: ...
def book_list() -> list[BookMeta]: ...
def book_delete(book_id: int) -> None: ...
def page_load(book_id: int, page_index: int) -> Page | None: ...
def pages_load_slice(book_id: int, offset: int, limit: int) -> list[Page]: ...
```

`book_save` транзакционно:
1. INSERT в books, получить id.
2. INSERT батч pages.
3. INSERT картинки (если были в parsed — M12) через `image_save(book_id, ...)`.
4. Сохранить обложку на диск `data/covers/<id>.<ext>`, обновить `cover_path`.
   - На M8 у нас нет обложек (они появятся с парсерами M12). Пропустить шаг.

### 3. Сжатие tokens/units/images

```python
import gzip, json
def _pack(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode("utf-8"), compresslevel=6)
def _unpack(data: bytes):
    return json.loads(gzip.decompress(data).decode("utf-8"))
```

### 4. Dataclass `ParsedBook`

На этой вехе ещё нет парсеров, но `ParsedBook` — общий dataclass, через него идёт и seed, и uploads:

```python
@dataclass
class ParsedBook:
    title: str
    author: str | None
    language: str
    source_format: str          # "txt" | "fb2" | "epub"
    source_bytes_size: int
    text: str                   # исходный текст с вставленными IMG-маркерами
    images: list[ParsedImage]   # картинки (mime, data, оригинальное имя)
    cover: ParsedImage | None   # обложка

@dataclass
class ParsedImage:
    image_id: str               # уже сгенерирован
    mime_type: str
    data: bytes
```

Создать в `src/en_reader/parsers/__init__.py`.

### 5. Пайплайн `book_save`

```python
def book_save(parsed: ParsedBook) -> int:
    tokens, units = analyze(parsed.text)
    pages = chunk(tokens, units, parsed.text, images=parsed.images)
    # pages — list[Page], у каждой page.images проставлены (см. M7)

    conn = get_db()
    with conn:
        cur = conn.execute(
            "INSERT INTO books(title, author, language, source_format, source_bytes_size, total_pages, cover_path, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (parsed.title, parsed.author, parsed.language, parsed.source_format,
             parsed.source_bytes_size, len(pages), None, datetime.utcnow().isoformat())
        )
        book_id = cur.lastrowid
        for p in pages:
            conn.execute(
                "INSERT INTO pages(book_id, page_index, text, tokens_gz, units_gz, images_gz)"
                " VALUES(?,?,?,?,?,?)",
                (book_id, p.page_index, p.text, _pack([asdict(t) for t in p.tokens]),
                 _pack([asdict(u) for u in p.units]), _pack(p.images))
            )
        for img in parsed.images:
            image_save(book_id, img.image_id, img.mime_type, img.data)
        # cover — в M12
    return book_id
```

### 6. Переделка seed-скрипта

`scripts/seed.py` (новый, вместо старого build_demo):
- Вход: путь к .txt.
- Строит `ParsedBook` (для txt — title = имя файла, author=None, images=[], cover=None, text — содержимое файла + пара вставленных IMG-маркеров + картинки в images).
- Вызывает `book_save(parsed)`.
- Удаляет `demo.json` если он ещё есть.

### 7. Cascade-удаление

`book_delete(book_id)`:
```python
with conn:
    conn.execute("DELETE FROM book_images WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM pages WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM books WHERE id=?", (book_id,))
    # cover file — удалить с диска
```

(На M8 `reading_progress` ещё нет; она появится в M10.1 и тоже должна каскадиться. В M10 добавляй туда `ON DELETE CASCADE` и удалять в `book_delete` не нужно.)

### 8. Тесты `tests/test_books_storage.py`

- `book_save` → в `books` одна строка, в `pages` N строк.
- `pages_load_slice(book_id, 0, 5)` возвращает первые 5 страниц в правильном порядке.
- `pages_load_slice` с offset=`total_pages-1`, limit=10 — одна страница.
- Инвариант: `"\n\n".join(p.text for p in loaded_pages) == parsed.text.rstrip()`.
- `book_delete` удаляет все pages и book_images.
- Повторный save той же книги (один seed дважды) — две независимые книги (разные id). Дедуп — задача для V2.

---

## Технические детали и ловушки

- **Compression compresslevel=6** — баланс скорости/размера. 9 медленнее.
- **BLOB размер**. tokens_gz для страницы ~5 кБ (был ~50 кБ несжатый). Для книги 200 страниц — ~1 МБ. Приемлемо.
- **Транзакция `with conn:`**. Любое исключение — rollback.
- **Порядок миграций**. v2→v3 ставит FK `pages.book_id REFERENCES books`. В v1→v2 `book_images` ссылался на `book_id` без FK — норм, потому что FK-constraint на старых таблицах применяются только если `PRAGMA foreign_keys=ON` был включён при создании. Чтобы не делать лишние миграции на этом этапе, оставь как есть.
- **`ON DELETE CASCADE`** для pages работает только если `PRAGMA foreign_keys=ON`. В `get_db()` мы это включаем.

---

## Acceptance

- [ ] Миграция v2→v3 применяется, создаются `books` и `pages`.
- [ ] `python scripts/seed.py tests/fixtures/golden/05-complex.txt` создаёт запись книги с правильным `total_pages`.
- [ ] `pages_load_slice` возвращает страницы в порядке page_index.
- [ ] Tokens/units в загруженных страницах совпадают с тем, что дало `analyze`.
- [ ] Инвариант восстановления текста зелёный.
- [ ] `book_delete` каскадирует правильно (тест).
- [ ] `demo.json` удалён, в `app.py` роут `/api/demo` удалён (или временно оставлен с FIXME — заменится в M8.2).
- [ ] `ruff`/`black` зелёные, тесты старые не ломаются.

---

## Что сдавать

- Ветка `task/M8-1-books-pages-persistence`, PR в main.

---

## Что НЕ делать

- Не добавляй `user_id` (M11.1).
- Не делай API `GET /api/books/{id}/content` — это **M8.2**.
- Не реализуй парсеры fb2/epub (**M12**). Для seed используй только txt.
- Не трогай фронт — он пока жив на `/api/demo`; заменим в M8.2.
