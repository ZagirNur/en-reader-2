"""Regression test for the v4→v5 migration (M11.1).

The real :func:`storage.migrate` applies every migration in sequence, so
we can't just call it against a pre-v5 fixture — it would jump straight
to v5. Instead we manually replay migrations 1..4 to stand up a v4
schema, insert the kind of rows a mid-M10 DB would contain, then run
migration 5 directly and assert the new shape.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from en_reader import storage


def _fresh_db() -> sqlite3.Connection:
    """Drop whatever the autouse conftest migrated and open an empty file."""
    storage._reset_for_tests()
    path = Path(os.environ["DB_PATH"])
    if path.exists():
        path.unlink()
    for suf in ("-wal", "-shm"):
        extra = path.parent / f"{path.name}{suf}"
        if extra.exists():
            extra.unlink()
    return storage.get_db()


def _apply_through_v4(conn: sqlite3.Connection) -> None:
    """Stand up a v4 schema on a fresh connection, mirroring ``migrate()``."""
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for i in range(4):  # v0→v1 through v3→v4
        with conn:
            storage.MIGRATIONS[i](conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(i + 1),),
            )


def _seed_v4_fixtures(conn: sqlite3.Connection) -> None:
    """Insert 2 books + 5 dict rows + 1 progress row + current_book_id=2."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for title in ("Book A", "Book B"):
            conn.execute(
                "INSERT INTO books(title, author, language, source_format, "
                "source_bytes_size, total_pages, cover_path, created_at) "
                "VALUES(?, NULL, 'en', 'txt', 0, 1, NULL, ?)",
                (title, now),
            )
        for lemma, tr in [
            ("ominous", "зловещий"),
            ("whisper", "шёпот"),
            ("gloom", "мрак"),
            ("valley", "долина"),
            ("shiver", "дрожь"),
        ]:
            conn.execute(
                "INSERT INTO user_dictionary(lemma, translation, first_seen_at) " "VALUES(?, ?, ?)",
                (lemma, tr, now),
            )
        conn.execute(
            "INSERT INTO reading_progress(book_id, last_page_index, "
            "last_page_offset, updated_at) VALUES(?, ?, ?, ?)",
            (2, 0, 0.42, now),
        )
        conn.execute("INSERT INTO meta(key, value) VALUES('current_book_id', '2')")


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r["name"] for r in rows}


def test_v4_to_v5_migrates_to_seed_user() -> None:
    conn = _fresh_db()
    _apply_through_v4(conn)
    _seed_v4_fixtures(conn)

    with conn:
        storage.MIGRATIONS[4](conn)
        conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
    # PRAGMA foreign_keys = OFF was issued inside the migration; re-enable.
    conn.execute("PRAGMA foreign_keys = ON")

    # users has one seed row.
    users = conn.execute("SELECT id, email, current_book_id FROM users").fetchall()
    assert len(users) == 1
    u = users[0]
    assert u["email"] == "seed@local"
    seed_id = u["id"]
    assert u["current_book_id"] == 2

    # meta.current_book_id removed.
    row = conn.execute("SELECT value FROM meta WHERE key='current_book_id'").fetchone()
    assert row is None

    # Books migrated with user_id.
    books = conn.execute("SELECT id, user_id, title FROM books ORDER BY id").fetchall()
    assert [b["user_id"] for b in books] == [seed_id, seed_id]
    assert [b["title"] for b in books] == ["Book A", "Book B"]

    # Dictionary migrated with user_id + preserved tuples.
    dict_rows = conn.execute(
        "SELECT user_id, lemma, translation FROM user_dictionary ORDER BY lemma"
    ).fetchall()
    assert len(dict_rows) == 5
    assert all(r["user_id"] == seed_id for r in dict_rows)
    tr = {r["lemma"]: r["translation"] for r in dict_rows}
    assert tr["ominous"] == "зловещий"
    assert tr["whisper"] == "шёпот"

    # Reading progress migrated with user_id.
    rp = conn.execute("SELECT user_id, book_id, last_page_offset FROM reading_progress").fetchall()
    assert len(rp) == 1
    assert rp[0]["user_id"] == seed_id
    assert rp[0]["book_id"] == 2
    assert abs(rp[0]["last_page_offset"] - 0.42) < 1e-9

    # *_old tables cleaned up.
    tables = _table_names(conn)
    assert "books_old" not in tables
    assert "ud_old" not in tables
    assert "rp_old" not in tables

    # New indexes present.
    indexes = _index_names(conn)
    assert "idx_books_user" in indexes
    assert "idx_ud_user_lemma" in indexes
    assert "idx_rp_user_book" in indexes

    storage._reset_for_tests()


def test_v4_to_v5_with_no_current_book_leaves_null() -> None:
    conn = _fresh_db()
    _apply_through_v4(conn)
    # No `meta.current_book_id` row this time.
    with conn:
        storage.MIGRATIONS[4](conn)
        conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
    conn.execute("PRAGMA foreign_keys = ON")

    row = conn.execute("SELECT current_book_id FROM users WHERE email='seed@local'").fetchone()
    assert row["current_book_id"] is None
    storage._reset_for_tests()


def test_v4_to_v5_is_idempotent_via_full_migrate() -> None:
    # A fresh `migrate()` on a v5 DB should be a no-op — re-running should
    # not fail or try to re-apply v4→v5.
    _fresh_db()
    storage.migrate()
    version_before = (
        storage.get_db()
        .execute("SELECT value FROM meta WHERE key='schema_version'")
        .fetchone()["value"]
    )
    storage.migrate()
    version_after = (
        storage.get_db()
        .execute("SELECT value FROM meta WHERE key='schema_version'")
        .fetchone()["value"]
    )
    # Full-stack migrate() advances to the *current* head, so after
    # v5→v6 landed this pair both stabilise at "6" and re-running is a
    # no-op. We care that the version is stable and >= "5" (the original
    # contract), not the exact numeric value.
    assert version_before == version_after
    assert int(version_before) >= 5
    storage._reset_for_tests()
