# en-reader — план реализации с нуля

Документ — **backlog для команды разработчиков**. Каждая задача — реальный тикет (0.5–3 дня работы, один PR, ясный acceptance). Задачи сгруппированы по вехам (milestones) в порядке реализации. Стандартные мелочи (`git init`, `.gitignore`, scaffolding, линтер) — часть первой задачи веха, а не отдельные пункты.

**Обозначения размера.** XS ≈ 0.5 дня · S ≈ 1 день · M ≈ 2 дня · L ≈ 3+ дня.

---

## Видение

**Проблема.** Читатель уровня B1–C1 хочет читать книги на английском, но внешние словари и переводчики разрывают поток. Kindle-словари показывают перевод вне контекста и плохо работают с фразовыми глаголами.

**Продукт.** Веб-читалка, в которой:
1. «Достойные перевода» слова и устойчивые выражения подчёркнуты.
2. Клик по английскому слову **заменяет его** русским переводом прямо на месте (не вставка рядом, не overlay). Выделяется акцентным цветом.
3. Повторный клик по переведённому (русскому) слову — **bottom sheet** с headword, IPA/POS, переводом, примером из книги, действиями «В словарь» / «Оригинал».
4. Переведённое раз слово **запоминается на уровне пользователя** и автоматически заменяется на перевод во всех будущих книгах — то же слово в книге Б появляется сразу на русском.
5. Фразовые глаголы — первого класса (включая разрывную форму `look the word up` — оба куска заменяются одновременно).
6. **Словарь** как отдельный экран: фильтры по статусу (new / learning / review / mastered), пример из книги, действия «Тренировать» / «Удалить».
7. **Тренировки** (Learn): выбор перевода (4 варианта) и flashcards; прогрессия слов между статусами; дневная цель и серия (streak).
8. **Каталог** предзагруженных public-domain книг с фильтром по уровню (A1..C1), импорт в личную библиотеку.
9. Приложение открывается точно там, где остановился пользователь.
10. Светлая / тёмная темы (editorial — оранжевый акцент, Geist + Instrument Serif).

**MVP перевода (V1).** Клик = одно слово, контекст = его предложение, ответ LLM = одна русская строка. `textContent` английского span'а заменяется на русский + класс `.translated` (акцентный цвет). Для split phrasal verb: оба span'а с общим `pair_id` получают один перевод одновременно. Батч-переводы страницы, merge-правила, sense-disambiguation — V2.

**Дизайн.** Эталон UI — [`tasks/_assets/design/prototype.html`](tasks/_assets/design/prototype.html); токены и компоненты — [`design-spec.md`](tasks/_assets/design/design-spec.md).

**Non-goals.** Не магазин книг, не клубы/комментарии, не другие языковые пары (только EN→RU), не нативные приложения, не офлайн, не поиск по книге, не полноценный SM-2/Anki (у нас упрощённая прогрессия).

---

## Вехи

- **M1.** NLP-разметка
- **M2.** Chunker
- **M3.** Локальная читалка без бэка
- **M4.** LLM-перевод одного слова (замена inline)
- **M5.** Пользовательский словарь (в памяти)
- **M6.** Персистентный словарь
- **M7.** Inline-картинки
- **M8.** Персистентность книг
- **M9.** Библиотека
- **M10.** Прогресс + lazy-load + resume
- **M11.** Мульти-юзер + auth
- **M12.** Парсеры и загрузка
- **M13.** Деплой
- **M14.** Наблюдаемость, hardening, бэкапы
- **M15.** Тесты и CI
- **M16.** Дизайн-система и фичи из прототипа: токены/компоненты, прогрессия слов, Словарь-экран, Каталог, Тренировки, Streak

---

# M1. NLP-разметка

### 1.1 Скелет проекта и базовый NLP-пайплайн — M
**Описание.** Завести Python-проект и собрать первый конвейер: строка → токены + предложения + флаг translatable. Это фундамент, на нём висит всё остальное.
**Включает.**
- Python-проект: pyproject, venv, линтер (ruff), форматтер (black), CI-заглушка.
- Структура `src/en_reader/`, `src/en_reader/parsers/`, `tests/`, `data/`.
- Подключение spaCy (`en_core_web_sm`, parser=true), singleton-пул.
- Dataclass `Token` (text, lemma, pos, is_sent_start, idx_in_text, translatable, unit_id, pair_id).
- Dataclass `Unit` (id, token_ids, lemma, kind, is_split_pv, pair_id).
- Функция токенизации из строки → `list[Token]` с проброшенным sent_start и char offset.
**Acceptance.**
- `pytest` запускается в пустом проекте.
- На фикстурном абзаце есть ≥ 1 токен с is_sent_start=true для каждого предложения.
- Инвариант: конкатенация `text` токенов + промежутки восстанавливает исходную строку (тест).

### 1.2 Curate STOP_WORDS + правило translatable — S
**Описание.** Собрать курируемый список ~300 английских лемм, которые никогда не translatable (артикли, A1-глаголы, местоимения, дни, месяцы, числительные), и реализовать сам фильтр.
**Включает.**
- Файл `data/stop_words.txt` под контролем версий.
- Правило: translatable = POS ∈ {VERB, NOUN, ADJ, ADV, PROPN} И lemma ∉ STOP_WORDS.
- Спец-правило: have/do/be в роли AUX — не translatable, даже если POS=VERB.
**Acceptance.**
- Тест на фикстуре: `the/and/I/was/have (aux)` не translatable; `ominous/whispered` translatable.
- Покрыт кейс split `was walking` — `was` не translatable, `walking` translatable.
**Зависит от.** 1.1.

### 1.3 MWE-детекция — S
**Описание.** Курируемый словарь устойчивых выражений (~500: `in order to`, `as well as`, `by the way`) и матчинг в тексте.
**Включает.**
- Файл `data/mwe.txt`.
- Интеграция `PhraseMatcher` из spaCy.
- При матче — создаётся один Unit kind=mwe, входящие токены перестают быть translatable как одиночки.
**Acceptance.**
- Тест: `in order to` в тексте — один Unit kind=mwe, три входящих токена с unit_id этого Unit.
- Unit не пересекаются, инварианты разметки зелёные.
**Зависит от.** 1.1, 1.2.

### 1.4 Фразовые глаголы: contiguous + split — M
**Описание.** Детектировать фразовые глаголы в двух формах — рядом (`look up the word`) и разнесённые (`look the word up`). Это ключевая для продукта фича.
**Включает.**
- Словарь `data/phrasal_verbs.txt` (~2500 записей `verb particle`).
- Contiguous: глагол + частица рядом → Unit kind=phrasal.
- Split: частица в `prt`-зависимости от глагола через dependency parser, но не соседствует → два Unit kind=split_phrasal с общим pair_id.
- Если и contiguous, и split, и MWE конкурируют — приоритет MWE > phrasal > одиночные.
**Acceptance.**
- `look up the word` → 1 Unit (look up).
- `look the word up` → 2 Unit с общим pair_id (look и up).
- `look at the book` — не определяется как phrasal (at — предлог, не prt).
- Инварианты разметки зелёные.
**Зависит от.** 1.1, 1.3.

