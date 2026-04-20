"""Regression tests for the full migration ladder (M14.5).

For each pre-v5 snapshot under ``tests/fixtures/migrations/`` we:

1. Copy the fixture into a fresh tmp path (the fixtures themselves must
   stay byte-identical across runs).
2. Count rows per relevant table directly via ``sqlite3`` — no storage
   layer involvement, just raw COUNT(*).
3. Point ``DB_PATH`` at the copy, reset the storage singleton, and call
   :func:`storage.migrate`.
4. Count rows again and assert the post-migration counts are ``>=`` the
   pre-migration counts for every table that existed before. Migrations
   are additive: v4→v5 adds a ``user_id`` column but never discards
   rows.

We deliberately override the autouse ``tmp_db`` fixture from
``conftest.py`` with an empty local fixture so the conftest doesn't
stand up a v5 schema before our setup has a chance to overwrite
``DB_PATH`` with a copy of the legacy fixture. Without the override the
conftest would migrate the wrong file, then our test would ``shutil.copy``
over the top of a v5 DB and re-migrate a no-op.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from en_reader import storage

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "migrations"

# Tables that might exist in any of the pre-v5 fixtures. Missing tables
# (e.g. ``books`` in schema_v1.db) are silently skipped by ``_count_rows``.
TABLES_OF_INTEREST = (
    "user_dictionary",
    "book_images",
    "books",
    "pages",
    "reading_progress",
)


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Override the conftest autouse ``tmp_db``.

    The root conftest auto-migrates every test DB to v5 before the test
    body runs, which would defeat the point of these tests (we need to
    control migration timing ourselves). Swapping to a no-op fixture at
    module scope keeps DB_PATH pointed at an unused tmp file until each
    test copies a real fixture into place and explicitly calls
    :func:`storage.migrate`.
    """
    db_file = tmp_path / "placeholder.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


def _count_rows(db_path: Path) -> dict[str, int]:
    """Return ``{table: count}`` for each table in ``TABLES_OF_INTEREST``.

    Opens a throwaway connection so we don't touch the storage singleton
    — callers rely on ``_count_rows`` not racing with ``migrate()``.
    """
    counts: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        for tbl in TABLES_OF_INTEREST:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
                counts[tbl] = int(row[0])
            except sqlite3.OperationalError:
                # Table does not exist at this schema version — skip it.
                pass
    finally:
        conn.close()
    return counts


def _schema_version(db_path: Path) -> str:
    """Return the ``meta.schema_version`` value as a string."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return row[0] if row else "0"
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    """Return the column names of ``table`` in ``db_path``."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}
    finally:
        conn.close()


@pytest.mark.parametrize("from_version", [1, 2, 3, 4, 5])
def test_migration_preserves_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, from_version: int
) -> None:
    """Every pre-v6 fixture survives ``migrate()`` without losing rows."""
    src = FIXTURES_DIR / f"schema_v{from_version}.db"
    assert src.exists(), f"Missing fixture: {src} — run scripts/generate_migration_fixtures.py"
    dst = tmp_path / "test.db"
    shutil.copyfile(src, dst)

    before = _count_rows(dst)
    # Sanity: the fixture actually seeded the rows the generator promises.
    assert before["user_dictionary"] == 5
    if from_version >= 2:
        assert before["book_images"] == 2
    if from_version >= 3:
        assert before["books"] == 2
        assert before["pages"] == 15
    if from_version >= 4:
        assert before["reading_progress"] == 1

    monkeypatch.setenv("DB_PATH", str(dst))
    storage._reset_for_tests()
    storage.migrate()
    storage._reset_for_tests()

    after = _count_rows(dst)

    # Additive property: every table present in ``before`` keeps at
    # least as many rows after migration. v4→v5 rebuilds three tables
    # under new names but copies every row across; v5→v6 only adds
    # nullable columns so counts are untouched.
    for tbl, before_count in before.items():
        after_count = after.get(tbl, 0)
        assert after_count >= before_count, (
            f"Migration from v{from_version} lost rows in {tbl}: "
            f"before={before_count}, after={after_count}"
        )

    assert _schema_version(dst) == "8"

    # v4→v5 specifics: the seed user exists (exactly once) and the
    # books table grew a ``user_id`` column.
    users_cols = _columns(dst, "users")
    assert "email" in users_cols
    conn = sqlite3.connect(str(dst))
    try:
        users = conn.execute("SELECT email FROM users").fetchall()
    finally:
        conn.close()
    assert len(users) == 1
    assert users[0][0] == "seed@local"
    assert "user_id" in _columns(dst, "books")

    # v5→v6 specifics: every progression column landed on
    # ``user_dictionary`` and pre-existing rows adopted the defaults.
    ud_cols = _columns(dst, "user_dictionary")
    for col in (
        "status",
        "correct_streak",
        "wrong_count",
        "last_reviewed_at",
        "next_review_at",
        "example",
        "source_book_id",
    ):
        assert col in ud_cols, f"Missing user_dictionary column after v6 migrate: {col}"
    conn = sqlite3.connect(str(dst))
    try:
        statuses = conn.execute("SELECT DISTINCT status FROM user_dictionary").fetchall()
    finally:
        conn.close()
    # Rows migrated in from v<6 adopt the ``status='new'`` default.
    assert {r[0] for r in statuses} == {"new"}


def test_migrate_from_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A virgin SQLite file migrates cleanly to the current schema version."""
    dst = tmp_path / "fresh.db"
    # Don't even create the file — storage.get_db() does that lazily.
    monkeypatch.setenv("DB_PATH", str(dst))
    storage._reset_for_tests()
    storage.migrate()
    storage._reset_for_tests()

    assert dst.exists()
    assert _schema_version(dst) == "8"

    # Every table introduced across the migration chain is present.
    conn = sqlite3.connect(str(dst))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    tables = {r[0] for r in rows}
    for expected in (
        "meta",
        "users",
        "user_dictionary",
        "book_images",
        "books",
        "pages",
        "reading_progress",
        "catalog_books",
        "daily_activity",
    ):
        assert expected in tables, f"Missing table after migrate(): {expected}"
