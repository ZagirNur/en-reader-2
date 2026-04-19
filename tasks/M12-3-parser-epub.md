# Задача M12.3 — Парсер EPUB

**Размер.** M (~2 дня)
**Зависимости.** M7.1 (маркер), M8.1 (ParsedBook).
**Что строится поверх.** M12.4 (upload).

---

## О проекте (контекст)

**en-reader** — веб-читалка. EPUB — zip-архив с XHTML-файлами (по главам), манифестом и spine (порядок глав). Картинки — отдельные файлы внутри архива.

Трюк с EPUB: `<img>` внутри `<p>` при наивной замене через BeautifulSoup легко ломается. Например, `BeautifulSoup.replace_with(new_p)` создаст новый `<p>` внутри старого — получится двойной маркер, оба встанут в разные параграфы. Правильно — заменять `<img>` на `NavigableString` с маркером, чтобы он остался в родительском `<p>` ровно один раз.

---

## Что нужно сделать

Функция `parse_epub(data: bytes, filename: str) -> ParsedBook`.

---

## Что входит

### 1. Зависимости

- `ebooklib` — парсит EPUB-структуру (манифест, spine, items).
- `beautifulsoup4` + `lxml` — парсинг XHTML внутри.

### 2. Модуль `src/en_reader/parsers/epub.py`

```python
import io
from bs4 import BeautifulSoup, NavigableString
from ebooklib import epub, ITEM_DOCUMENT, ITEM_IMAGE
from pathlib import Path

def parse_epub(data: bytes, filename: str) -> ParsedBook:
    try:
        book = epub.read_epub(io.BytesIO(data))
    except Exception as e:
        raise UnsupportedFormatError(f"invalid EPUB: {e}")

    # 1. Metadata.
    title = _get_metadata(book, "title") or Path(filename).stem
    author = _get_metadata(book, "creator")
    language = _get_metadata(book, "language") or "en"

    # 2. Map image filenames -> (image_id, mime, bytes).
    image_map: dict[str, tuple[str, str, bytes]] = {}
    inline_images: list[ParsedImage] = []

    for item in book.get_items():
        if item.get_type() == ITEM_IMAGE:
            img_id = new_image_id()
            mime = item.media_type
            image_map[item.file_name] = (img_id, mime, item.content)
            # inline_images наполним только теми, что реально встретятся в тексте

    # 3. Cover.
    cover = _extract_cover(book, image_map)

    # 4. Текст по spine.
    text_parts = []
    used_image_ids = set()

    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if not item or item.get_type() != ITEM_DOCUMENT:
            continue
        chapter_text = _extract_chapter_text(item, image_map, inline_images, used_image_ids, cover_filename=cover.source_path if cover else None)
        if chapter_text.strip():
            text_parts.append(chapter_text)

    text = "\n\n".join(text_parts)

    return ParsedBook(
        title=title, author=author, language=language,
        source_format="epub", source_bytes_size=len(data),
        text=text, images=inline_images, cover=cover,
    )

def _get_metadata(book, key: str) -> str | None:
    m = book.get_metadata("DC", key)
    return m[0][0] if m else None

def _extract_cover(book, image_map) -> ParsedImage | None:
    # ebooklib: cover через meta name="cover"
    cover_item = book.get_item_with_id("cover") or None
    if cover_item and cover_item.get_type() == ITEM_IMAGE:
        return ParsedImage(
            image_id=new_image_id(),
            mime_type=cover_item.media_type,
            data=cover_item.content,
        )
    # Fallback: manifest с properties=cover-image
    for item in book.get_items():
        if item.get_type() == ITEM_IMAGE and "cover" in (item.id or "").lower():
            return ParsedImage(
                image_id=new_image_id(),
                mime_type=item.media_type,
                data=item.content,
            )
    return None

def _extract_chapter_text(item, image_map, inline_images, used_image_ids, cover_filename) -> str:
    soup = BeautifulSoup(item.get_content(), "lxml-xml")

    # Заменить <img> на NavigableString с маркером в родительском <p>.
    for img in soup.find_all("img"):
        src = img.get("src", "")
        src_resolved = _resolve_src(item.file_name, src)
        if src_resolved == cover_filename:
            img.decompose()
            continue
        if src_resolved in image_map:
            img_id, mime, content = image_map[src_resolved]
            if img_id not in used_image_ids:
                used_image_ids.add(img_id)
                inline_images.append(ParsedImage(image_id=img_id, mime_type=mime, data=content))
            img.replace_with(NavigableString(f"IMG{img_id}"))
        else:
            img.decompose()

    # Собрать текст параграфов.
    parts = []
    for p in soup.find_all(["p", "div", "h1", "h2", "h3"]):
        txt = p.get_text(" ", strip=True)
        if txt:
            parts.append(txt)
    return "\n\n".join(parts)

def _resolve_src(chapter_filename: str, src: str) -> str:
    """src — относительный путь из XHTML, chapter — где этот XHTML лежит.
    Возвращает полный путь относительно корня EPUB."""
    from pathlib import PurePosixPath
    chapter_dir = PurePosixPath(chapter_filename).parent
    return str((chapter_dir / src).as_posix()).lstrip("./")
```

Код-скелет; отшлифуй до рабочего состояния и покрой тестами.

### 3. Тесты `tests/test_parser_epub.py`

Фикстура `tests/fixtures/parsers/sample.epub` — маленький EPUB с:
- Metadata title/author/language.
- 2–3 главы (XHTML).
- Cover + 2 inline-картинки.

Тесты:
- `parse_epub(data, "sample.epub")` возвращает ParsedBook.
- `title`, `author`, `language` корректные.
- `cover` извлечён, mime верный.
- `len(images) == 2` (только те, что реально встречаются в тексте).
- text содержит ровно 2 маркера (инвариант).
- **Инвариант «один маркер на картинку»** — маркер не продублирован (это основная ловушка).
- Cover НЕ в тексте.
- Невалидный zip → UnsupportedFormatError.

---

## Технические детали и ловушки

- **`BeautifulSoup.replace_with(new_tag)` ломает структуру**. Если заменяешь `<img>` на `<p>IMG…</p>` — создаётся nested `<p>` внутри родительского `<p>`, при get_text() маркер может продублироваться. Используй `NavigableString(f"IMG{id}")` — это просто текстовая нода, без своего тега.
- **Путь к картинке**. В XHTML src бывает relative: `../images/fig1.png`. А item.file_name — полный путь внутри EPUB: `OEBPS/images/fig1.png`. Нужна resolve-логика.
- **Несколько раз один и тот же src**. Автор может вставить одну картинку в разных местах. Используй `used_image_ids` чтобы не дублировать в inline_images. В text — маркер будет тот же самый, несколько раз.
- **ebooklib warnings**: "In the future version we will turn default option ignore_ncx to True" — это не ошибка, просто предупреждение.

---

## Acceptance

- [ ] Парсер возвращает корректный ParsedBook на фикстуре.
- [ ] Инвариант «маркеры == images» зелёный.
- [ ] Cover извлечён, в тексте отсутствует.
- [ ] Один `<img>` → один маркер в результирующем тексте (не два).
- [ ] Невалидный epub → UnsupportedFormatError.
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M12-3-parser-epub`, PR в main.

---

## Что НЕ делать

- Не поддерживай DRM epub — падай с понятной ошибкой.
- Не фильтруй CSS — нас интересует только текст.
- Не пытайся извлечь TOC — не нужно (пользователь пролистывает).