### 1.5 Golden-тесты разметки — S
**Описание.** Зафиксировать ожидаемую разметку на нескольких эталонных абзацах — чтобы непреднамеренные регрессии в NLP ловились сразу.
**Включает.**
- 3–5 эталонных фрагментов (~100 слов каждый) с ручной разметкой Token/Unit в JSON.
- Golden-тест, сравнивающий текущий output с эталоном; при намеренной смене — `pytest --update-golden`.
- Тест-инварианты на крупном тексте (вся первая глава «Гарри Поттера»).
**Acceptance.**
- Любое непреднамеренное изменение правил translatable/MWE/phrasal проваливает golden-тест с читаемым diff.
- Инварианты (Unit не пересекаются, каждый токен в одном предложении, concat восстанавливает текст) зелёные на большом тексте.
**Зависит от.** 1.2, 1.3, 1.4.

---

# M2. Chunker

### 2.1 Чанкер текста на страницы — S
**Описание.** Резать размеченный текст на страницы 100–1000 слов по границам предложений.
**Включает.**
- Dataclass `Page` (page_index, text, tokens, units).
- Алгоритм: накапливаем предложения, пока слов < 100; закрываем страницу, если следующее предложение делает > 1000 или если уже закрыто.
- Обработка гигантского предложения (> 1000 слов): отдельная страница, warning в лог.
- Rstrip финальной страницы, `\n\n` между страницами при сериализации.
**Acceptance.**
- На фикстурной книге все страницы 100–1000 слов (кроме единственной «гигантского» предложения).
- Конкатенация text всех страниц (с `\n\n`) восстанавливает исходный текст.
- Ни одна страница не разрывает предложение (тест по sent_start).
**Зависит от.** 1.1.

---

# M3. Локальная читалка без бэка

### 3.1 Seed-пайплайн: текст → демо-фикстура — S
**Описание.** Скрипт, который прогоняет хардкод-английский через NLP + chunker и складывает результат в статический JSON, отдаваемый фронту до появления БД.
**Включает.**
- `scripts/build_demo.py` (вход: путь к .txt, выход: `src/en_reader/static/demo.json`).
- Роут `GET /api/demo` отдаёт этот JSON, без авторизации.
- FastAPI-скелет: `/` отдаёт `static/index.html`, `/static/*` — файлы.
**Acceptance.**
- Запуск `python scripts/build_demo.py tests/fixtures/demo.txt` создаёт JSON со страницами и разметкой.
- `GET /api/demo` возвращает этот JSON.
**Зависит от.** 1.5, 2.1.

### 3.2 Скелет SPA + state + роутинг — S
**Описание.** HTML/JS/CSS-основа приложения: единый state, наивный роутер, два экрана-заглушки.
**Включает.**
- `static/index.html` с `<div id="root">`, подключение `app.js`, `style.css`.
- Один state-объект; мутации через явные action-функции; re-render по diff.
- Роутер на pushState: `/` и `/reader` (пока без id).
- Loader-индикатор при первичной загрузке `/api/demo`.
**Acceptance.**
- Открытие `/` показывает пустой экран библиотеки (заглушка «здесь будут книги»).
- Переход на `/reader` рендерит экран reader (пока пустой).
- В Dev Tools нет ошибок.
**Зависит от.** 3.1.

### 3.3 Рендер страниц + подчёркивание translatable + типографика — M
**Описание.** Собственно читалка: страницы идут колонкой, токены рендерятся, translatable подчёркнуты.
**Включает.**
- Render страницы: итерация по токенам, text-ноды + `<span class="translatable">` для translatable.
- Разделители страниц: горизонтальная линия + `Page N`.
- Типографика: Georgia/Charter serif, line-height ≥ 1.5, max-width ~700 px, `text-align: justify`.
- Адаптив шрифта: 16–20 pt mobile / до 18 pt desktop (media queries).
- Стиль translatable: тонкий пунктир снизу, hover-эффект.
- Заглушка onTokenClick — `console.log(unit_id)`.
**Acceptance.**
- Ручная проверка на 1-й главе «Гарри Поттера»: `the/and/was` не подчёркнуты, `ominous/whispered/look up` подчёркнуты.
- Вёрстка не ломается на 360 px и 1440 px.
**Зависит от.** 3.2.

---

# M4. LLM-перевод одного слова (замена inline)

### 4.1 LLM-интеграция и translate endpoint — M
**Описание.** Один вызов LLM = перевод одного слова/выражения в контексте его предложения. Никаких массивов, merge-правил и sense-ярлыков.
**Включает.**
- Зависимость `google-genai`, конфиг через `.env` (`GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash-lite`).
- Системный промпт (см. «Справочник. Промпт MVP»).
- Функция `translate_one(unit_text, sentence) -> str` с валидацией (непустая, ≤ 60 символов, без тегов).
- Ретраи: до 3 попыток при ошибке/пустом/слишком длинном ответе, экспоненциальный backoff.
- Роут `POST /api/translate` body `{unit_text, sentence, lemma}` → `{ru}`; 502 при неуспехе всех ретраев.
- Логирование: latency, успех/ошибка, длина контекста. Без содержимого.
**Acceptance.**
- Ручной `curl` со словом и предложением возвращает одну русскую строку за < 2 с p50.
- При падении сети/таймауте клиент получает 502 после 3 ретраев.
**Зависит от.** 3.1.

### 4.2 Замена текста перевода + bottom sheet + split-PV — M
**Описание.** Клик по английскому `.word` → `textContent` меняется на русский + класс `.translated` (акцентный цвет) на всех видимых страницах. Клик по уже переведённому (русскому) → bottom sheet с деталями и actions.
**Включает.**
- Хендлер клика: если `.word` без `.translated` — POST `/api/translate`, замена textContent, short flash `.highlighted`.
- Применение перевода ко всем `.word[data-lemma="..."]` на всех загруженных страницах (в т. ч. split PV — через `data-pair-id`).
- Bottom sheet на повторный клик: headword, IPA/POS (если есть), `.soft` card «Перевод», пример из книги, actions `btn primary "В словарь"` / `btn ghost "Оригинал"`.
- «Оригинал» → восстановление EN через `dataset.originalText` + `DELETE /api/dictionary/{lemma}` + toast «Вернули оригинал».
- Scroll anchor: top видимой секции до/после мутации совпадает ±1 px.
- Тост «не удалось перевести» при 502.
**Acceptance.**
- Ручной e2e: клик по `ominous` → слово стало «зловещий» акцентным цветом; все другие `ominous` на странице тоже стали русскими.
- Клик по `look` в «look the word up» → оба span (`look` и `up`) стали русскими одновременно.
- Клик по «зловещий» → открыт bottom sheet; «Оригинал» возвращает `ominous`.
- Clicking не сдвигает viewport (top видимой секции до/после совпадает ±1 px).
- **НЕТ** `<span class="ru-tag">` и вставок рядом с английским — замена на месте.
**Зависит от.** 3.3, 4.1, **16.1 (токены)**, **16.2 (bottom sheet)**.

