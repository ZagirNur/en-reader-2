# Задача M14.5 — Миграции: тест «старая схема → новая»

**Размер.** S (~1 день)
**Зависимости.** M6.1 (миграции), M11.1 (user_id миграция).
**Что строится поверх.** Гарантия, что каждая новая миграция не ломает продакшн-данные.

---

## О проекте (контекст)

**en-reader** — веб-читалка. В проекте уже ≥ 5 миграций. Каждая новая — потенциальная мина для продакшн-данных. Нужна регрессионная страховка: для каждой миграции — фикстура БД «до» и тест, проверяющий, что данные пережили переход.

---

## Что нужно сделать

Механизм проверки миграций на снапшотах БД, один тест на каждую миграцию, CI-правило.

---

## Что входит

### 1. Директория `tests/fixtures/migrations/`

Для каждой «предыдущей» версии — SQLite-снапшот с несколькими осмысленными записями.

Формат имени: `schema_v<N>.db` — БД, на которой установлен schema_version=N и ничего после не применено.

Конкретно:
- `schema_v1.db`: только `user_dictionary` с 5 записями.
- `schema_v2.db`: v1 + `book_images` с 2 картинками.
- `schema_v3.db`: v2 + `books` (2 книги) + `pages` (15 страниц).
- `schema_v4.db`: v3 + `reading_progress` (1 запись).
- `schema_v5.db`: не делаем — это уже текущая с user_id.

**Как генерить фикстуры**: для каждой — отдельный one-off-скрипт в `scripts/generate_migration_fixtures.py`, который создаёт БД, применяет миграции по одной, останавливается на нужной версии, вставляет тестовые данные, сохраняет в `tests/fixtures/migrations/`.

Запусти один раз при появлении этой задачи, закоммить получившиеся .db-файлы.

### 2. Тест `tests/test_migrations.py`

```python
import shutil
import pytest
import sqlite3
from en_reader.storage import migrate

@pytest.mark.parametrize("from_version", [1, 2, 3, 4])
def test_migration_preserves_data(tmp_path, monkeypatch, from_version):
    # 1. Скопировать фикстуру.
    src = f"tests/fixtures/migrations/schema_v{from_version}.db"
    dst = tmp_path / "test.db"
    shutil.copyfile(src, dst)

    # 2. Снять «до» снимок счётчиков.
    before = _count_records(dst)

    # 3. Применить миграции.
    monkeypatch.setenv("DB_PATH", str(dst))
    _reset_storage_singleton()
    migrate()

    # 4. Снять «после» снимок.
    after = _count_records(dst)

    # 5. Проверить, что данные сохранились.
    assert after["user_dictionary"] >= before["user_dictionary"]
    assert after["books"] >= before["books"]
    assert after["reading_progress"] >= before.get("reading_progress", 0)
    assert after["book_images"] >= before.get("book_images", 0)

def _count_records(db_path):
    conn = sqlite3.connect(db_path)
    try:
        counts = {}
        for tbl in ["user_dictionary", "books", "reading_progress", "book_images"]:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[tbl] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                pass
        return counts
    finally:
        conn.close()
```

### 3. Тест полноты цепочки миграций

```python
def test_migrate_from_empty():
    """От пустой БД до текущей схемы — без ошибок, schema_version в конце."""
    ...
```

### 4. CI-правило

В `.github/workflows/ci.yml` (создаётся в M15.7) убедись, что тест миграций запускается на каждом PR.

### 5. Процедура для будущих миграций

В PR любого нового миграционного шага:
1. Сделать новый `schema_v<N>.db` с тестовыми данными.
2. Добавить параметр в `test_migration_preserves_data`.
3. Убедиться, что после применения all миграций данные целы.

Документировать в `docs/migrations.md`:
```markdown
# Adding a migration

1. Define `_migrate_v<N>_to_v<N+1>` in `storage.py`.
2. Add to `MIGRATIONS` list.
3. Generate fixture: `python scripts/generate_migration_fixtures.py --up-to <N>`.
4. Add entry in `test_migrations.py` parametrize.
5. PR blocked until the new migration test is green.
```

---

## Технические детали и ловушки

- **Фикстуры в git**. SQLite-файлы — бинарные, diff нечитаемый. Это ок, они маленькие (~50 КБ каждая).
- **Повторная регенерация**. `scripts/generate_migration_fixtures.py` должен быть **идемпотентным** и детерминированным (никаких `datetime.now()` в тестовых данных — используй фиксированный timestamp).
- **Singleton reset**. `_reset_storage_singleton()` нужна, чтобы тест-миграция не делил connection с другими тестами. Добавь в storage.py `def _reset() -> None` для тестов.

---

## Acceptance

- [ ] Фикстуры v1..v4 существуют.
- [ ] `test_migrations.py` параметризован по ним, все зелёные.
- [ ] Поломка миграции (вручную внесённый bug) → тест красный с понятным сообщением.
- [ ] Документация в `docs/migrations.md` обновлена.

---

## Что сдавать

- Ветка `task/M14-5-migration-regression-test`, PR в main.

---

## Что НЕ делать

- Не генерируй фикстуры «на лету» в тесте — бери из коммитных файлов.
- Не упрощай тест до «после migrate ни одна таблица не пуста» — нужно сравнение с «до».
- Не пиши downward-миграции на MVP.
