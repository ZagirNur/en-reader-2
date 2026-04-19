# Задача M16.5 — Каталог: seed-книги + экран «Каталог»

**Размер.** M (~2 дня)
**Зависимости.** M8.1 (books/pages), M16.1 (tokens), M16.2 (tabbar).
**Что строится поверх.** Новым пользователям есть что читать сразу после регистрации.

---

## О проекте (контекст)

**en-reader** — веб-читалка. На старте у пользователя пустая библиотека. Чтобы не принуждать его сразу грузить свой файл, даём **каталог предзагруженных public-domain книг** (Project Gutenberg): несколько десятков классических английских произведений с пометкой уровня (A1..C1) и тегами «короткое», «по твоему уровню».

Каталог — ещё одна из 4 вкладок таб-бара. Клик по книге в каталоге → копирование в личную библиотеку пользователя.

---

## Что нужно сделать

1. Seed-скрипт, который скачивает/берёт из фикстур ~20 книг Gutenberg и кладёт в отдельную схему как «каталог».
2. API каталога + «добавить в мою библиотеку».
3. Экран «Каталог».

---

## Что входит

### 1. Миграция v6 → v7

```sql
CREATE TABLE catalog_books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  author TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'en',
  level TEXT NOT NULL,                 -- 'A1' | 'A2' | 'B1' | 'B2' | 'C1'
  pages INTEGER NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',     -- JSON array: ['short', 'classic', 'beginner']
  cover_preset TEXT NOT NULL,          -- 'c-olive' etc.
  source_url TEXT,                     -- для атрибуции (Gutenberg ID)
  created_at TEXT NOT NULL
);

-- reference на файл/хранилище полного текста.
-- Простейший вариант: файлы лежат на диске data/catalog/<id>.txt,
-- и при копировании в личную библиотеку — парсятся через существующий pipeline.
```

### 2. Seed-скрипт `scripts/seed_catalog.py`

Загружает (или берёт из `data/catalog/sources/`) ~20 текстов Project Gutenberg, парсит их через `parse_txt`, анализирует (для подсчёта `pages` — прогоняет через NLP + chunker), сохраняет в `catalog_books`. Тексты держатся на диске для последующего импорта.

Минимальный список (уровни — ориентировочные):
- A1: «The Tale of Peter Rabbit», «The Velveteen Rabbit».
- A2: «The Happy Prince», «The Selfish Giant».
- B1: «Animal Farm», «The Hobbit» (первые главы), «The Little Prince» (EN).
- B2: «The Old Man and the Sea», «1984», «The Great Gatsby», «Of Mice and Men», «Fahrenheit 451».
- C1: «Pride and Prejudice», «Norwegian Wood» (если доступен PG).
- Short: «Flowers for Algernon», «The Yellow Wallpaper», «The Lottery».

Всё — public domain. Указывать `source_url`.

Скрипт запускается **один раз на проде** (идемпотентный — skip если `title+author` уже есть).

### 3. API

- `GET /api/catalog` → сгруппировано по секциям:
  ```
  {
    "sections": [
      {
        "key": "По твоему уровню",
        "items": [
          {"id": 1, "title": "...", "author": "...", "level": "B1", "pages": 112, "cover_preset": "c-sage"},
          ...
        ]
      },
      {"key": "Короткое — за выходные", "items": [...]}
    ]
  }
  ```
  На сервере: «По твоему уровню» = книги с level в пределах ±1 от уровня пользователя (уровня ещё нет — B1 по умолчанию; хранится в users.level когда введём — в этой задаче просто hardcode B1 как default). «Короткое» = книги с тегом `short`.
- `POST /api/catalog/{id}/import` → 200 `{book_id: N}`. Копирует caталог-книгу в личную библиотеку пользователя (тот же pipeline что upload: parse → analyze → chunk → save_book). Дедуп по title+author.
- `GET /api/catalog/{id}/cover` → returns preset-градиент как SVG (если нет реальной обложки) или настоящий файл.

### 4. Экран «Каталог»

Структура (см. `ScreenCatalog` в прототипе):
- `.uplabel "Каталог"` + `h1 "Что почитать"`.
- Row of level chips `A1 A2 B1 B2 C1` — по умолчанию выбран уровень пользователя.
- Секции по `sections` из API — каждая:
  - `.uplabel` с key секции.
  - Horizontal-scroll row карточек (110 px width, flex-shrink: 0):
    - Обложка с градиентом.
    - Title (12 px 600).
    - `level · N стр.` (10 px `var(--ink-2)`).
- Клик по карточке → POST `/api/catalog/{id}/import` → toast «Добавлено в библиотеку» → через 0.5 с переход в `/books/{new_id}`.

### 5. User-level фильтр chip

- Клик по chip A1/A2/B1/B2/C1 фильтрует секции (или же всегда показывает всё, chip — чисто для секции «По твоему уровню»).
- Proстейший MVP: chip запоминается в `users.preferred_level`, секция пересчитывается.

### 6. Тесты

- Миграция v6→v7 + миграция catalog_books.
- Seed-скрипт на 2 фикстурных файлах.
- `GET /api/catalog` возвращает секции.
- `POST /api/catalog/{id}/import` создаёт книгу в личной библиотеке.
- Повторный import той же книги даёт 409 или обновляет.
- Фронт-юнит на рендер карточки.

### 7. Ручная проверка

- Новый пользователь → библиотека пустая → таб «Каталог» → ≥ 20 книг видно.
- Клик «The Hobbit» → toast → reader открыт.
- В «Мои книги» — новая книга.

---

## Acceptance

- [ ] 20+ книг в `catalog_books` после seed.
- [ ] `GET /api/catalog` возвращает секции.
- [ ] Экран рендерится корректно.
- [ ] Import из каталога создаёт книгу.
- [ ] Повторный import не плодит дубли.
- [ ] Тесты зелёные.

---

## Дизайн

Эталон — [`prototype.html`](./_assets/design/prototype.html), функция `ScreenCatalog`.

---

## Что сдавать

- Ветка `task/M16-5-catalog-seed-and-screen`, PR в main.

---

## Что НЕ делать

- Не делай уровни по всем книгам перфектно — ориентировочно ОК.
- Не тащи copyright-ные книги.
- Не грузи сотни книг — 20 достаточно на MVP.
- Не делай поиск по каталогу — MVP.
