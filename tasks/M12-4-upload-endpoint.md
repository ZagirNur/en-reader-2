# Задача M12.4 — Upload endpoint + UI загрузки

**Размер.** M (~2 дня)
**Зависимости.** M12.1, M12.2, M12.3, M11.3, M9.2 (карточка `+`).
**Что строится поверх.** Конец M12 — пользователь может загружать книги реально.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь кликает на карточку `+` → выбирает файл → ждёт 5–30 секунд → книга открыта. Если что-то пошло не так — понятная ошибка.

Pipeline: upload → dispatch parser → NLP → chunker → save to DB.

---

## Что нужно сделать

Роут `POST /api/books/upload`, диспетчер парсеров, UI загрузки с прогресс-скелетоном и ошибками.

---

## Что входит

### 1. Диспетчер парсеров

```python
def parse_book(data: bytes, filename: str) -> ParsedBook:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "txt":
        return parse_txt(data, filename)
    if ext == "fb2":
        return parse_fb2(data, filename)
    if ext == "epub":
        return parse_epub(data, filename)
    # Magic bytes fallback (на случай неправильного расширения)
    if data.startswith(b"PK"):                    # zip — potentially epub
        try:
            return parse_epub(data, filename)
        except UnsupportedFormatError:
            pass
    if data.lstrip()[:100].startswith(b"<?xml"):  # xml — potentially fb2
        try:
            return parse_fb2(data, filename)
        except UnsupportedFormatError:
            pass
    raise UnsupportedFormatError(f"unsupported format: {ext}")
```

### 2. Роут

```python
MAX_UPLOAD_BYTES = 200 * 1024 * 1024   # 200 MB

@app.post("/api/books/upload")
async def upload_book(file: UploadFile, user: User = Depends(get_current_user)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (max 200 MB)")
    if len(data) == 0:
        raise HTTPException(400, "empty file")

    try:
        parsed = parse_book(data, file.filename or "book")
    except UnsupportedFormatError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("parse failed")
        raise HTTPException(400, "failed to parse book")

    try:
        book_id = storage.book_save(user.id, parsed)
    except Exception:
        logger.exception("book_save failed")
        raise HTTPException(500, "failed to save book")

    meta = storage.book_meta(book_id)
    return {
        "book_id": book_id,
        "title": meta.title,
        "total_pages": meta.total_pages,
    }
```

### 3. Обложки на диск

- `book_save` теперь получает `ParsedBook` с `cover` — если не None, сохранить в `data/covers/<book_id>.<ext>` (расширение по mime) и обновить `cover_path`.
- `.gitignore` на `data/covers/`.

### 4. UI: клик по карточке `+`

В `renderLibrary()`:
```js
const addCard = document.querySelector(".add-card");
addCard.addEventListener("click", () => {
  const input = document.createElement("input");
  input.type = "file";
  // НЕ ставим accept — iOS Safari режет fb2
  input.style.display = "none";
  input.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) uploadBook(file);
  });
  document.body.appendChild(input);
  input.click();
});
```

### 5. `uploadBook(file)`

```js
async function uploadBook(file) {
  // скелетон-карточка в state.books
  state.uploadingFilename = file.name;
  render();

  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch("/api/books/upload", {method: "POST", body: form});
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({detail: `${resp.status}`}));
      throw new Error(err.detail || resp.statusText);
    }
    const {book_id, title} = await resp.json();
    state.uploadingFilename = null;
    // Обновить список книг.
    const books = await apiGet("/api/books");
    state.books = books;
    navigate(`/books/${book_id}`);
  } catch (e) {
    state.uploadingFilename = null;
    toast(`Не удалось загрузить: ${e.message}`);
    render();
  }
}
```

### 6. Скелетон загружающейся карточки

В renderLibrary — если `state.uploadingFilename`, перед add-card вставить:
```html
<div class="card uploading">
  <div class="cover-placeholder"><div class="spinner"></div></div>
  <div class="meta">
    <div class="title">Загружается…</div>
    <div class="author">${filename}</div>
  </div>
</div>
```

### 7. Стили

```css
.card.uploading { opacity: 0.7; pointer-events: none; }
.spinner { width: 24px; height: 24px; border: 3px solid #ddd; border-top-color: #3b82f6; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
```

### 8. Тесты `tests/test_upload.py`

Мокаем NLP / БД для скорости (или используем маленькие фикстуры):
- POST txt-файла → 200, book_id, total_pages ≥ 1.
- POST fb2-файла → 200, images сохранились.
- POST epub-файла → 200.
- POST .pdf → 400 (unsupported).
- POST пустого файла → 400.
- POST 250 MB файла → 413.
- POST кривого fb2 (битый XML) → 400, в БД ничего не записалось (атомарность).
- POST без авторизации → 401.

### 9. Ручная проверка

- Загрузи настоящую книгу fb2 с картинками → открылась, текст читается, картинки в тексте, обложка на карточке.
- Загрузи битый файл → toast «Не удалось загрузить…».

---

## Технические детали и ловушки

- **Нет атрибута `accept`**. На iOS Safari атрибут `accept="text/plain,.fb2,.epub"` блокирует выбор fb2 (mime fb2 не стандартизирован). Просто пропусти `accept`.
- **MAX_UPLOAD_BYTES**. FastAPI/Starlette сам не ограничивает размер — это в ответственности uvicorn + middleware. Дополнительная проверка в роуте — защита.
- **Атомарность.** `book_save` должен быть полностью в транзакции. Если какая-то картинка не сохранилась — rollback книги, pages, предыдущих картинок.
- **Время парсинга**. Большая fb2 (10 МБ) может парситься 10+ секунд. Это синхронный запрос — пользователь видит спиннер.
- **Обложка на диск**. Если файловая система read-only — тест в проде покажет. В dev — проверь `data/covers/` доступность.

---

## Acceptance

- [ ] Upload txt/fb2/epub работает end-to-end, книга сразу открывается.
- [ ] 250 MB → 413 с понятным сообщением.
- [ ] Битый fb2 → 400, БД чистая.
- [ ] Без авторизации → 401.
- [ ] Скелетон-карточка появляется и исчезает корректно.
- [ ] Тосты с ошибками.
- [ ] Обложка отображается на карточке после загрузки.
- [ ] Все тесты зелёные.

---

## Дизайн

Добавить в библиотеку карточку-скелетон во время upload — используй токены `.card` + иконку `spinner` (см. [`design-spec.md`](./_assets/design/design-spec.md)).

Если книга пришла **без обложки** — использовать один из 7 градиентных пресетов `.cover.c-olive | c-clay | c-ink | c-mauve | c-mustard | c-sage | c-rose`. Выбор пресета детерминированный: `hash(book_id) % 7` — так каждая книга всегда отображается в одном и том же цвете. Бэк возвращает поле `cover_preset: "c-olive"` в `/api/books` когда реальной обложки нет. Обновить схему БД тут не нужно — поле вычисляется из id на лету.

На самой обложке — `Instrument Serif` `ct` (title) и `ca` (author uppercase 8 px).

---

## Что сдавать

- Ветка `task/M12-4-upload-endpoint`, PR в main.
- Скриншот: библиотека с загруженной книгой + обложкой; скриншот reader со страницы с картинкой.

---

## Что НЕ делать

- Не добавляй progress для upload (сложно и излишне для MVP).
- Не разбирай zip-архивы с несколькими книгами.
- Не пытайся детектировать дубликаты книг (V2).
