# Задача M12.2 — Парсер FB2

**Размер.** M (~2 дня)
**Зависимости.** M7.1 (маркер-формат картинок), M8.1 (`ParsedBook`, `ParsedImage`).
**Что строится поверх.** M12.4 (upload).

---

## О проекте (контекст)

**en-reader** — веб-читалка. FB2 — популярный в рунете формат русских книг и нередко сборников английских. Это XML с разметкой, встроенными картинками (base64) и обложкой в `description`. Нужно:
- Извлечь весь visible-текст в порядке следования.
- Inline-картинки из `<image l:href="#id"/>` оставить в тексте как маркеры `IMG<hex>`, а байты отдать через `ParsedBook.images`.
- Обложку извлечь отдельно (она не должна дублироваться в тексте).
- Распарсить title и author из `description/title-info`.

---

## Что нужно сделать

Функция `parse_fb2(data: bytes, filename: str) -> ParsedBook`.

---

## Что входит

### 1. Зависимость `lxml`

`lxml` — быстрый XML-парсер. Добавь в `pyproject.toml`.

### 2. Структура FB2

Упрощённо:
```xml
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
             xmlns:l="http://www.w3.org/1999/xlink">
  <description>
    <title-info>
      <book-title>The Title</book-title>
      <author>
        <first-name>John</first-name>
        <last-name>Doe</last-name>
      </author>
      <coverpage>
        <image l:href="#cover.jpg"/>
      </coverpage>
      <lang>en</lang>
    </title-info>
  </description>
  <body>
    <section>
      <p>Paragraph 1 with <image l:href="#img001"/> inline image.</p>
      <p>Paragraph 2.</p>
    </section>
  </body>
  <binary id="cover.jpg" content-type="image/jpeg">BASE64...</binary>
  <binary id="img001" content-type="image/png">BASE64...</binary>
</FictionBook>
```

### 3. Алгоритм

```python
def parse_fb2(data: bytes, filename: str) -> ParsedBook:
    from lxml import etree
    import base64

    NS = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0",
          "l": "http://www.w3.org/1999/xlink"}

    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as e:
        raise UnsupportedFormatError(f"invalid FB2 XML: {e}")

    # 1. Metadata.
    title_node = root.find(".//fb:description/fb:title-info/fb:book-title", NS)
    title = (title_node.text or "").strip() if title_node is not None else Path(filename).stem
    author_nodes = root.findall(".//fb:description/fb:title-info/fb:author", NS)
    author = _format_authors(author_nodes)
    lang_node = root.find(".//fb:description/fb:title-info/fb:lang", NS)
    language = (lang_node.text or "en").strip() if lang_node is not None else "en"

    # 2. Binaries → dict id→(mime, bytes).
    binaries = {}
    for b in root.findall(".//fb:binary", NS):
        bid = b.get("id")
        mime = b.get("content-type", "application/octet-stream")
        try:
            binaries[bid] = (mime, base64.b64decode(b.text or ""))
        except Exception:
            pass

    # 3. Cover.
    cover = None
    cover_node = root.find(".//fb:description/fb:title-info/fb:coverpage/fb:image", NS)
    if cover_node is not None:
        href = cover_node.get("{http://www.w3.org/1999/xlink}href", "").lstrip("#")
        if href in binaries:
            mime, data_bytes = binaries[href]
            cover = ParsedImage(image_id=new_image_id(), mime_type=mime, data=data_bytes)

    # 4. Body — пройти по всем текстовым нодам + inline images.
    text_parts = []
    inline_images: list[ParsedImage] = []
    used_in_text_ids = set()

    for body in root.findall(".//fb:body", NS):
        _walk_body(body, NS, text_parts, inline_images, binaries, used_in_text_ids, cover_href=(cover_node.get("{http://www.w3.org/1999/xlink}href", "").lstrip("#") if cover_node is not None else None))

    text = "\n\n".join(text_parts)

    return ParsedBook(
        title=title, author=author, language=language,
        source_format="fb2", source_bytes_size=len(data),
        text=text, images=inline_images, cover=cover,
    )

def _walk_body(elem, NS, text_parts, inline_images, binaries, used_ids, cover_href):
    """Обходит элементы body в порядке следования, собирает параграфы."""
    for node in elem.iter():
        tag = etree.QName(node).localname
        if tag == "p":
            paragraph = _flatten_paragraph(node, NS, inline_images, binaries, cover_href)
            if paragraph.strip():
                text_parts.append(paragraph)

def _flatten_paragraph(p, NS, inline_images, binaries, cover_href) -> str:
    buf = []
    if p.text:
        buf.append(p.text)
    for child in p:
        ctag = etree.QName(child).localname
        if ctag == "image":
            href = child.get("{http://www.w3.org/1999/xlink}href", "").lstrip("#")
            if href == cover_href:
                # пропустить дубль обложки внутри текста
                pass
            elif href in binaries:
                mime, data_bytes = binaries[href]
                img_id = new_image_id()
                inline_images.append(ParsedImage(image_id=img_id, mime_type=mime, data=data_bytes))
                buf.append(f"IMG{img_id}")
        elif ctag in {"emphasis", "strong"}:
            buf.append(_flatten_paragraph(child, NS, inline_images, binaries, cover_href))
        else:
            if child.text:
                buf.append(child.text)
        if child.tail:
            buf.append(child.tail)
    return "".join(buf)

def _format_authors(author_nodes) -> str | None:
    names = []
    for a in author_nodes:
        fn = a.find(".//fb:first-name", {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"})
        ln = a.find(".//fb:last-name", {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"})
        parts = [(fn.text or "").strip() if fn is not None else "",
                 (ln.text or "").strip() if ln is not None else ""]
        name = " ".join(p for p in parts if p)
        if name:
            names.append(name)
    return ", ".join(names) if names else None
```