---

# M5. Пользовательский словарь (в памяти)

### 5.1 In-memory словарь + API + авто-подсветка — M
**Описание.** Сервер помнит, какие слова пользователь уже переводил, чтобы на любой странице эти слова были подсвечены «из коробки».
**Включает.**
- In-memory dict на сервере `{lemma → ru}`. Пользователей пока нет — один глобальный словарь на процесс.
- После успешного `translate_one` — запись в dict.
- Роут `GET /api/dictionary` возвращает весь dict.
- Роут `DELETE /api/dictionary/{lemma}` удаляет запись.
- `/api/demo` возвращает дополнительно `auto_unit_ids[]` для каждой страницы — Unit, чьи леммы есть в dict, плюс `user_dict: {lemma: translation}`.
- Фронт: при рендере страницы translatable с леммой из dict сразу рендерятся с заменой (`textContent = translation`, класс `.translated`).
- Фронт: повторный клик → bottom sheet → «Оригинал» → `DELETE /api/dictionary/{lemma}` + восстановление `.word` по всем страницам.
**Acceptance.**
- Кликаю на `ominous` на странице 1 → при скролле на страницу 5 `ominous` уже переведён, LLM не зовётся.
- Клик по переводу убирает его со всех страниц.
**Зависит от.** 4.2.

---

# M6. Персистентный словарь

### 6.1 Словарь в SQLite с миграционной инфраструктурой — M
**Описание.** Словарь должен переживать рестарт сервера. Попутно — ввести миграционный каркас, которым будут пользоваться все последующие БД-задачи.
**Включает.**
- Модуль `storage.py`: lazy open connection, параметризованные запросы.
- Таблица `meta` (key, value) — `schema_version`.
- Таблица `user_dictionary` (MVP: `id, lemma UNIQUE, translation, first_seen_at`).
- `storage.migrate()`: читает schema_version, применяет миграции по шагам.
- Миграция v0→v1: создать таблицы.
- Загрузка dict в in-memory кэш при старте; мутации — write-through.
**Acceptance.**
- Первый запуск — создаётся `data/en-reader.db` со schema_version=1.
- Перевод → рестарт сервера → dict на месте, LLM не зовётся повторно.
- Повторный `pip install` не ломает БД.
**Зависит от.** 5.1.

### 6.2 Skip LLM при hit в словаре — S
**Описание.** Если лемма уже известна — возвращать кэш, не зовя LLM. До этого шага «кэш» был через auto_unit_ids; теперь обрабатываем случай клика по единице, чью лемму пользователь уже переводил (например, в phrasal-форме и теперь встретил в другой книге одиночно).
**Включает.**
- На `POST /api/translate` — сначала lookup в dict по lemma; hit → вернуть cached ru, miss → LLM + запись в dict.
- Логировать HIT/MISS.
**Acceptance.**
- Тест: два подряд POST с одной леммой — второй не зовёт LLM (проверка через мок).
- Метрика hit-ratio появляется в логах.
**Зависит от.** 6.1.

---

# M7. Inline-картинки

### 7.1 Inline-картинки в тексте — M
**Описание.** Книги содержат картинки, они должны отображаться inline в тексте, в нужном месте. Пока берём картинки из seed-фикстуры; парсеры появятся в M12.
**Включает.**
- Единый формат маркера `IMG[0-9a-f]{12}`.
- Утилита `new_image_id()`.
- Таблица `book_images` (id, book_id, image_id, mime_type, bytes_or_path; UNIQUE book_id+image_id).
- Хранение: BLOB в sqlite или файл в `data/images/` — выбрать один путь и зафиксировать.
- Роут `GET /api/books/{book_id}/images/{image_id}` с `Cache-Control: public, max-age=31536000, immutable`.
- Фронт: в рендере текста маркер → `<img src=… class="inline-image">`.
- Стили `.inline-image`: max-width 100%, центр, vertical margin.
- Seed обновить, чтобы добавлять 1–2 тестовые картинки.
**Acceptance.**
- В demo-книге визуально виден `<img>` в правильном месте.
- Инвариантный тест: число маркеров в text == число записей в book_images.
**Зависит от.** 3.3, 6.1.

---

# M8. Персистентность книг

### 8.1 Схема books/pages + save/load + сжатие — M
**Описание.** Перенести книги и страницы из seed-JSON в SQLite. Это подготовка к мульти-книжной библиотеке.
**Включает.**
- Таблица `books` (пока без user_id): id, title, author, language, source_format, source_bytes_size, total_pages, cover_path, created_at.
- Таблица `pages`: id, book_id, page_index, text, tokens_json, units_json; UNIQUE(book_id, page_index).
- Сжатие tokens_json/units_json gzip перед записью.
- Миграция v1→v2: добавить таблицы.
- `save_book(parsed_book)` — транзакция: books + пакетный pages + book_images.
- `load_book_meta(book_id)`, `load_page(book_id, page_index)`, `load_pages_slice(book_id, offset, limit)`.
- Seed-скрипт переписан: пишет в БД, а не в JSON.
**Acceptance.**
- `python scripts/seed.py tests/fixtures/demo.txt` создаёт запись книги + все страницы.
- `load_pages_slice` возвращает страницы в порядке page_index, без пропусков.
- Инвариант: книгу загрузили и прочитали страницы обратно — текст восстановлен посимвольно.
**Зависит от.** 6.1, 7.1.

### 8.2 API контента книги — S
**Описание.** Фронт больше не ходит за `/api/demo` — ходит за конкретной книгой по id.
**Включает.**
- Роут `GET /api/books/{id}/content?offset=N&limit=K`.
- Ответ: `{book_id, total_pages, last_page_index, last_page_offset, pages: [...], user_dict: {lemma: ru, ...}, auto_unit_ids}`.
- На этой вехе last_page_index/offset = 0 (прогресс в M10), user_dict — срез словаря по леммам текущих страниц.
- Роут `GET /api/books/{id}/cover` (404 если нет).
- Переделать фронт на новый эндпоинт, `/api/demo` убрать.
**Acceptance.**
- Открытие книги по `/books/{id}` рендерит первую страницу из БД.
- Network-запросов: один к `/content`, один к `/cover`.
**Зависит от.** 8.1.

