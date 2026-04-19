# Задача M7.1 — Inline-картинки в тексте

**Размер.** M (~2 дня)
**Зависимости.** M3.3 (рендер страниц), M6.1 (SQLite).
**Что строится поверх.** M12.2/M12.3 (парсеры fb2/epub будут вставлять маркеры картинок).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Книги fb2 и epub часто содержат иллюстрации — они должны отображаться внутри текста, в правильном месте. Решение: в тексте страницы в нужных позициях стоят **маркеры** формата `IMG<12-hex>`; фронт при рендере заменяет маркер на `<img>`. Картинки хранятся в таблице `book_images`.

Парсеры fb2/epub в M12 будут генерировать эти маркеры. Сейчас их нет — мы делаем **всё**, кроме парсеров: маркер-формат, таблицу, роут отдачи, фронт-рендер, и обновляем seed-скрипт, чтобы добавить пару тестовых картинок.

---

## Что нужно сделать

Подготовить инфраструктуру inline-картинок: маркер-формат, хранилище, API, фронт-рендер; протестировать на seed-фикстуре.

---

## Что входит

### 1. Формат маркера и утилиты

В `src/en_reader/models.py` или отдельно `images.py`:
```python
import re, secrets
IMAGE_MARKER_RE = re.compile(r"IMG[0-9a-f]{12}")
def new_image_id() -> str:
    return secrets.token_hex(6)   # 12 hex chars
```

### 2. Миграция v1 → v2

В `storage.py`:
```python
def _migrate_v1_to_v2(conn):
    conn.execute("""
      CREATE TABLE book_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER NOT NULL,
        image_id TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        data BLOB NOT NULL,
        UNIQUE(book_id, image_id)
      )
    """)
    conn.execute("CREATE INDEX idx_book_images_book ON book_images(book_id)")
```

Решение «BLOB vs файл на диске»: **BLOB** — проще бэкап (один .db-файл), размер книги в пределах разумного. Если в будущем будут огромные иллюстрации — переедем.

### 3. Storage-методы

```python
def image_save(book_id: int, image_id: str, mime_type: str, data: bytes) -> None: ...
def image_get(book_id: int, image_id: str) -> tuple[str, bytes] | None: ...  # (mime, data)
```

На M7 у нас ещё нет таблицы `books`, так что `book_id` будет для демо-книги — захардкодим константу `DEMO_BOOK_ID = 1` (она в v1→v2 миграции НЕ создаётся, просто используется как магическое число на M7; в M8.1 появится реальная таблица books).

Альтернатива — положить картинки без book_id, через nullable-поле. Не стоит — `book_id` нужен в будущем.

Рабочий вариант: в рамках M7 книгу представляем как псевдо-id=1 (вставится в seed). Запись в `books` делает M8.1.

### 4. Роут `GET /api/books/{book_id}/images/{image_id}`

```python
@app.get("/api/books/{book_id}/images/{image_id}")
def get_image(book_id: int, image_id: str):
    result = storage.image_get(book_id, image_id)
    if not result:
        raise HTTPException(404)
    mime, data = result
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

### 5. Обновление seed `scripts/build_demo.py`

- Добавить в фикстуру 1–2 картинки (кладём в `tests/fixtures/demo-images/` PNG или JPG публичных).
- В seed-пайплайне:
  1. Сгенерить `image_id` для каждой картинки.
  2. Вставить маркер `IMG<id>` в текст (в рамках фикстурного абзаца — в паре осмысленных мест, например, между параграфами).
  3. Сохранить файлы в БД через `image_save(DEMO_BOOK_ID, image_id, mime, data)`.
- В `/api/demo` — отдавать `book_id: 1` (чтобы фронт строил URL).

### 6. Фронт-рендер

В `renderPage()` при проходе по токенам:
- До основного цикла разбить `page.text` и токены. Проблема: маркер может быть частью одной токенизации. В реальности маркер `IMG<hex>` может попасть внутрь строки. Правильный подход:
  - **Seed-пайплайн не пропускает маркер через токенайзер**. Маркер — это не слово. Лучше: в `build_demo.py` картинки лежат в отдельной структуре `page.images: [{position: <char_idx в page.text>, image_id, mime_type}]`. В page.text остаётся маркер.
  - При рендере — собираем DOM по токенам **и** после каждого токена, если в диапазоне `[token.end, next_token.start]` содержится маркер → вставляем `<img>` в этом месте.

Простейший альтернативный путь: в рендере finished-page делать последний проход по `page-body.innerHTML` и заменять `IMG<hex>` на `<img src="...">`. **Не делай так** — ломает сохранность translatable-span'ов. Используй первый путь (позиции).

### 7. Стили

```css
.inline-image {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1rem auto;
  border-radius: 4px;
}
```

### 8. Тесты

- `tests/test_images.py`:
  - `image_save` → `image_get` возвращает те же данные.
  - `GET /api/books/1/images/<id>` возвращает 200 с correct MIME и Cache-Control.
  - `GET /api/books/1/images/<несуществующий>` → 404.
- Инвариантный тест: число маркеров в `page.text` == длина `page.images`.

### 9. Ручная проверка

- Открываем `/reader` → видим фикстурный текст + картинки внутри.
- Network tab: картинка качается один раз, далее — из кэша (Cache-Control).

---

## Технические детали и ловушки

- **Маркер в токенах.** Если в `build_demo.py` картинка попала в `text` до токенайзера — spaCy разрежет маркер на токены (`IMG`, `abc...`). **Это плохо** — маркер не должен токенизироваться. Подход:
  - В seed-пайплайне сначала удали маркеры из текста, записав их позиции → прогони через NLP + chunker → в каждой `Page` восстанови `page.images` из позиций, которые попали в эту страницу.
  - Или: перед разметкой заменяй маркер на неразрывный плейсхолдер, потом восстанавливай.
  Самый надёжный: убрать маркеры, запомнить `(char_pos, image_id, mime)`, разметить очищенный текст, после чанкинга пересчитать позиции маркеров относительно каждой страницы.
- **Размер картинок в SQLite.** BLOB до нескольких МБ — нормально. Не качай огромные оригиналы.
- **MIME-детекция.** По расширению файла или magic bytes. Для seed — по расширению достаточно.
- **CSP.** `img-src 'self' data:` — в M14.2. Сейчас не ограничено.

---

## Acceptance

- [ ] Миграция v1→v2 применяется и создаёт `book_images`.
- [ ] `image_save` + `image_get` работают.
- [ ] Seed-фикстура содержит 1–2 картинки.
- [ ] В `/reader` картинки отображаются inline, в правильной позиции относительно текста.
- [ ] `GET /api/books/1/images/<id>` отдаёт корректный MIME и Cache-Control.
- [ ] Инвариантный тест «маркеры == images» зелёный.
- [ ] Ручной рефреш — картинка из disk cache (Network: 200 from disk cache или аналог).

---

## Что сдавать

- Ветка `task/M7-1-inline-images`, PR в main.
- Скриншот с картинкой внутри текста — в описании PR.

---

## Что НЕ делать

- Не пиши парсеры fb2/epub (**M12**).
- Не делай уменьшение размеров (resize/thumbnail) — отдавай оригинал; оптимизация потом.
- Не пиши таблицу `books` (M8.1) — используй константу DEMO_BOOK_ID на этой задаче.
- Не делай uploads API для картинок вручную — картинки попадают в БД только через seed (и потом в M12 через парсеры).