Код выше — скетч. Приведи его в чистый рабочий вид.

### 4. Тесты `tests/test_parser_fb2.py`

Фикстура `tests/fixtures/parsers/sample.fb2` — маленькая книга (~5 КБ) с:
- Title «Sample Book», Author «John Doe».
- Обложкой (PNG 10x10 base64).
- Двумя inline-картинками в тексте.
- 3–4 параграфами.

Тесты:
- `parse_fb2(data, "sample.fb2")` возвращает ParsedBook.
- `title == "Sample Book"`, `author == "John Doe"`, `language == "en"`.
- `cover` не None, с корректным mime.
- `len(images) == 2`.
- `text` содержит ровно 2 маркера `IMG<hex>`.
- Обложка НЕ дублируется в text (инвариант).
- Некорректный XML → `UnsupportedFormatError`.

---

## Технические детали и ловушки

- **Namespaces** в FB2 — используй NS-map.
- **xlink:href** — через `{http://www.w3.org/1999/xlink}href`.
- **Обложка в binary с тем же id, что указан в coverpage**. Собираем binary → dict, затем cover href → lookup.
- **Inline-эмфазис** (`<emphasis>`, `<strong>`) — не важен для нас, просто вытаскиваем текст. Можно рекурсивно собрать.
- **Пустые `<p>`** — игнорируй.
- **`etree.fromstring` vs `etree.parse`** — первое для bytes.

---

## Acceptance

- [ ] Парсер возвращает корректный ParsedBook на фикстуре.
- [ ] Инвариант «маркеры в text == images».
- [ ] Обложка извлечена отдельно, не в тексте.
- [ ] Невалидный XML → UnsupportedFormatError.
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M12-2-parser-fb2`, PR в main.

---

## Что НЕ делать

- Не пытайся парсить `<image>` как `<img>` HTML — это XML, свой формат.
- Не делай fallback на HTML-парсер.
- Не нормализуй текст «в книжный вид» (quote marks, dashes) — оставляй как есть.
