"""Regression test for the v6→v7 migration (M16.5).

Mirrors :mod:`tests.test_migration_v4_to_v5` — we replay migrations 1..6
by hand, plant a couple of pre-v7 rows that the migration has to leave
undisturbed (the catalog table is brand new, so there's not much to
preserve, but we check books/users/user_dictionary are untouched), then
apply migration 7 directly and assert the new shape.
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


def _apply_through_v6(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for i in range(6):  # v0→v1 through v5→v6
        with conn:
            storage.MIGRATIONS[i](conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(i + 1),),
            )
    conn.execute("PRAGMA foreign_keys = ON")


def _seed_pre_v7(conn: sqlite3.Connection) -> None:
    """Plant a book + dict entry so we can check the migration doesn't touch them."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO books(user_id, title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(1, 'Pre-v7 book', NULL, 'en', 'txt', 0, 1, NULL, ?)",
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


def test_v6_to_v7_creates_catalog_books_table() -> None:
    conn = _fresh_db()
    _apply_through_v6(conn)
    _seed_pre_v7(conn)

    assert "catalog_books" not in _tables(conn)

    with conn:
        storage.MIGRATIONS[6](conn)
        conn.execute("UPDATE meta SET value='7' WHERE key='schema_version'")

    # New table + index present.
    tables = _tables(conn)
    assert "catalog_books" in tables
    assert "idx_catalog_level" in _indexes(conn)

    # Columns match the spec.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(catalog_books)").fetchall()}
    expected = {
        "id",
        "title",
        "author",
        "language",
        "level",
        "pages",
        "tags",
        "cover_preset",
        "source_url",
        "source_path",
        "created_at",
    }
    assert expected.issubset(cols)

    # UNIQUE(title, author) is enforced.
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO catalog_books(title, author, level, pages, tags, "
            "cover_preset, source_url, source_path, created_at) "
            "VALUES('T', 'A', 'B1', 1, '[]', 'c-olive', NULL, '/tmp/x', ?)",
            (now,),
        )
    try:
        with conn:
            conn.execute(
                "INSERT INTO catalog_books(title, author, level, pages, tags, "
                "cover_preset, source_url, source_path, created_at) "
                "VALUES('T', 'A', 'B1', 1, '[]', 'c-olive', NULL, '/tmp/x', ?)",
                (now,),
            )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("duplicate (title, author) should raise IntegrityError")

    # Pre-v7 rows left alone.
    books = conn.execute("SELECT title FROM books").fetchall()
    assert len(books) == 1 and books[0]["title"] == "Pre-v7 book"
    ud = conn.execute("SELECT lemma FROM user_dictionary").fetchall()
    assert len(ud) == 1 and ud[0]["lemma"] == "ominous"

    storage._reset_for_tests()


def test_v6_to_v7_is_idempotent_via_full_migrate() -> None:
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
    assert int(first) >= 7
    storage._reset_for_tests()
