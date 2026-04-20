"""Regression test for the v7→v8 migration (M16.8).

Mirrors :mod:`tests.test_migration_v6_to_v7` — we replay migrations 1..7
by hand, plant a couple of pre-v8 rows that the migration has to leave
undisturbed, then apply migration 8 directly and assert the new
``daily_activity`` table is in place with the documented shape
(columns, index, UNIQUE enforcement). A final idempotency check re-runs
the full ``migrate()`` and confirms the schema version doesn't regress.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from en_reader import storage


def _fresh_db() -> sqlite3.Connection:
    storage._reset_for_tests()
    path = Path(os.environ["DB_PATH"])
    if path.exists():
        path.unlink()
    for suf in ("-wal", "-shm"):
        extra = path.parent / f"{path.name}{suf}"
        if extra.exists():
            extra.unlink()
    return storage.get_db()


def _apply_through_v7(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for i in range(7):  # v0→v1 through v6→v7
        with conn:
            storage.MIGRATIONS[i](conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(i + 1),),
            )
    conn.execute("PRAGMA foreign_keys = ON")


def _seed_pre_v8(conn: sqlite3.Connection) -> None:
    """Plant a book + dict entry so we can check the migration doesn't touch them."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO books(user_id, title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(1, 'Pre-v8 book', NULL, 'en', 'txt', 0, 1, NULL, ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(1, 'ominous', 'зловещий', ?)",
            (now,),
        )


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r["name"] for r in rows}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r["name"] for r in rows}


def test_v7_to_v8_creates_daily_activity_table() -> None:
    conn = _fresh_db()
    _apply_through_v7(conn)
    _seed_pre_v8(conn)

    assert "daily_activity" not in _tables(conn)

    with conn:
        storage.MIGRATIONS[7](conn)
        conn.execute("UPDATE meta SET value='8' WHERE key='schema_version'")

    # New table + index present.
    tables = _tables(conn)
    assert "daily_activity" in tables
    assert "idx_daily_user_date" in _indexes(conn)

    # Columns match the spec.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(daily_activity)").fetchall()}
    expected = {
        "id",
        "user_id",
        "date",
        "words_trained_correct",
        "words_trained_total",
    }
    assert expected.issubset(cols)

    # UNIQUE(user_id, date) is enforced.
    with conn:
        conn.execute(
            "INSERT INTO daily_activity(user_id, date, words_trained_correct, "
            "words_trained_total) VALUES(1, '2024-01-01', 1, 1)"
        )
    try:
        with conn:
            conn.execute(
                "INSERT INTO daily_activity(user_id, date, words_trained_correct, "
                "words_trained_total) VALUES(1, '2024-01-01', 1, 1)"
            )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("duplicate (user_id, date) should raise IntegrityError")

    # Pre-v8 rows left alone.
    books = conn.execute("SELECT title FROM books").fetchall()
    assert len(books) == 1 and books[0]["title"] == "Pre-v8 book"
    ud = conn.execute("SELECT lemma FROM user_dictionary").fetchall()
    assert len(ud) == 1 and ud[0]["lemma"] == "ominous"

    storage._reset_for_tests()


def test_v7_to_v8_is_idempotent_via_full_migrate() -> None:
    _fresh_db()
    storage.migrate()
    first = (
        storage.get_db()
        .execute("SELECT value FROM meta WHERE key='schema_version'")
        .fetchone()["value"]
    )
    storage.migrate()
    second = (
        storage.get_db()
        .execute("SELECT value FROM meta WHERE key='schema_version'")
        .fetchone()["value"]
    )
    assert first == second
    assert int(first) >= 8
    storage._reset_for_tests()
