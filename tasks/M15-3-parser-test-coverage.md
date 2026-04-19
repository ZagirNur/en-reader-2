# Задача M15.3 — Покрытие parsers

**Размер.** S (~1 день)
**Зависимости.** M12.1, M12.2, M12.3, M12.4.
**Что строится поверх.** Защита от регрессий парсинга при обновлении lxml/ebooklib.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Парсеры ходят на внешние форматы с капризной разметкой — lxml, ebooklib, charset_normalizer. При обновлении одной из этих библиотек легко получить сюрприз. Нужны фикстуры и тесты, покрывающие happy-path + ключевые edge cases.

---

## Что нужно сделать

Добить coverage парсеров ≥ 85%, привести все фикстурные кейсы.

---

## Что входит

### 1. Фикстуры в `tests/fixtures/parsers/`

- `sample_utf8.txt`, `sample_utf8_bom.txt`, `sample_cp1252.txt`, `sample_win1251.txt` (из M12.1).
- `sample.fb2` с 2 картинками и обложкой (из M12.2).
- `broken.fb2` — заведомо битый XML.
- `sample.epub` с 2 главами, 2 картинками, обложкой (из M12.3).
- `broken.epub` — просто ненулевые байты не-zip.
- `nested_img.epub` — специально сконструированная глава с `<p>` содержащим `<img>` внутри `<em><span>` вложений (проверка 1 маркер на картинку).
- `cover_in_text.fb2` — cover binary, но тоже ссылка из body (проверка дедупа).
- `multi_author.fb2` — два `<author>`.

### 2. test_parser_txt.py

Уже написан в M12.1. Проверь coverage, добавь:
- Файл > 10 МБ (без BOM, utf-8).
- Файл только из whitespace.
- Файл только из `\r` (старый Mac).

### 3. test_parser_fb2.py

(Из M12.2 расширить.)
- Happy path.
- Broken XML → UnsupportedFormatError.
- Отсутствует title-info → title = filename.
- Нет coverpage → cover=None.
- Multi-author → author объединён через «, ».
- cover_in_text: обложка в binary и упомянута ссылкой в body → cover извлечён, в text маркера НЕТ.
- Картинка на несуществующий binary → игнорируется без падения.

### 4. test_parser_epub.py

(Из M12.3 расширить.)
- Happy path.
- Broken epub → UnsupportedFormatError.
- nested_img фикстура: маркер ровно один.
- EPUB без cover → cover=None.
- EPUB с несколькими image в manifest, только часть на spine → inline_images содержит только реально встреченные.

### 5. test_upload_dispatcher.py

(Из M12.4 расширить.)
- Правильный extension — правильный парсер.
- Неправильный extension + правильные магические bytes → fallback.
- Ни то ни другое → UnsupportedFormatError / 400.

### 6. Coverage

Цель ≥ 85% для:
- `src/en_reader/parsers/txt.py`
- `src/en_reader/parsers/fb2.py`
- `src/en_reader/parsers/epub.py`
- Диспетчер (`parse_book`).

---

## Технические детали и ловушки

- **Генерация фикстур**. FB2 — сам XML, легко написать руками (short template). EPUB — сложнее; можно сгенерить через скрипт на `ebooklib` в `scripts/generate_epub_fixture.py`.
- **Коммит бинарных фикстур** — нормально, размер малый.
- **charset_normalizer**. На очень коротких файлах может путаться. Тесты с ≥ 100 байт текста.

---

## Acceptance

- [ ] Все фикстуры в репо.
- [ ] Coverage parsers ≥ 85%.
- [ ] broken-файлы → UnsupportedFormatError, не AttributeError/Exception.
- [ ] Инвариант маркеров на всех фикстурах.

---

## Что сдавать

- Ветка `task/M15-3-parser-test-coverage`, PR в main.

---

## Что НЕ делать

- Не тестируй сами lxml/ebooklib.
- Не ставь pdfparser (не поддерживаем).
