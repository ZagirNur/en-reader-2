"""SQLite-backed storage for the en-reader dev server (M6.1).

Replaces the in-memory dictionary from M5.1 with a single-file SQLite
database that survives server restarts. Also introduces the migration
framework future persistence tasks (books/pages, reading progress,
per-user scoping) will plug into.

Design choices:

* **One connection per process.** FastAPI in dev runs a single worker,
  and SQLite with ``check_same_thread=False`` is perfectly happy being
  shared across request threads. Opening a new connection per request
  is expensive and would churn the WAL.
* **Default isolation + explicit transactions.** We keep pysqlite's
  default deferred-transaction mode so ``with conn:`` actually wraps
  ``BEGIN ... COMMIT/ROLLBACK`` around migrations. Single-statement CRUD
  calls commit via the ``with conn:`` block or rely on the implicit
  commit at the end of the next DDL — in practice each DAO call below
  issues one statement, and the context manager in ``migrate()`` is the
  only place we need true atomicity.
* **WAL journal mode.** More resilient to concurrent readers and
  survives unclean shutdowns better than the default rollback journal.
* **Lemmas are lowercased at the boundary.** The ``lemma`` column has a
  UNIQUE constraint and we never mix case; ``"Ominous"`` and
  ``"ominous"`` collapse to the same row.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None


def _db_path() -> Path:
    """Resolve the on-disk DB path and ensure its parent directory exists."""
    path = Path(os.environ.get("DB_PATH", "data/en-reader.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_db() -> sqlite3.Connection:
    """Return the process-wide SQLite connection, opening it on first use."""
    global _conn
    if _conn is None:
        path = _db_path()
        conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _conn = conn
    return _conn


# ---------- migrations ----------


def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    """Create the initial ``user_dictionary`` table."""
    conn.execute("""
        CREATE TABLE user_dictionary (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          lemma TEXT NOT NULL UNIQUE,
          translation TEXT NOT NULL,
          first_seen_at TEXT NOT NULL
        )
        """)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Create the ``book_images`` table for inline illustrations (M7.1).

    BLOBs keep the on-disk footprint to a single ``.db`` file, which makes
    backups trivial and matches the "one file per user" SQLite shape. If we
    ever ship books with hundreds of megapixel-scale illustrations we can
    migrate to filesystem storage — but that is not M7.
    """
    conn.execute("""
        CREATE TABLE book_images (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL,
          image_id TEXT NOT NULL,
          mime_type TEXT NOT NULL,
          data BLOB NOT NULL,
          UNIQUE(book_id, image_id)
        )
        """)
    conn.execute("CREATE INDEX idx_book_images_book ON book_images(book_id)")


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
    _migrate_v1_to_v2,
]


def migrate() -> None:
    """Apply any pending schema migrations. Idempotent."""
    conn = get_db()
    with conn:
        # Pre-migration bootstrap: the version-tracking table itself.
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    current = int(row["value"]) if row else 0
    target = len(MIGRATIONS)
    for i in range(current, target):
        with conn:  # BEGIN ... COMMIT/ROLLBACK
            MIGRATIONS[i](conn)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(i + 1),),
            )
    logger.info("DB migrated to version %d", target)


# ---------- user dictionary DAO ----------


def dict_add(lemma: str, translation: str) -> None:
    """Insert ``(lemma, translation)`` if the lemma is not already present.

    First write wins — updates require an explicit ``dict_remove`` + add.
    """
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_dictionary(lemma, translation, first_seen_at) "
            "VALUES(?, ?, ?)",
            (
                lemma.lower(),
                translation,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def dict_remove(lemma: str) -> None:
    """Delete the row for ``lemma`` (case-insensitive). No error if missing."""
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM user_dictionary WHERE lemma = ?", (lemma.lower(),))


def dict_get(lemma: str) -> str | None:
    """Return the translation for ``lemma`` (case-insensitive), or ``None``."""
    conn = get_db()
    cur = conn.execute(
        "SELECT translation FROM user_dictionary WHERE lemma = ?",
        (lemma.lower(),),
    )
    row = cur.fetchone()
    return row["translation"] if row else None


def dict_all() -> dict[str, str]:
    """Return the full dictionary as a ``{lemma: translation}`` dict."""
    conn = get_db()
    cur = conn.execute("SELECT lemma, translation FROM user_dictionary")
    return {row["lemma"]: row["translation"] for row in cur.fetchall()}


# ---------- book_images DAO ----------


def image_save(book_id: int, image_id: str, mime_type: str, data: bytes) -> None:
    """Insert an image blob. No-op if ``(book_id, image_id)`` already exists.

    Seed runs are idempotent in spirit: re-running ``build_demo.py`` will
    generate fresh ``image_id``s, so duplicate inserts on the same id are
    not expected — the ``INSERT OR IGNORE`` is a belt-and-braces guard.
    """
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO book_images(book_id, image_id, mime_type, data) "
            "VALUES(?, ?, ?, ?)",
            (book_id, image_id, mime_type, data),
        )


def image_get(book_id: int, image_id: str) -> tuple[str, bytes] | None:
    """Return ``(mime_type, data)`` for the image, or ``None`` if missing."""
    conn = get_db()
    cur = conn.execute(
        "SELECT mime_type, data FROM book_images WHERE book_id = ? AND image_id = ?",
        (book_id, image_id),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return (row["mime_type"], bytes(row["data"]))


def image_clear_book(book_id: int) -> None:
    """Delete every image for ``book_id``. Test/seed helper."""
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM book_images WHERE book_id = ?", (book_id,))


# ---------- test helpers ----------


def _reset_for_tests() -> None:
    """Close the cached connection so the next ``get_db()`` reopens it.

    Used by test fixtures that swap ``DB_PATH`` between tests.
    """
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except sqlite3.Error:
            pass
        _conn = None
