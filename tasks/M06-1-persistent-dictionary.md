# Задача M6.1 — Словарь в SQLite + миграционная инфраструктура

**Размер.** M (~2 дня)
**Зависимости.** M5.1 (in-memory словарь + API).
**Что строится поверх.** M6.2 (skip LLM при hit), M8.1 (books/pages в SQLite), M10.1 (reading_progress), M11.1 (user_id миграция).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Словарь должен переживать рестарт сервера — иначе всё, что пользователь перевёл, исчезает при первом `git pull`. Плюс, пора вводить инфраструктуру БД и миграций, которой будут пользоваться все следующие задачи с persistence.

SQLite — потому что однопроцессное приложение, одна машина, нагрузка низкая, и это один .db-файл, который можно бэкапить tar-ом.

---

## Что нужно сделать

Ввести SQLite-слой, таблицу `meta` для schema_version, таблицу `user_dictionary` (без user_id — добавится в M11.1), миграционный фреймворк, перевести in-memory словарь на write-through кэш поверх БД.

---

## Что входит

### 1. Модуль `src/en_reader/storage.py`

**Публичный контракт:**
```python
def get_db() -> sqlite3.Connection: ...       # lazy singleton
def migrate() -> None: ...                    # вызывается при старте app
def dict_add(lemma: str, translation: str) -> None: ...
def dict_remove(lemma: str) -> None: ...
def dict_get(lemma: str) -> str | None: ...
def dict_all() -> dict[str, str]: ...
```

Connection:
- Один на процесс, `check_same_thread=False`.
- `row_factory = sqlite3.Row`.
- `PRAGMA foreign_keys = ON;`.
- `PRAGMA journal_mode = WAL;` (устойчивее к одновременным чтениям).
- Путь к БД: `os.environ.get("DB_PATH", "data/en-reader.db")`.

### 2. Таблица `meta`

```sql
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

Храним `schema_version` = число как строка.

### 3. Миграционный фреймворк

```python
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
    # _migrate_v1_to_v2, ...
]

def migrate() -> None:
    conn = get_db()
    # создать meta если нет
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    current = int(row["value"]) if row else 0
    target = len(MIGRATIONS)
    for i in range(current, target):
        with conn:   # транзакция
            MIGRATIONS[i](conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(i + 1),)
            )
    logger.info("DB migrated to version %d", target)
```

Каждая миграция — функция, принимающая `conn`, выполняющая DDL.

### 4. Миграция v0 → v1

```python
def _migrate_v0_to_v1(conn):
    conn.execute("""
      CREATE TABLE user_dictionary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lemma TEXT NOT NULL UNIQUE,
        translation TEXT NOT NULL,
        first_seen_at TEXT NOT NULL
      )
    """)
```

### 5. Методы словаря

- `dict_add(lemma, translation)` → `INSERT OR REPLACE` (или IGNORE? — решение: замещаем на новое значение; перевод одного слова может быть уточнён повторно).
  - Actually: INSERT OR IGNORE (первая запись выигрывает). Перевод менять умеем только через DELETE + add. Это проще и интуитивнее.
- `dict_remove(lemma)` → DELETE.
- `dict_get(lemma)` → SELECT.
- `dict_all()` → SELECT lemma, translation → dict.

`first_seen_at` — ISO-timestamp.

### 6. Интеграция с API

- `/api/translate` (после успешного LLM): `dict_add(lemma, ru)`.
- `GET /api/dictionary` → `dict_all()`.
- `DELETE /api/dictionary/{lemma}` → `dict_remove(lemma)`.
- `/api/demo`: `user_dict = dict_all()`, `auto_unit_ids = [u.id for u in page.units if u.lemma in user_dict]`.

In-memory кэш из M5.1 **можешь убрать**: SQLite на одной машине достаточно быстр для < 10000 записей. Если всё же хочется — write-through dict, но это лишнее усложнение на этом этапе.

### 7. Startup-хук

В `app.py`:
```python
@app.on_event("startup")
def on_startup():
    migrate()
```

### 8. Тесты `tests/test_storage.py`

Фикстура — временная БД:
```python
@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    # сбросить singleton, если кэшировал connection
    import en_reader.storage
    en_reader.storage._conn = None
    en_reader.storage.migrate()
    yield
    en_reader.storage._conn = None
```

Тесты:
- `dict_add("ominous", "зловещий")` → `dict_get("ominous") == "зловещий"`.
- Повторный add с тем же lemma — не дублирует (UNIQUE).
- `dict_remove` — удаляет.
- После `migrate()` повторно на той же БД — не падает (идемпотентно).
- Рестарт процесса (пересоздание conn с тем же DB_PATH) — словарь на месте.

---

## Технические детали и ловушки

- **WAL mode**. Может оставить `.db-wal` файл рядом с основным. Это нормально. При `sqlite3.backup()` бэкапе — берутся все нужные блоки.
- **Connection singleton.** Если используешь `check_same_thread=False`, SQLite ОК с несколькими потоками, но лучше в FastAPI одна connection per process. Не делай per-request — дорого.
- **Транзакции.** `with conn:` — context manager, auto-commit или rollback при exception.
- **Миграция «забывчивая».** Если кто-то руками удалит `meta.schema_version`, `migrate()` попытается применить все миграции заново. В v0→v1 IF NOT EXISTS спасает, но в будущих миграциях это риск. Пока тщательно следи за инвариантом «schema_version монотонно растёт».
- **Тесты изоляции.** Фикстура `tmp_db` обязательно должна сбрасывать кэшированный connection — иначе тесты делят состояние.

---

## Acceptance

- [ ] Первый запуск приложения создаёт `data/en-reader.db` с таблицами `meta` и `user_dictionary`, `schema_version=1`.
- [ ] Повторный запуск — никаких ошибок, миграции не применяются повторно.
- [ ] `POST /api/translate` → `GET /api/dictionary` возвращает свежую запись.
- [ ] Рестарт сервера — словарь на месте (интеграционный тест).
- [ ] Тесты `test_storage.py` зелёные.
- [ ] Старые тесты из M5.1 адаптированы и зелёные.
- [ ] В `.gitignore` добавлено `data/*.db` и `data/*.db-wal`, `data/*.db-shm`.

---

## Что сдавать

- Ветка `task/M6-1-persistent-dictionary`, PR в main.

---

## Что НЕ делать

- Не добавляй `user_id` в схему (M11.1).
- Не пиши `books`, `pages`, `reading_progress` таблицы (M8, M10).
- Не пиши `translation_cache` — это V2.
- Не используй SQLAlchemy. Голый sqlite3 достаточно.
- Не разгоняй in-memory кэш поверх БД — лишнее усложнение.