---

# M9. Библиотека

### 9.1 API списка книг и удаление — S
**Описание.** REST-CRUD поверх books для фронта.
**Включает.**
- `GET /api/books` → `[{id, title, author, total_pages, has_cover}]`.
- `DELETE /api/books/{id}` → 204, каскадное удаление pages, book_images, обложки на диске.
- Защита от double-delete и гонок (проверка существования).
**Acceptance.**
- После DELETE — `/api/books/{id}/content` отдаёт 404.
- В БД нет osiротевших pages/images.
**Зависит от.** 8.1.

### 9.2 Экран библиотеки — M
**Описание.** Главный экран: сетка обложек + карточка «+ Добавить книгу» (пока без реального upload — заглушка).
**Включает.**
- CSS-grid: 2 колонки mobile / 3 tablet / 4 desktop (media queries).
- Карточка книги: обложка (или заглушка) + title (2 строки, ellipsis) + author (1 строка).
- Большая пунктирная карточка `+` как последний элемент.
- Пустое состояние: центр экрана — `+`, подсказка «Добавь свою первую книгу».
- Клик по карточке → `pushState /books/{id}` + rerender.
- Длинный тап/контекстное меню → «Удалить» с подтверждением.
**Acceptance.**
- На 360 px — 2 колонки, на 1440 — 4.
- Пустое состояние выглядит осмысленно при отсутствии книг.
- Удаление обновляет список.
**Зависит от.** 9.1.

### 9.3 Шапка читалки + навигация — S
**Описание.** Reader получает шапку с кнопкой возврата и индикатором прогресса.
**Включает.**
- Sticky-header: `← Библиотека`, title книги (ellipsis), прогресс-бар в % (page_index/total_pages).
- Header auto-hide при скролле вниз, показ — при скролле вверх.
- Кнопка `← Библиотека` → pushState `/`, сброс reader-state.
**Acceptance.**
- Шапка скрывается/появляется плавно, без дёргания.
- Клик по `← Библиотека` возвращает на экран библиотеки.
**Зависит от.** 9.2.

---

# M10. Прогресс + lazy-load + resume

### 10.1 Модель и API прогресса чтения — S
**Описание.** Сохранять (page_index, offset∈[0,1]) в БД, чтобы при возврате в книгу восстанавливать точное место.
**Включает.**
- Таблица `reading_progress` (id, book_id, last_page_index, last_page_offset, updated_at; UNIQUE book_id).
- Миграция v2→v3.
- Роут `POST /api/books/{id}/progress` body `{last_page_index, last_page_offset}` → 204.
- `GET /api/books/{id}/content` дополнительно возвращает last_page_index / last_page_offset.
**Acceptance.**
- POST → SELECT возвращает те же значения.
- UNIQUE конфликт обновляет запись, а не дублирует.
**Зависит от.** 8.2.

### 10.2 Восстановление скролла при открытии книги — M
**Описание.** При открытии книги рендерим только target-страницу и точно восстанавливаем offset внутри неё. Это самая деликатная часть UX — не делать по таймеру, а по событиям.
**Включает.**
- При открытии: загрузить только одну страницу (offset = last_page_index, limit = 1).
- После рендера + загрузки изображений (`image.load`) + font ready — `scrollTo(section.top + section.height * offset)`.
- ResizeObserver / событийная логика: если высота секции изменилась после первого скролла (шрифт догрузился) — корректировать.
- До завершения «окна восстановления» игнорировать scroll-события пользователя (не затирать прогресс).
**Acceptance.**
- Открытие книги с offset=0.5 на стр. 37: центр стр. 37 в центре viewport ±5% высоты.
- Открытие с offset=0 — начало страницы.
- Нет «двойного прыжка» виден пользователю.
**Зависит от.** 10.1.

### 10.3 Lazy-подгрузка соседних страниц через sentinels — M
**Описание.** Бесконечный скролл вверх и вниз через IntersectionObserver, без дёрганий viewport.
**Включает.**
- Верхний sentinel над первой загруженной страницей → запрос `offset = first - 1, limit = 1`.
- Нижний sentinel под последней загруженной → `offset = last + 1, limit = 1`.
- Prepend с scroll compensation: запомнить scrollHeight до, скорректировать scrollTop после.
- Предотвращение дублирующих запросов (in-flight flag на каждом направлении).
- Граничные случаи: достигли 0 / total_pages — sentinel отключается.
**Acceptance.**
- Скролл вниз подгружает следующую страницу за < 300 мс.
- Скролл вверх не сдвигает видимую страницу.
- Network tab: на открытии одна страница, далее по одной на скролл.
**Зависит от.** 10.2.

### 10.4 Сохранение прогресса с защитой от stale-save — S
**Описание.** Сохранять позицию с debounce, но так, чтобы устаревшие таймеры не затирали свежие значения.
**Включает.**
- Функция «видимая страница»: секция с наибольшим пересечением viewport.
- Вычисление offset: `(viewport_top - section.top) / section.height`, clamp [0,1].
- Debounce 1.5 с.
- Всегда `clearTimeout` перед установкой нового, даже при early-return когда значение не изменилось.
- Сохранение: POST `/api/books/{id}/progress`.
**Acceptance.**
- Скроллю туда-сюда быстро — пишется только последнее значение.
- Тест: быстро 10→5→8→10 — в БД окажется 10, даже если между ними случился early-return.
**Зависит от.** 10.3.

### 10.5 Current-book и redirect-flow — S
**Описание.** Закрыл вкладку в середине книги → открыл домен → приложение сразу открывает ту же книгу. Нажал «← Библиотека» → домен снова открывает библиотеку.
**Включает.**
- Поле «current_book_id» (пока в `meta`, в M11 переедет на users).
- `GET /api/me/current-book` → `{book_id|null}`.
- `POST /api/me/current-book` → `{book_id|null}`.
- Фронт: при открытии `/` — если current-book ≠ null → pushState `/books/{id}`.
- При открытии книги → POST `{book_id: id}`.
- При клике `← Библиотека` → POST `{book_id: null}`, затем pushState `/`.
- Закрытие вкладки без кнопки — current-book не трогаем.
**Acceptance.**
- Acceptance resume: закрыл на стр. 37 offset 0.5 → открыл `/` → книга стр. 37 offset 0.5.
- «← Библиотека» → следующий заход открывает library.
**Зависит от.** 10.2, 10.4.

---

# M11. Мульти-юзер + auth

