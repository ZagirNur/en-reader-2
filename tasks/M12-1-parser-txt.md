# Задача M12.1 — Парсер TXT

**Размер.** S (~1 день)
**Зависимости.** M8.1 (есть `ParsedBook`).
**Что строится поверх.** M12.4 (upload endpoint использует все парсеры).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь загружает книгу файлом — txt, fb2 или epub. Парсер по формату возвращает единую структуру `ParsedBook` (title, author, text, images, cover), которая дальше идёт в pipeline (analyze → chunker → save_book).

TXT — самый простой формат: просто текст. Сложность — в кодировке. Windows-1251 ещё встречается в русских фанфиках на английском, CP1252 — в старых западных файлах. Надо определять автоматически.

---

## Что нужно сделать

Функция `parse_txt(data: bytes, filename: str) -> ParsedBook`.

---

## Что входит

### 1. Зависимость `chardet`

В `pyproject.toml` добавить `chardet` или `charset-normalizer` (последний — современнее, предпочтительнее).

### 2. Модуль `src/en_reader/parsers/txt.py`

```python
from pathlib import Path
import charset_normalizer
from . import ParsedBook, UnsupportedFormatError

def parse_txt(data: bytes, filename: str) -> ParsedBook:
    # 1. Детект кодировки.
    result = charset_normalizer.from_bytes(data).best()
    if not result:
        raise UnsupportedFormatError("cannot detect encoding")
    text = str(result)

    # 2. Strip BOM.
    if text.startswith("\ufeff"):
        text = text[1:]

    # 3. Нормализация переносов строк.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 4. Title из имени файла.
    title = Path(filename).stem or "Untitled"

    return ParsedBook(
        title=title,
        author=None,
        language="en",
        source_format="txt",
        source_bytes_size=len(data),
        text=text,
        images=[],
        cover=None,
    )
```

### 3. Исключение `UnsupportedFormatError`

В `src/en_reader/parsers/__init__.py` (если ещё нет):
```python
class UnsupportedFormatError(Exception):
    pass
```

### 4. Тесты `tests/test_parser_txt.py`

- UTF-8 без BOM: `b"Hello world"` → `text == "Hello world"`.
- UTF-8 с BOM: `b"\xef\xbb\xbfHello"` → `text == "Hello"` (BOM снят).
- Windows-1251: байты русского текста → корректная кириллица в тексте (хотя это EN-reader, проверяем, что парсер не падает на валидных байтах любой кодировки).
- CP1252: байты с «smart quotes» → корректные символы.
- Пустой файл: `b""` → либо ParsedBook с пустым text, либо UnsupportedFormatError (выбери — лучше поднимать, пустая книга бессмысленна).
- `\r\n` и `\r` → только `\n` в результате.
- Title из filename без расширения: `"war_and_peace.txt"` → title `"war_and_peace"`.

### 5. Фикстуры

Подготовь файлы в `tests/fixtures/parsers/`:
- `sample_utf8.txt`, `sample_utf8_bom.txt`, `sample_cp1252.txt`, `sample_win1251.txt`.
- Короткие (~100 байт).

---

## Технические детали и ловушки

- **charset-normalizer vs chardet**. charset-normalizer — современнее, лучше на малых файлах. API: `charset_normalizer.from_bytes(data).best()` возвращает best guess.
- **Не угадывается?** Возьми utf-8 с `errors="replace"` как fallback. Или поднимай UnsupportedFormatError — зависит от политики. Рекомендую fallback на utf-8 с replace, чтобы пользователь получил читаемую книгу даже если парсер не уверен.
- **BOM**: `\ufeff` — это Zero Width No-Break Space, один символ. Strip его.
- **\r\n**: некоторые Windows-файлы. Нормализуй.

---

## Acceptance

- [ ] Все фикстуры парсятся корректно.
- [ ] Тесты зелёные.
- [ ] `source_bytes_size` — длина raw bytes, не len(text).
- [ ] `title` из filename.

---

## Что сдавать

- Ветка `task/M12-1-parser-txt`, PR в main.

---

## Что НЕ делать

- Не пиши fb2/epub (**12.2/12.3**).
- Не делай upload endpoint (**12.4**).
- Не пытайся парсить author из первой строки текста — это ненадёжно.
