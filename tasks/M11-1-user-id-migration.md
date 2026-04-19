# Задача M11.1 — Миграция данных под user_id

**Размер.** M (~2 дня)
**Зависимости.** M10.5 (complete single-user product).
**Что строится поверх.** M11.2 (auth), M11.3 (изоляция).

---

## О проекте (контекст)

**en-reader** — веб-читалка. До M11 всё было «для одного пользователя» — один глобальный словарь, одна библиотека, один прогресс. Пора превратить это в мульти-пользовательский продукт. Стратегия — тихая миграция:
1. Создать таблицу `users` с одним «seed»-юзером (`admin@local` или подобное).
2. Переселить все существующие данные на него.
3. Добавить `user_id` во все per-user таблицы.
4. Старые роуты пока работают на «жёстко зашитом seed-юзере», пока M11.2/M11.3 не добавит настоящую авторизацию.

Это разделение позволяет проверить миграцию **без** ломки работающего приложения.

---

## Что нужно сделать

Миграция `v4 → v5`: создать `users`, переселить `books`, `user_dictionary`, `reading_progress`, `meta.current_book_id` на seed-юзера.

---

## Что входит

### 1. Схема v5

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  current_book_id INTEGER
);
```

- В `books` добавить `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`.
- В `user_dictionary` добавить `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`; UNIQUE заменить на `(user_id, lemma)`.
- В `reading_progress` добавить `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`; UNIQUE заменить на `(user_id, book_id)`.

Индексы:
- `CREATE INDEX idx_books_user ON books(user_id)`.
- `CREATE INDEX idx_ud_user_lemma ON user_dictionary(user_id, lemma)`.
- `CREATE INDEX idx_rp_user_book ON reading_progress(user_id, book_id)`.

### 2. Миграция `_migrate_v4_to_v5`

SQLite не поддерживает `ALTER TABLE ... ADD COLUMN NOT NULL` без default. Нужно пересоздание таблиц:

```python
def _migrate_v4_to_v5(conn):
    # 1. users + seed.
    conn.execute("""
      CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        current_book_id INTEGER
      )
    """)
    # seed-user с дефолтным паролем (не используется никем до M11.2).
    # password_hash — плейсхолдер, настоящая hash будет при первом signup в M11.2.
    from datetime import datetime
    conn.execute(
        "INSERT INTO users(email, password_hash, created_at) VALUES(?,?,?)",
        ("seed@local", "__migration_placeholder__", datetime.utcnow().isoformat())
    )
    seed_user_id = conn.execute("SELECT id FROM users WHERE email='seed@local'").fetchone()["id"]

    # 2. Перенос current_book_id из meta в users.
    row = conn.execute("SELECT value FROM meta WHERE key='current_book_id'").fetchone()
    if row and row["value"]:
        conn.execute("UPDATE users SET current_book_id=? WHERE id=?", (int(row["value"]), seed_user_id))
    conn.execute("DELETE FROM meta WHERE key='current_book_id'")

    # 3. books: пересоздание с user_id.
    conn.execute("ALTER TABLE books RENAME TO books_old")
    conn.execute("""
      CREATE TABLE books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL, author TEXT, language TEXT NOT NULL DEFAULT 'en',
        source_format TEXT NOT NULL, source_bytes_size INTEGER NOT NULL DEFAULT 0,
        total_pages INTEGER NOT NULL, cover_path TEXT, created_at TEXT NOT NULL
      )
    """)
    conn.execute("""
      INSERT INTO books(id, user_id, title, author, language, source_format,
                         source_bytes_size, total_pages, cover_path, created_at)
      SELECT id, ?, title, author, language, source_format,
             source_bytes_size, total_pages, cover_path, created_at
      FROM books_old
    """, (seed_user_id,))
    conn.execute("DROP TABLE books_old")
    conn.execute("CREATE INDEX idx_books_user ON books(user_id)")

    # 4. user_dictionary: пересоздание.
    conn.execute("ALTER TABLE user_dictionary RENAME TO ud_old")
    conn.execute("""
      CREATE TABLE user_dictionary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        lemma TEXT NOT NULL,
        translation TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        UNIQUE(user_id, lemma)
      )
    """)
    conn.execute("""
      INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at)
      SELECT ?, lemma, translation, first_seen_at FROM ud_old
    """, (seed_user_id,))
    conn.execute("DROP TABLE ud_old")
    conn.execute("CREATE INDEX idx_ud_user_lemma ON user_dictionary(user_id, lemma)")

    # 5. reading_progress: пересоздание.
    conn.execute("ALTER TABLE reading_progress RENAME TO rp_old")
    conn.execute("""
      CREATE TABLE reading_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        last_page_index INTEGER NOT NULL DEFAULT 0,
        last_page_offset REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, book_id)
      )
    """)
    conn.execute("""
      INSERT INTO reading_progress(user_id, book_id, last_page_index, last_page_offset, updated_at)
      SELECT ?, book_id, last_page_index, last_page_offset, updated_at FROM rp_old
    """, (seed_user_id,))
    conn.execute("DROP TABLE rp_old")
    conn.execute("CREATE INDEX idx_rp_user_book ON reading_progress(user_id, book_id)")