### 11.1 Миграция данных под user_id — M
**Описание.** Добавить `user_id` во все per-user таблицы и переселить существующие данные на «первого пользователя».
**Включает.**
- Таблица `users` (id, email, password_hash, created_at, current_book_id).
- `books.user_id`, `user_dictionary.user_id`, `reading_progress.user_id`.
- Миграция: создать seed-пользователя `admin@local`, приписать ему всё существующее.
- `current_book_id` из `meta` → `users.current_book_id`.
- Обновить индексы: `books.user_id`, `user_dictionary(user_id, lemma)`, `reading_progress(user_id, book_id)`.
**Acceptance.**
- Миграция выполняется на старой БД без потерь данных (тест: dump до/после).
- Старые роуты продолжают возвращать те же данные (пока без auth — seed-user).
**Зависит от.** 10.5.

### 11.2 Auth API + сессии + persistent SECRET_KEY — M
**Описание.** Signup/login/logout/me, bcrypt, сессионная cookie, SECRET_KEY, который переживает рестарт.
**Включает.**
- Хэш bcrypt, cost 12, секрет truncate до 72 байт.
- Валидация: email regex, password ≥ 8.
- `data/.secret_key` — генерится при первом старте, читается далее.
- Starlette SessionMiddleware: HttpOnly, SameSite=Lax, 30 дней, Secure в prod.
- Роуты: `POST /auth/signup` (409), `POST /auth/login` (401), `POST /auth/logout`, `GET /auth/me`.
- Dependency `get_current_user` — 401 без сессии.
- Rate-limit: 10 попыток на signup/login / IP / минуту → 429.
**Acceptance.**
- Signup → logout → login возвращает ту же сессию.
- Рестарт сервера — cookie остаётся валидной.
- 10+ неудачных login с одного IP — 429.
**Зависит от.** 11.1.

### 11.3 Изоляция ресурсов и экран логина — M
**Описание.** Все `/api/*` роуты (кроме auth) защищены; пользователь видит только свои данные; есть минимальный UI для логина/регистрации.
**Включает.**
- Все `/api/books/{id}/*` роуты проверяют `book.user_id == current_user.id` → 403 иначе.
- `/api/books`, `/api/dictionary`, `/api/translate`, progress, current-book — scope по user_id.
- UI: экран `/login` с двумя формами (переключение signup/login), inline-ошибки.
- Logout-кнопка в шапке.
- Тесты изоляции: юзер А не видит книги/словарь/progress юзера Б.
**Acceptance.**
- `GET /api/books/{foreign_id}` → 403.
- Тесты изоляции зелёные.
- Нельзя зайти на `/` без сессии — редирект на `/login`.
**Зависит от.** 11.2.

---

# M12. Парсеры и загрузка

### 12.1 Парсер TXT — S
**Описание.** Читать .txt любой популярной кодировки, возвращать ParsedBook.
**Включает.**
- Dataclass `ParsedBook` (title, author, language, text, images=[]).
- Chardet-детект кодировки (UTF-8, CP1251, ISO-8859-1), fallback UTF-8.
- Strip BOM.
- Title из имени файла (без расширения).
**Acceptance.**
- Фикстуры в UTF-8, CP1251, с BOM — все читаются корректно (тест: сравнение с ожидаемой строкой).
**Зависит от.** 1.1.

### 12.2 Парсер FB2 — M
**Описание.** lxml-парсинг FB2 с извлечением текста в порядке следования, обложки и inline-картинок.
**Включает.**
- Обход body, извлечение параграфов в порядке следования.
- Inline-картинки: `<image l:href="#id"/>` → маркер `IMG<hex>` в тексте + bytes в ParsedBook.images.
- Title/author из `description/title-info/book-title` и `author`.
- Обложка из `description/title-info/coverpage`, НЕ дублируется в text.
**Acceptance.**
- Фикстура с 2 картинками и обложкой: text содержит 2 маркера, images len=2, cover present.
- Тест: число маркеров == len(images).
**Зависит от.** 7.1, 12.1.

### 12.3 Парсер EPUB — M
**Описание.** ebooklib + BeautifulSoup, обход spine, извлечение видимого текста, inline-картинки без дублей.
**Включает.**
- Обход spine, выборка тегов-параграфов.
- `<img>` → `NavigableString` с маркером, чтобы остался в родительском `<p>` ровно один раз (не создавать новый `<p>`).
- Title/author из metadata.
- Обложка: `properties="cover-image"` в manifest, fallback к первой картинке.
**Acceptance.**
- Фикстура epub с nested `<p>` и `<img>`: маркер ровно один на картинку.
- Cover извлекается корректно.
**Зависит от.** 7.1, 12.1.

### 12.4 Upload endpoint + UI загрузки — M
**Описание.** Пользователь жмёт `+ Добавить книгу`, выбирает файл, видит прогресс, получает открытую книгу или понятную ошибку.
**Включает.**
- Диспетчер парсеров по расширению + магическим байтам.
- Роут `POST /api/books/upload` (multipart, один файл).
- Пайплайн: parse → NLP → chunker → `save_book(user_id, parsed)`.
- Атомарность: всё в одной транзакции, при ошибке — откат полностью.
- Лимит 200 МБ → 413; валидация формата → 400.
- UI: file-input без атрибута `accept` (iOS Safari режет fb2).
- UI: скелетон-карточка с именем файла пока идёт upload.
- Тост с читаемой ошибкой при 400/413/500.
**Acceptance.**
- Загрузка txt/fb2/epub работает, книга сразу открывается.
- Файл 250 МБ → 413, UI показывает причину.
- Broken fb2 → 400 без записи в БД.
**Зависит от.** 9.1, 11.3, 12.1, 12.2, 12.3.

---

# M13. Деплой

### 13.1 VPS bootstrap + systemd + :80 — M
**Описание.** Один скрипт поднимает сервис на чистой Ubuntu VPS и запускает его на 80 порту без nginx.
**Включает.**
- `deploy/bootstrap.sh`: apt python/git/ufw, unprivileged user, venv, зависимости, spaCy-модель, `data/` mkdir, генерация SECRET_KEY.
- `deploy/en-reader.service`: uvicorn с `AmbientCapabilities=CAP_NET_BIND_SERVICE`, WorkingDirectory=data, Restart=always.
- `ufw allow 80/tcp && ufw enable`.
- `deploy/README.md`: одна команда для поднятия с нуля.
**Acceptance.**
- На пустой Ubuntu ВМ: `curl bootstrap.sh | bash` → через ≤ 5 минут сервис доступен на `http://<ip>/`.
- Ребут сервера — сервис поднимается сам.
**Зависит от.** 11.3.

