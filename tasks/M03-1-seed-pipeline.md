# Задача M3.1 — Seed-пайплайн: текст → демо-фикстура

**Размер.** S (~1 день)
**Зависимости.** M1.1–M1.5, M2.1.
**Что строится поверх.** M3.2 (фронт качает `/api/demo`), M3.3 (рендер), M4 (клик → LLM).

---

## О проекте (контекст)

**en-reader** — веб-читалка. На этой стадии у нас нет БД, нет загрузки книг, нет мульти-пользователей. Нужен самый быстрый способ пропустить разметку через реальный фронт: взять хардкод-английский текст, прогнать через NLP + chunker, отдать как JSON одному эндпоинту.

Это временная схема «только на M3-M4», которая будет заменена в M8 на настоящий API книг.

---

## Что нужно сделать

Скрипт + эндпоинт: строит demo-фикстуру из англ.txt и отдаёт её фронту.

---

## Что входит

### 1. Скрипт `scripts/build_demo.py`

- Вход: путь к .txt (абсолютный или относительно корня репо).
- Действия:
  1. Прочитать файл (UTF-8).
  2. Прогнать через `analyze(text)` → `(tokens, units)`.
  3. Прогнать через `chunk(tokens, units, text)` → `list[Page]`.
  4. Сериализовать в JSON структуру:
     ```
     {
       "total_pages": N,
       "pages": [
         {
           "page_index": 0,
           "text": "...",
           "tokens": [{...}],
           "units": [{...}]
         },
         ...
       ]
     }
     ```
  5. Записать в `src/en_reader/static/demo.json`.
- Запуск: `python scripts/build_demo.py path/to/book.txt`.

### 2. FastAPI-скелет

- Добавить зависимости в `pyproject.toml`: `fastapi`, `uvicorn[standard]`.
- Файл `src/en_reader/app.py`:
  - Создать `FastAPI()`.
  - Смонтировать статику: `/static/*` → `src/en_reader/static/`.
  - Роут `GET /` → отдаёт `static/index.html` (файл появится в 3.2, пока можно положить пустой HTML).
  - Роут `GET /api/demo` → читает `static/demo.json` и возвращает его содержимое.

### 3. Запуск

- В `README.md` добавить:
  ```
  # dev
  python scripts/build_demo.py tests/fixtures/long.txt
  uvicorn en_reader.app:app --reload --port 8000
  # открыть http://localhost:8000
  ```

### 4. Тесты `tests/test_demo_endpoint.py`

- Запустить тестовый клиент FastAPI (`from fastapi.testclient import TestClient`).
- Предварительно сгенерить demo.json (через фикстуру pytest: вызвать `build_demo.main("tests/fixtures/golden/01-simple.txt")`).
- `GET /api/demo` возвращает 200, тело — валидный JSON с полями `total_pages`, `pages`.
- Проверить, что `total_pages == len(pages)`.

### 5. Заглушка `index.html`

- `src/en_reader/static/index.html`:
  ```html
  <!DOCTYPE html>
  <html lang="ru">
  <head><meta charset="utf-8"><title>en-reader</title></head>
  <body><div id="root">loading...</div></body>
  </html>
  ```
- Без JS/CSS пока — это задача 3.2.

---

## Технические детали и ловушки

- **Сериализация dataclass-ов.** `dataclasses.asdict(x)` даст dict, который pymарshals в JSON. Для вложенных — работает. Проверь, что все значения JSON-safe (int, str, bool, None, list, dict).
- **Размер demo.json.** Для книги в 50 000 слов JSON будет ~5–10 МБ. Это ок для локального dev; для продакшн БД в M8 будет разбиение по страницам.
- **`StaticFiles` из FastAPI** — используй `app.mount("/static", StaticFiles(directory="src/en_reader/static"), name="static")`.
- **Корневой `/` vs `/static/`**: `/` должен отдавать `index.html`, а не 404. Явный роут `@app.get("/")` возвращает `FileResponse("src/en_reader/static/index.html")`.
- **Путь к `demo.json`**. Используй `Path(__file__).parent / "static" / "demo.json"` внутри `app.py` — иначе скрипт сломается при запуске из другой директории.

---

## Acceptance

- [ ] `python scripts/build_demo.py tests/fixtures/golden/01-simple.txt` создаёт валидный `src/en_reader/static/demo.json`.
- [ ] `uvicorn en_reader.app:app` запускается без ошибок.
- [ ] `curl http://localhost:8000/api/demo` возвращает JSON с `total_pages > 0`.
- [ ] `curl http://localhost:8000/` возвращает HTML-заглушку.
- [ ] Тесты `test_demo_endpoint.py` зелёные.
- [ ] README обновлён.

---

## Что сдавать

- Ветка `task/M3-1-seed-pipeline`, PR в main.

---

## Что НЕ делать

- Никакой БД (M8).
- Никакого фронтового рендера страниц (M3.3).
- Никакого апи переводов (M4).
- Никакой авторизации (M11).
- Не добавляй "/api/books/..." роуты — они появятся в M8.
