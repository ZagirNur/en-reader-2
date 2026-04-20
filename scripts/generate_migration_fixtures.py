"""Deterministically regenerate the migration fixture databases (M14.5).

Produces ``tests/fixtures/migrations/schema_v<N>.db`` for N in 1..5 — a
SQLite snapshot whose schema_version is exactly N, seeded with a handful
of rows for each table that exists at that level. These files are
checked into the repo and exercised by ``tests/test_migrations.py`` to
prove every migration preserves pre-existing data.

**Idempotent by design**: there is no ``datetime.now()`` or other source
of nondeterminism — the script bakes in a fixed ISO timestamp and uses
literal blobs for the gzip'd page payloads. Re-running must produce
byte-identical files so ``git diff`` stays quiet unless the fixtures
actually change.

Usage::

    python scripts/generate_migration_fixtures.py

Run from the repo root; the output directory is resolved relative to
this file so the script doesn't care about the caller's cwd.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import sys
from pathlib import Path

# Make ``src/`` importable when running from the repo root without install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from en_reader import storage  # noqa: E402

# Frozen timestamp used for every ``*_at`` column in the fixtures. Must
# never be replaced with ``datetime.now()`` — determinism is the whole
# point of checking these .db files into git.
FIXED_TS = "2026-01-01T00:00:00+00:00"


# Deterministic empty-list payload for pages.tokens_gz/units_gz/images_gz.
# Computed once at import time so every fixture run writes identical
# bytes (gzip timestamps are stripped because we feed a raw JSON object
# through `gzip.compress` with default mtime=None on Python 3.11+? No —
# we pass mtime=0 via the `compress` helper's signature isn't available,
# so we round-trip through GzipFile to pin mtime explicitly).
def _empty_list_gz() -> bytes:
    """Return gzip-compressed ``[]`` JSON with a zeroed mtime header."""
    import io

    payload = json.dumps([]).encode("utf-8")
    buf = io.BytesIO()
    # mtime=0 keeps the gzip header bytes deterministic across runs.
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as gz:
        gz.write(payload)
    return buf.getvalue()


EMPTY_LIST_GZ = _empty_list_gz()

# Output directory for the fixture files. Mirrors what the tests look up.
FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "migrations"


def _apply_migrations_up_to(conn: sqlite3.Connection, n: int) -> None:
    """Apply migrations 1..n to ``conn`` and stamp ``schema_version=n``.

    Mirrors the bootstrap + per-migration transaction shape that
    :func:`storage.migrate` uses so the resulting file is a faithful
    snapshot of what a real en-reader DB at version ``n`` would look
    like.
    """
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for i in range(n):
        with conn:
            storage.MIGRATIONS[i](conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(i + 1),),
            )


def _seed_v1(conn: sqlite3.Connection) -> None:
    """5 rows in ``user_dictionary`` (pre-v5 schema: no ``user_id`` column)."""
    rows = [
        ("ominous", "зловещий"),
        ("whisper", "шёпот"),
        ("gloom", "мрак"),
        ("valley", "долина"),
        ("shiver", "дрожь"),
    ]
    with conn:
        for lemma, tr in rows:
            conn.execute(
                "INSERT INTO user_dictionary(lemma, translation, first_seen_at) " "VALUES(?, ?, ?)",
                (lemma, tr, FIXED_TS),
            )


def _seed_v2(conn: sqlite3.Connection) -> None:
    """v1 rows + 2 rows in ``book_images`` (small deterministic blobs)."""
    _seed_v1(conn)
    with conn:
        for image_id, payload in [
            ("img0000000001", b"\x89PNG-fixture-1"),
            ("img0000000002", b"\x89PNG-fixture-2"),
        ]:
            conn.execute(
                "INSERT INTO book_images(book_id, image_id, mime_type, data) " "VALUES(?, ?, ?, ?)",
                (1, image_id, "image/png", payload),
            )


def _seed_v3(conn: sqlite3.Connection) -> None:
    """v2 rows + 2 books with 15 pages total (8 + 7)."""
    _seed_v2(conn)
    with conn:
        # Two books; total_pages matches the number of pages we insert
        # for each so invariants hold even on a partially-migrated DB.
        conn.execute(
            "INSERT INTO books(id, title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(?, ?, ?, 'en', 'txt', 0, ?, NULL, ?)",
            (1, "Book A", "Author A", 8, FIXED_TS),
        )
        conn.execute(
            "INSERT INTO books(id, title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(?, ?, ?, 'en', 'txt', 0, ?, NULL, ?)",
            (2, "Book B", "Author B", 7, FIXED_TS),
        )
        for book_id, page_count in ((1, 8), (2, 7)):
            for idx in range(page_count):
                conn.execute(
                    "INSERT INTO pages(book_id, page_index, text, tokens_gz, "
                    "units_gz, images_gz) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        book_id,
                        idx,
                        f"Page {idx} of book {book_id}.",
                        EMPTY_LIST_GZ,
                        EMPTY_LIST_GZ,
                        EMPTY_LIST_GZ,
                    ),
                )


def _seed_v4(conn: sqlite3.Connection) -> None:
    """v3 rows + 1 reading_progress row referencing book_id=2."""
    _seed_v3(conn)
    with conn:
        conn.execute(
            "INSERT INTO reading_progress(book_id, last_page_index, "
            "last_page_offset, updated_at) VALUES(?, ?, ?, ?)",
            (2, 0, 0.42, FIXED_TS),
        )


def _seed_v5(conn: sqlite3.Connection) -> None:
    """Seed the v5 per-user schema directly (no v4 replay needed).

    The v4→v5 migration already created the ``users`` table and seeded
    ``seed@local``; we reuse its id as the owner of every row. Writes go
    through the v5 shape (``user_id`` columns present), matching the
    post-migration layout that production DBs have at this schema
    version. Row counts mirror the other fixtures (5 dict entries, 2
    books, 15 pages, 1 reading_progress row, 2 book_images) so
    ``test_migrations`` can assert identical ``before`` totals across
    every fixture.
    """
    seed_user_id = conn.execute("SELECT id FROM users WHERE email='seed@local'").fetchone()[0]
    with conn:
        # 5 dictionary rows (matches the v1 count the test asserts on).
        for lemma, tr in [
            ("ominous", "зловещий"),
            ("whisper", "шёпот"),
            ("gloom", "мрак"),
            ("valley", "долина"),
            ("shiver", "дрожь"),
        ]:
            conn.execute(
                "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
                "VALUES(?, ?, ?, ?)",
                (seed_user_id, lemma, tr, FIXED_TS),
            )
        # 2 book_images blobs (matches v2 count).
        for image_id, payload in [
            ("img0000000001", b"\x89PNG-fixture-1"),
            ("img0000000002", b"\x89PNG-fixture-2"),
        ]:
            conn.execute(
                "INSERT INTO book_images(book_id, image_id, mime_type, data) " "VALUES(?, ?, ?, ?)",
                (1, image_id, "image/png", payload),
            )
        # 2 books × 8+7 = 15 pages (matches v3 counts).
        conn.execute(
            "INSERT INTO books(id, user_id, title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(?, ?, ?, ?, 'en', 'txt', 0, ?, NULL, ?)",
            (1, seed_user_id, "Book A", "Author A", 8, FIXED_TS),
        )
        conn.execute(
            "INSERT INTO books(id, user_id, title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(?, ?, ?, ?, 'en', 'txt', 0, ?, NULL, ?)",
            (2, seed_user_id, "Book B", "Author B", 7, FIXED_TS),
        )
        for book_id, page_count in ((1, 8), (2, 7)):
            for idx in range(page_count):
                conn.execute(
                    "INSERT INTO pages(book_id, page_index, text, tokens_gz, "
                    "units_gz, images_gz) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        book_id,
                        idx,
                        f"Page {idx} of book {book_id}.",
                        EMPTY_LIST_GZ,
                        EMPTY_LIST_GZ,
                        EMPTY_LIST_GZ,
                    ),
                )
        # 1 reading_progress row (matches v4 count).
        conn.execute(
            "INSERT INTO reading_progress(user_id, book_id, last_page_index, "
            "last_page_offset, updated_at) VALUES(?, ?, ?, ?, ?)",
            (seed_user_id, 2, 0, 0.42, FIXED_TS),
        )


SEEDERS = {
    1: _seed_v1,
    2: _seed_v2,
    3: _seed_v3,
    4: _seed_v4,
    5: _seed_v5,
}


def _build_fixture(n: int) -> Path:
    """Create ``schema_v{n}.db`` from scratch and return its path."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURES_DIR / f"schema_v{n}.db"
    # Unlink any prior file so the byte layout is never inherited from a
    # previous run (SQLite prefers to grow files, not shrink them).
    out.unlink(missing_ok=True)
    for suf in ("-wal", "-shm"):
        (FIXTURES_DIR / f"schema_v{n}.db{suf}").unlink(missing_ok=True)

    conn = sqlite3.connect(str(out))
    conn.row_factory = sqlite3.Row
    try:
        # 1 KB pages keep the fixture files tiny (< 30 KB each). The
        # default 4 KB pagesize pads every table onto its own page and
        # bloats these near-empty snapshots to 50-60 KB for no benefit.
        # page_size must be set BEFORE any table is created.
        conn.execute("PRAGMA page_size = 1024")
        # Keep journal_mode at the default DELETE so no ``-wal`` files
        # get written alongside the fixture. Foreign keys OFF during
        # seeding so we can insert ``reading_progress`` rows referencing
        # books we inserted a moment ago without FK timing surprises.
        conn.execute("PRAGMA foreign_keys = OFF")
        _apply_migrations_up_to(conn, n)
        SEEDERS[n](conn)
        # VACUUM rebuilds the file at its minimum page footprint — our
        # fixtures are tiny in actual bytes but default page allocation
        # leaves 2-3 empty pages in a freshly-created DB. Shrinking here
        # keeps the checked-in files under 30 KB each.
        conn.execute("VACUUM")
    finally:
        conn.close()
    return out


def main() -> None:
    """Regenerate every ``schema_v{1..5}.db`` under the fixtures dir."""
    for n in (1, 2, 3, 4, 5):
        path = _build_fixture(n)
        size = path.stat().st_size
        print(f"wrote {path.relative_to(_REPO_ROOT)}  ({size} bytes)")


if __name__ == "__main__":
    main()