### 13.2 Autopull-пайплайн — M
**Описание.** Автоматический CI/CD: пуш в main → через ≤ 30 с сервис обновлён на VPS.
**Включает.**
- `deploy/autopull.sh`: flock, `git fetch`, no-op check, `git pull`.
- При смене `pyproject.toml` — `pip install`.
- При смене systemd-unit в репозитории — `cp` + `daemon-reload`.
- Рестарт сервиса.
- `deploy/en-reader-autopull.service` (oneshot) + `.timer` (OnUnitActiveSec=10s).
- Не шуметь: если pull no-op — тишина.
**Acceptance.**
- `git push` → через ≤ 30 с новая версия живёт.
- Изменение systemd-unit в репо автоматически перезаливается.
**Зависит от.** 13.1.

### 13.3 Telegram deploy-notify — S
**Описание.** После каждого успешного деплоя прилетает сообщение в Telegram с SHA.
**Включает.**
- `deploy/notify.sh`: curl `sendMessage` с токеном и chat_id из `.env` (с hardcoded fallback, если .env не читается).
- Вызов из autopull.sh в конце при смене SHA.
- Формат: `deployed <sha7>` или `failed <sha7>: <reason>`.
**Acceptance.**
- Push → в Telegram прилетает `deployed <sha>`.
- При ошибке рестарта — прилетает `failed`.
**Зависит от.** 13.2.

### 13.4 TLS через Let's Encrypt — S
**Описание.** Перевести прод на HTTPS с автоматическим обновлением сертификата.
**Включает.**
- Установка acme.sh (или certbot-standalone), получение сертификата.
- systemd-unit для :443 с CAP_NET_BIND_SERVICE.
- Редирект http→https.
- Крон для авто-обновления сертификата.
- Если без домена MVP — задача пропускается.
**Acceptance.**
- `https://<domain>/` → зелёный замок.
- `http://<domain>/` → 301 на https.
**Зависит от.** 13.1.

---

# M14. Наблюдаемость, hardening, бэкапы

### 14.1 Структурированные логи + /debug/logs + /debug/health — M
**Описание.** Видеть, что на проде происходит, не лазая по SSH.
**Включает.**
- Structured logger (JSON в prod, pretty на dev).
- `RingBufferHandler` (thread-safe, последние 1000 строк).
- Handler подключён к root, uvicorn, fastapi логгерам.
- `GET /debug/logs` (требует admin-флаг или basic-auth) — тело ring-buffer.
- `GET /debug/health` — `{git_sha, uptime, counts: {users, books}, last_autopull}`.
- Метрики LLM: вызовы, hit-ratio dict, p50/p95 latency → в лог.
**Acceptance.**
- После ошибки на проде её видно на `/debug/logs` без SSH.
- `/debug/health` возвращает текущий SHA.
**Зависит от.** 13.1.

### 14.2 Security headers, CSP, CSRF — S
**Описание.** Стандартная защита от типовых атак.
**Включает.**
- Middleware с заголовками: CSP (`default-src 'self'; img-src 'self' data:; connect-src 'self'`), X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- CSRF-проверка: кроме SameSite=Lax — сверка Origin/Referer на POST/DELETE.
- Secure-cookie флаги в prod.
**Acceptance.**
- Securityheaders.com показывает A или лучше.
- POST с чужим Origin → 403.
**Зависит от.** 11.2.

### 14.3 Rate-limits на ключевые эндпоинты — S
**Описание.** Защитить translate/upload/auth от злоупотреблений и от runaway-кликов пользователя.
**Включает.**
- Rate-limiter (slowapi или собственный middleware, Redis-free — в памяти процесса).
- Лимиты: auth 10/мин/IP; translate 60/мин/user; upload 5/час/user.
- При превышении → 429.
**Acceptance.**
- Тест: 100 кликов подряд на translate в 1 секунду → часть 429, сервер не падает.
**Зависит от.** 11.2, 12.4.

### 14.4 Ежедневные бэкапы SQLite — S
**Описание.** Потеря БД не должна стоить больше суток работы.
**Включает.**
- Cron/systemd-timer раз в сутки: `sqlite3 .backup` → tarball → внешнее хранилище (S3/Hetzner storage/rclone).
- Ротация: хранить 30 последних бэкапов.
- Тестовый restore-скрипт.
**Acceptance.**
- Бэкап появляется в хранилище ежедневно.
- Ручной restore восстанавливает БД.
**Зависит от.** 13.1.

### 14.5 Миграционная инфраструктура: тест «старая → новая» — S
**Описание.** Убедиться, что продовые данные не теряются при каждой новой миграции.
**Включает.**
- Фикстура «снапшот БД версии N» в тестах.
- Тест: прогнать миграции → таблицы users, books, user_dictionary, reading_progress сохранились с тем же количеством записей.
- CI-правило: новая миграция без теста — PR блокируется.
**Acceptance.**
- Тест зелёный на цепочке миграций v0→v1→v2→v3→…
**Зависит от.** 6.1, 11.1.

---

# M15. Тесты и CI

### 15.1 Полное покрытие NLP — M
**Описание.** Один большой тест-модуль на всё NLP.
**Включает.**
- test_tokenizer (инвариант concat, is_sent_start).
- test_translatable (POS, STOP_WORDS, AUX have/do/be).
- test_mwe (фразы распознаны, токены теряют одиночный translatable).
- test_phrasal_verbs (contiguous, split, pair_id, приоритет MWE > phrasal).
- test_invariants (длинный текст, Unit не пересекаются).
- Golden-тесты с механизмом `pytest --update-golden`.
**Acceptance.**
- Покрытие модулей NLP ≥ 90 %.
- На крупном тексте (≥ 10 000 слов) инварианты зелёные.
**Зависит от.** 1.5.

### 15.2 Покрытие storage и контентных API — M
**Описание.** CRUD-тесты и roundtrip через API.
**Включает.**
- test_storage (save/load/каскады).
- test_books_api (list, delete, content, cover, images).
- test_translation_hit_miss (словарь: hit не зовёт LLM).
- test_progress (save → load, offset точный).
- test_current_book (set/get, redirect-логика).
- Мок Gemini — никаких реальных вызовов.
**Acceptance.**
- Все API-роуты покрыты тестами happy path + 4xx.
**Зависит от.** 10.5.

### 15.3 Покрытие parsers — S
**Описание.** Три парсера, по паре фикстур каждый.
**Включает.**
- test_parser_txt (UTF-8, CP1251, BOM).
- test_parser_fb2 (текст, обложка, inline-картинки, инвариант маркеров).
- test_parser_epub (spine, nested `<p>`, обложка, инвариант маркеров).
- test_upload (happy + 413 + 400 + atomicity).
**Acceptance.**
- Покрытие parsers ≥ 85 %.
**Зависит от.** 12.4.