```

### 3. Обновление storage-функций

Сигнатуры расширяются `user_id`:
- `dict_add(user_id, lemma, translation)`, `dict_remove(user_id, lemma)`, `dict_all(user_id)`.
- `book_list(user_id)`, `book_save(user_id, parsed)`, `book_meta(book_id, user_id=None)` — при передаче user_id требует совпадения.
- `progress_get(user_id, book_id)`, `progress_set(user_id, book_id, ...)`.
- `current_book_get(user_id)`, `current_book_set(user_id, book_id | None)`.

Для `book_meta` — если user_id не задан, возвращать без фильтра (нужно внутренним операциям, но НЕ роутам).

### 4. Роуты на этом этапе используют SEED_USER_ID

В `app.py` определи:
```python
SEED_USER_ID = 1   # Временно, до M11.2.
```

Все роуты передают `SEED_USER_ID` в storage-методы. Поведение приложения снаружи не меняется.

### 5. Тесты миграции `tests/test_migration_v4_to_v5.py`

Подготовь фикстуру БД «до миграции» (v4) с несколькими записями:
- 2 книги в `books` (без user_id).
- 5 записей в `user_dictionary`.
- 1 запись в `reading_progress`.
- `meta.current_book_id = 2`.

Прогони миграцию, проверь:
- `users` содержит `seed@local`.
- Все 2 книги имеют `user_id = seed.id`.
- Все 5 записей словаря имеют `user_id = seed.id`.
- `reading_progress` имеет user_id.
- `seed.current_book_id = 2`, `meta.current_book_id` удалён.
- `books_old`, `ud_old`, `rp_old` не существуют.

### 6. Регресс-тесты старых тест-сьютов

Существующие тесты должны продолжить работать после обновления storage-функций и роутов на seed-user. Все тесты `test_dictionary`, `test_books_api`, `test_progress`, `test_current_book` должны прогоняться на seed-user.

---

## Технические детали и ловушки

- **`ALTER TABLE RENAME`** — SQLite-friendly способ «добавить NOT NULL колонку».
- **Foreign keys во время миграции.** SQLite проверяет FK только если `PRAGMA foreign_keys=ON`. В миграции временно можно выключить: `PRAGMA foreign_keys = OFF;` в начале миграции, `PRAGMA foreign_keys = ON;` в конце. Это избегает проблем с ссылками на old/new таблицы.
- **Бэкап до миграции.** Для уверенности можно в `migrate()` при переходе на v5 сделать `sqlite3 .db .db.backup-v4` (или просто file copy). Необязательно для автотеста, но в проде полезно.
- **seed@local пароль**. Плейсхолдер. Когда в M11.2 появится signup — первый зарегистрированный пользователь становится «настоящим» владельцем контента. Это не проблема для одного dev'а; для нескольких разработчиков — seed можно помечать отдельно.

---

## Acceptance

- [ ] Миграция v4→v5 применяется без ошибок на тестовой БД с seed-данными.
- [ ] Все existing-данные переехали на seed-юзера корректно.
- [ ] Все старые тесты зелёные после обновления кода под user_id.
- [ ] `test_migration_v4_to_v5` зелёный.
- [ ] Индексы созданы.
- [ ] `SEED_USER_ID = 1` используется во всех роутах.

---

## Что сдавать

- Ветка `task/M11-1-user-id-migration`, PR в main.
- В PR — перед deploy обязательно снять бэкап.

---

## Что НЕ делать

- Не реализуй signup/login (**M11.2**).
- Не реализуй изоляцию между юзерами (**M11.3**).
- Не удаляй seed-юзера — он владеет существующими данными.
- Не переписывай тесты на «много юзеров» — этого пока нет.