### 15.4 Покрытие auth и изоляции — S
**Описание.** Защита от регрессий в мультипользовательской модели.
**Включает.**
- test_auth (signup/login/logout/me, bcrypt roundtrip).
- test_sessions_persist_after_restart (пересоздание app с тем же SECRET_KEY).
- test_isolation (А не видит books/dict/progress Б, `/api/books/{foreign_id}` → 403).
- test_rate_limit (10 login подряд → 429).
**Acceptance.**
- Попытка доступа к чужому ресурсу — всегда 403.
**Зависит от.** 11.3, 14.3.

### 15.5 Integration-тесты — S
**Описание.** 2–3 сценария, склеивающих несколько модулей.
**Включает.**
- upload_txt → content → translate → повторный translate (cache hit, без LLM).
- cross-book dictionary: клик в книге А → auto-подсвечено на странице Б.
- resume-flow через API: POST progress → GET current-book → GET content.
**Acceptance.**
- Все сценарии зелёные в CI.
**Зависит от.** 15.2, 15.3.

### 15.6 E2E через Playwright — M
**Описание.** Два критических сценария, прогоняемых в настоящем браузере.
**Включает.**
- E2E-1: signup → upload txt → открыть книгу → клик по слову → русский появляется inline.
- E2E-2: resume — скроллю в середину стр. 37 → закрываю вкладку → открываю `/` → редирект в книгу, скролл в 0.5 стр. 37.
- Прогон на Chromium + WebKit.
**Acceptance.**
- Оба сценария зелёные локально и в CI.
**Зависит от.** 12.4, 10.5.

### 15.7 GitHub Actions CI — S
**Описание.** Автоматический прогон на каждый push + required для merge в main.
**Включает.**
- Workflow: lint (ruff) + pytest + playwright.
- Матрица Python-версии (основная + одна соседняя).
- Required check в branch protection для main.
- Кеш deps для ускорения.
**Acceptance.**
- Красный CI блокирует merge.
- Время CI ≤ 8 минут.
**Зависит от.** 15.1–15.6.

---

# M16. Дизайн-система и фичи из прототипа

> Эта веха добавлена после получения дизайна в Claude Design. M16.1 и M16.2 — **блокеры** для всех UI-задач (M3.3, M9.2, M9.3, M11.3, M12.4) и должны быть сделаны в самом начале, сразу после M3.2. Подробности — в [`tasks/_assets/design/design-spec.md`](tasks/_assets/design/design-spec.md).

### 16.1 Design tokens + primitives + theme toggle — M
**Описание.** Палитра light/dark, шрифты Geist + Instrument Serif, базовые классы (`btn`, `chip`, `card`, `pbar`, `uplabel`, `word`, `cover.c-*`), toggle темы с persist в localStorage и `prefers-color-scheme`.
**Acceptance.** Все классы из design-spec работают; `setTheme()` мгновенно переключает; `data/.secret_key`-стиль persist для темы.
**Зависит от.** 3.2.

### 16.2 Bottom sheet + toast + tab bar — M
**Описание.** Шаред-компоненты: `openSheet(content)/closeSheet()`, `showToast(msg)`, `renderTabBar(active)/hideTabBar()/showTabBar()`; SVG-иконки в отдельном файле.
**Acceptance.** Sheet открывается/закрывается по клику на scrim и Esc; toast автоматически скрывается; таб-бар с 4 вкладками и активной точкой.
**Зависит от.** 16.1.

### 16.3 Прогрессия слов (new / learning / review / mastered) + API — M
**Описание.** Расширить user_dictionary статусами + correct_streak/wrong_count/last_reviewed_at/next_review_at/example/source_book_id. Правила переходов между статусами, агрегация `dict_stats`, `pick_training_pool`, endpoint'ы `/api/dictionary/stats|training|training/result`.
**Acceptance.** Миграция v5→v6; правила переходов корректны; training pool по приоритету review → learning → new.
**Зависит от.** 6.1, 11.1.

### 16.4 Экран «Словарь» — M
**Описание.** Отдельная вкладка: header + счётчик, stats-card (review/active/mastered), 5 фильтр-чипов, список карточек слов с бейджем статуса, клик → bottom sheet с примером и actions «Тренировать» / «Удалить».
**Acceptance.** Фильтры меняют выдачу; stats корректен; пустое состояние обработано; темы light/dark.
**Зависит от.** 16.1, 16.2, 16.3.

### 16.5 Каталог: seed-книги + экран — M
**Описание.** Таблица `catalog_books`, seed-скрипт (~20 книг Project Gutenberg), endpoint'ы `GET /api/catalog` и `POST /api/catalog/{id}/import`, экран «Каталог» с level chips и горизонтально-скроллящимися секциями.
**Acceptance.** ≥ 20 книг после seed; клик по карточке импортирует в личную библиотеку; дедуп по title+author.
**Зависит от.** 8.1, 16.1, 16.2.

### 16.6 Тренировка: выбор перевода (multiple choice) — M
**Описание.** Экраны Learn Home + Learn Card (MC) + Done. Сессия до 10 слов, 4 варианта, цветной feedback, POST результата на каждый ответ.
**Acceptance.** Правильный/неправильный корректно движут статусы; done-экран показывает счёт; таб-бар скрыт в сессии.
**Зависит от.** 16.1, 16.2, 16.3.

### 16.7 Тренировка: карточки (flashcards) — S
**Описание.** Режим flashcards: front → headword + IPA; flip → back с переводом и примером; actions «Знал» / «Не знал»; та же прогрессия.
**Acceptance.** Flip-анимация; binarный ответ шлёт `correct`; done-экран переиспользован.
**Зависит от.** 16.6.

### 16.8 Дневная цель и серия (streak) — S
**Описание.** Таблица `daily_activity`, подсчёт streak (последовательные дни с тренировкой), дневная цель 10 правильных ответов, `GET /api/me/streak`; UI-карточки на Library и Learn Home.
**Acceptance.** Тренировочные результаты инкрементируют `daily_activity`; streak корректно считается через границу суток UTC; UI обновляется.
**Зависит от.** 16.3, 16.6.

---

# Критерии приёмки всего продукта

- [ ] **A1. Разметка.** На 1-й главе «Гарри Поттера» `the/and/I/was` не подчёркнуты, `ominous/whispered/look up` — подчёркнуты.
- [ ] **A2. Клик → замена.** Один LLM-вызов, английское слово `ominous` **заменяется** на «зловещий» акцентным цветом (не вставка рядом), viewport не прыгает.
- [ ] **A3. Bottom sheet.** Повторный клик по переведённому слову открывает bottom sheet с headword, переводом, примером; «Оригинал» возвращает английское.
- [ ] **A4. Split phrasal.** Клик по `look` в `look the word up` — оба span (`look` и `up`) становятся русскими одновременно; отмена — оба возвращаются.
- [ ] **A5. Кросс-книжный словарь.** Переведено в книге А → то же слово в книге Б сразу на русском, без LLM-вызова.
- [ ] **A6. Персистентный словарь.** Рестарт сервера → словарь на месте.
- [ ] **A7. Картинки.** Обложка fb2 на карточке, ≥ 1 `<img>` в тексте книги.
- [ ] **A8. Ленивая загрузка.** Network: одна страница на открытии, соседи — по sentinel.
- [ ] **A9. Resume.** Закрыл стр. 37 offset 0.5 → открыл `/` → книга открывается стр. 37 offset 0.5 (±5 % высоты).
- [ ] **A10. «← Библиотека».** Следующий заход — library, не книга.
- [ ] **A11. Multi-user.** Signup/login/logout/рестарт — cookie валидна; данные изолированы по user_id.
- [ ] **A12. Каталог.** Новый пользователь видит ≥ 20 книг в каталоге по уровню; один клик импортирует в личную библиотеку.
- [ ] **A13. Словарь-экран.** Вкладка «Словарь» показывает слова с фильтрами new/learning/review/mastered + stats.
- [ ] **A14. Тренировки.** «Выбор перевода» даёт 4 варианта, правильный ответ двигает слово по прогрессии; done-экран показывает счёт.
- [ ] **A15. Темы.** Переключение светлая/тёмная моментально, без перезагрузки; выбор persist.
- [ ] **A16. Деплой.** `git push` в main → ≤ 30 с прилетает Telegram `deployed <sha>`; сайт не падает дольше 2 с.

---

# Справочник. Модель данных (финальная, после M16)

- **users** (id, email UNIQUE, password_hash, created_at, current_book_id, preferred_level)
- **books** (id, user_id, title, author, language, source_format, source_bytes_size, total_pages, cover_path, created_at)
- **pages** (id, book_id, page_index, text, tokens_json, units_json; UNIQUE book_id+page_index)
- **book_images** (id, book_id, image_id, mime_type, bytes_or_path; UNIQUE book_id+image_id)
- **user_dictionary** (id, user_id, lemma, translation, status, correct_streak, wrong_count, last_reviewed_at, next_review_at, example, source_book_id, first_seen_at; UNIQUE user_id+lemma)
  - `status ∈ {new, learning, review, mastered}`
- **reading_progress** (id, user_id, book_id, last_page_index, last_page_offset, updated_at; UNIQUE user_id+book_id)
- **catalog_books** (id, title, author, language, level, pages, tags, cover_preset, source_url, created_at)
- **daily_activity** (id, user_id, date, words_trained_correct, words_trained_total; UNIQUE user_id+date)
- **meta** (key, value) — schema_version и служебные

Индексы: `books.user_id`, `pages.book_id`, `user_dictionary(user_id, lemma)`, `reading_progress(user_id, book_id)`, `daily_activity(user_id, date)`.

> Отдельная таблица `translation_cache` с page-level ключами в V1 не нужна — её роль выполняет `user_dictionary.translation`. Появится в V2 при переходе на батч-переводы.

---

# Справочник. API (финальный)

**Auth**
- `POST /auth/signup` — `{email, password}` → 200+cookie / 409.
- `POST /auth/login` — `{email, password}` → 200+cookie / 401.
- `POST /auth/logout` → 200.
- `GET /auth/me` → `{email}` / 401.

**Книги**
- `GET /api/books` → `[{id, title, author, total_pages, has_cover}]`.
- `POST /api/books/upload` (multipart) → `{book_id, title, total_pages}`.
- `DELETE /api/books/{id}` → 204.
- `GET /api/books/{id}/cover` → image.
- `GET /api/books/{id}/images/{image_id}` → image.

**Контент**
- `GET /api/books/{id}/content?offset=N&limit=K` →
  `{book_id, total_pages, last_page_index, last_page_offset, pages: [{page_index, text, tokens, units, auto_unit_ids}], user_dict: {lemma: translation}}`.

**Перевод**
- `POST /api/translate` — `{unit_text, sentence, lemma}` → `{ru}`.

**Словарь**
- `GET /api/dictionary?status=<all|new|learning|review|mastered>` → расширенные записи с `{lemma, translation, status, example, source_book, last_reviewed_at}`.
- `GET /api/dictionary/stats` → `{total, review_today, active, mastered, ...}`.
- `GET /api/dictionary/training?limit=10` → тренировочный пул по приоритету.
- `POST /api/dictionary/training/result` — `{lemma, correct}` → 204 (update progression + daily_activity).
- `DELETE /api/dictionary/{lemma}` → 204.

**Каталог**
- `GET /api/catalog` → `{sections: [{key, items: [...]}]}`.
- `POST /api/catalog/{id}/import` → `{book_id}`.

**Прогресс / current-book / streak**
- `POST /api/books/{id}/progress` — `{last_page_index, last_page_offset}` → 204.
- `GET /api/me/current-book` → `{book_id | null}`.
- `POST /api/me/current-book` → `{book_id | null}`.
- `GET /api/me/streak` → `{streak, today: {target, done, percent}}`.

**Debug**
- `GET /debug/health` → `{git_sha, uptime, counts, last_autopull}`.
- `GET /debug/logs` → tail ring-buffer.

Коды: 400 / 401 / 403 / 404 / 409 / 413 / 429 / 500.

---

# Справочник. Промпт LLM (V1)

**System:**
```
You are a professional English-to-Russian literary translator.
You receive a single English word or short phrase and the sentence it appears in.
Return ONLY the best Russian translation of the word/phrase, in context.
Rules:
- One short translation, no variants, no explanations.
- Preserve capitalization (lowercase common words, Title Case for proper nouns).
- For a phrasal verb given as a whole (e.g. "look up"), return a single Russian verb or expression.
- If the phrase is the verb part of a split phrasal verb (particle is elsewhere in the sentence),
  still return the full Russian translation including what the particle contributes.
- No punctuation except what belongs to the translation. No quotes, no parentheses.
- Max 60 characters.
```

**User:**
```
Word: <unit_text>
Sentence: <sentence>
```

**Output:** одна строка plain text.

---

# Нефункциональные требования

- Клик → inline-перевод: p95 ≤ 1.5 с; hit в словаре ≤ 50 мс.
- Подгрузка соседней страницы ≤ 300 мс.
- Страница 100–1000 слов по границам предложений.
- Upload до 200 МБ; txt / fb2 / epub.
- Последние 2 версии Chrome/Safari/Firefox, desktop + mobile.
- Сессия живёт 30 дней и переживает деплой.
- Русский UI.

---

# Что НЕ делаем

Полноценный SM-2/Anki (у нас упрощённая прогрессия из 4 статусов), клубы/комментарии, рекомендации, поиск по книге, закладки, авто-обложки LLM-ом, нативные приложения, другие языковые пары, офлайн.
