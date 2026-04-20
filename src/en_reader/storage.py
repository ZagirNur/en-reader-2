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

import gzip
import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .models import BookMeta, Page, PageImage, Token, Unit, User

if TYPE_CHECKING:
    from .parsers import ParsedBook

logger = logging.getLogger(__name__)

# M11.1: the single migration-seeded user that owns every piece of legacy
# content. Real signup/login lands in M11.2 — until then, all routes pass
# this id to the DAOs via the kwarg defaults below.
SEED_USER_ID = 1

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


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Create the ``books`` and ``pages`` tables (M8.1).

    Pages carry tokens/units/images as gzip-compressed JSON BLOBs — a loaded
    page is ~5 kB instead of ~50 kB uncompressed, which keeps the on-disk
    footprint for a 200-page book around 1 MB. The FK on ``pages.book_id``
    cascades on delete; with ``PRAGMA foreign_keys=ON`` (set in
    :func:`get_db`) that gives us automatic page cleanup when a book row
    goes away. ``book_images`` was added in v2 without a FK, so
    :func:`book_delete` wipes it explicitly.
    """
    conn.execute("""
        CREATE TABLE books (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          author TEXT,
          language TEXT NOT NULL DEFAULT 'en',
          source_format TEXT NOT NULL,
          source_bytes_size INTEGER NOT NULL DEFAULT 0,
          total_pages INTEGER NOT NULL,
          cover_path TEXT,
          created_at TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE pages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          page_index INTEGER NOT NULL,
          text TEXT NOT NULL,
          tokens_gz BLOB NOT NULL,
          units_gz BLOB NOT NULL,
          images_gz BLOB NOT NULL,
          UNIQUE(book_id, page_index)
        )
        """)
    conn.execute("CREATE INDEX idx_pages_book ON pages(book_id)")


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Create the ``reading_progress`` table (M10.1).

    One row per book (``UNIQUE(book_id)``) holds the latest reading position
    as ``(last_page_index, last_page_offset)``. ``user_id`` will join the
    UNIQUE tuple in M11.1 — until then, a single reader per instance is
    assumed. ``ON DELETE CASCADE`` on ``book_id`` keeps progress in lockstep
    with the books table without explicit cleanup in :func:`book_delete`.
    """
    conn.execute("""
        CREATE TABLE reading_progress (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          last_page_index INTEGER NOT NULL DEFAULT 0,
          last_page_offset REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          UNIQUE(book_id)
        )
        """)


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """M11.1: introduce the ``users`` table and per-user scoping.

    Creates ``users`` + seeds a single ``seed@local`` row (id=1) that owns
    every piece of pre-M11 content, migrates ``meta.current_book_id`` into
    ``users.current_book_id``, and rebuilds ``books`` / ``user_dictionary``
    / ``reading_progress`` with a ``user_id`` column and updated UNIQUE
    tuples. Foreign keys are temporarily disabled because SQLite evaluates
    them mid-rename-and-copy, and the intermediate ``*_old`` tables would
    briefly violate the new constraints otherwise. We flip foreign_keys
    OFF here and ``migrate()`` re-enables it after the transaction ends
    (PRAGMA changes are only honoured outside a transaction).
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    # legacy_alter_table: without this, SQLite rewrites FK references in
    # *other* tables when we do `ALTER TABLE books RENAME TO books_old`.
    # That would leave `pages.book_id` pointing at `books_old`, which
    # disappears a few lines later. Legacy mode keeps FK text literal.
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("""
        CREATE TABLE users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          current_book_id INTEGER
        )
        """)
    conn.execute(
        "INSERT INTO users(email, password_hash, created_at) VALUES(?, ?, ?)",
        (
            "seed@local",
            "__migration_placeholder__",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    seed_user_id = conn.execute("SELECT id FROM users WHERE email='seed@local'").fetchone()["id"]

    row = conn.execute("SELECT value FROM meta WHERE key='current_book_id'").fetchone()
    if row and row["value"]:
        conn.execute(
            "UPDATE users SET current_book_id=? WHERE id=?",
            (int(row["value"]), seed_user_id),
        )
    conn.execute("DELETE FROM meta WHERE key='current_book_id'")

    conn.execute("ALTER TABLE books RENAME TO books_old")
    conn.execute("""
        CREATE TABLE books (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          author TEXT,
          language TEXT NOT NULL DEFAULT 'en',
          source_format TEXT NOT NULL,
          source_bytes_size INTEGER NOT NULL DEFAULT 0,
          total_pages INTEGER NOT NULL,
          cover_path TEXT,
          created_at TEXT NOT NULL
        )
        """)
    conn.execute(
        """
        INSERT INTO books(id, user_id, title, author, language, source_format,
                          source_bytes_size, total_pages, cover_path, created_at)
        SELECT id, ?, title, author, language, source_format,
               source_bytes_size, total_pages, cover_path, created_at
        FROM books_old
        """,
        (seed_user_id,),
    )
    conn.execute("DROP TABLE books_old")
    conn.execute("CREATE INDEX idx_books_user ON books(user_id)")

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
    conn.execute(
        """
        INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at)
        SELECT ?, lemma, translation, first_seen_at FROM ud_old
        """,
        (seed_user_id,),
    )
    conn.execute("DROP TABLE ud_old")
    conn.execute("CREATE INDEX idx_ud_user_lemma ON user_dictionary(user_id, lemma)")

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
    conn.execute(
        """
        INSERT INTO reading_progress(user_id, book_id, last_page_index,
                                     last_page_offset, updated_at)
        SELECT ?, book_id, last_page_index, last_page_offset, updated_at
        FROM rp_old
        """,
        (seed_user_id,),
    )
    conn.execute("DROP TABLE rp_old")
    conn.execute("CREATE INDEX idx_rp_user_book ON reading_progress(user_id, book_id)")


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """M16.3: extend ``user_dictionary`` with progression + sheet-display columns.

    SQLite supports ``ALTER TABLE ADD COLUMN`` directly when the new column
    has a ``DEFAULT`` or is nullable — no table rebuild needed. Existing
    rows adopt the defaults (``status='new'``, counters=0, nullable fields
    NULL), which is exactly what we want for words added pre-M16.3.
    ``source_book_id`` is a proper FK with ``ON DELETE SET NULL`` so
    deleting a book does not orphan dictionary entries that referenced it.
    ``ipa`` / ``pos`` are intentionally absent from the schema: per spec §8
    they stay ``None`` in the API response and we do not persist them.
    """
    conn.execute("ALTER TABLE user_dictionary ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
    conn.execute("ALTER TABLE user_dictionary ADD COLUMN correct_streak INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE user_dictionary ADD COLUMN wrong_count INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE user_dictionary ADD COLUMN last_reviewed_at TEXT")
    conn.execute("ALTER TABLE user_dictionary ADD COLUMN next_review_at TEXT")
    conn.execute("ALTER TABLE user_dictionary ADD COLUMN example TEXT")
    conn.execute(
        "ALTER TABLE user_dictionary ADD COLUMN source_book_id INTEGER "
        "REFERENCES books(id) ON DELETE SET NULL"
    )


def _migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """M16.5: create the ``catalog_books`` table.

    Public-domain reading material the seed script (``scripts/seed_catalog.py``)
    pre-loads so freshly-registered users always have something to open. The
    table is per-instance (not per-user): ``/api/catalog`` reads it directly,
    and ``/api/catalog/{id}/import`` copies a row into the caller's own
    ``books`` table via the regular :func:`book_save` pipeline.

    Columns mirror the spec SQL verbatim — ``tags`` is stringified JSON
    (SQLite has no native array type) and ``cover_preset`` is one of the
    M16.1 gradient-preset names (``c-olive``, ``c-rose``, …) so the UI can
    render a tile without a real image file. ``source_url`` is informational
    (Gutenberg attribution); nothing joins on it. No FK because the row
    references a file-on-disk, not another DB table.
    """
    conn.execute("""
        CREATE TABLE catalog_books (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          author TEXT NOT NULL,
          language TEXT NOT NULL DEFAULT 'en',
          level TEXT NOT NULL,
          pages INTEGER NOT NULL,
          tags TEXT NOT NULL DEFAULT '[]',
          cover_preset TEXT NOT NULL,
          source_url TEXT,
          source_path TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(title, author)
        )
        """)
    conn.execute("CREATE INDEX idx_catalog_level ON catalog_books(level)")


def _migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """M16.8: create the ``daily_activity`` table.

    One row per ``(user_id, date)`` tracks how many training answers the
    user submitted that calendar day and how many were correct. The table
    is append-only from the UI's perspective: each answer either inserts
    a fresh row or increments both counters on the existing row via an
    ``ON CONFLICT`` upsert. ``date`` is the UTC calendar date as
    ``YYYY-MM-DD`` — same format we use for ``first_seen_at`` elsewhere,
    just truncated — so lexical sort matches chronological order and the
    streak walk-backwards query stays trivial.

    ``UNIQUE(user_id, date)`` makes the upsert work with a single
    ``ON CONFLICT DO UPDATE`` and the covering index on the same tuple
    keeps the per-day lookup in :func:`compute_streak` O(log n).
    """
    conn.execute("""
        CREATE TABLE daily_activity (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          date TEXT NOT NULL,
          words_trained_correct INTEGER NOT NULL DEFAULT 0,
          words_trained_total INTEGER NOT NULL DEFAULT 0,
          UNIQUE(user_id, date)
        )
        """)
    conn.execute("CREATE INDEX idx_daily_user_date ON daily_activity(user_id, date)")


def _migrate_v8_to_v9(conn: sqlite3.Connection) -> None:
    """M18.1: add ``users.telegram_id`` for Telegram Mini-App auth.

    Nullable because existing email/password accounts predate the column;
    partial UNIQUE index keeps the 1:1 mapping between Telegram accounts
    and rows without forbidding multiple ``NULL`` rows (legacy users).

    SQLite supports partial indexes since 3.8.0 (WHERE clause), so this
    migration runs the same on 22.04 and 24.04. ALTER TABLE ADD COLUMN
    without a DEFAULT leaves existing rows at NULL, which is what we
    want — an email/password user gets a telegram_id only after they
    open the Mini-App and we link the accounts.
    """
    conn.execute("ALTER TABLE users ADD COLUMN telegram_id INTEGER")
    conn.execute(
        "CREATE UNIQUE INDEX idx_users_telegram ON users(telegram_id) "
        "WHERE telegram_id IS NOT NULL"
    )


def _migrate_v9_to_v10(conn: sqlite3.Connection) -> None:
    """M18.4: add ``link_tokens`` — one-time tokens for the Telegram link flow.

    An authenticated web user clicks "Привязать Telegram", we mint a
    short-lived token, and send them to ``t.me/<bot>?start=link_<token>``.
    The webhook handler consumes the token to know which local user is
    asking to be linked to the ``from.id`` of the incoming message.

    ``status`` transitions: ``pending`` → ``done|conflict|expired|failed``.
    When status is ``conflict`` we store the chat/message id of the inline
    keyboard we sent so a follow-up callback_query can edit it in place.
    ``result`` is a short human-readable string the /auth/link/telegram/
    status endpoint surfaces to the frontend poller.
    """
    conn.execute(
        """
        CREATE TABLE link_tokens (
          token TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          other_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          chat_id INTEGER,
          message_id INTEGER,
          result TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_link_tokens_user ON link_tokens(user_id)")


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
    _migrate_v1_to_v2,
    _migrate_v2_to_v3,
    _migrate_v3_to_v4,
    _migrate_v4_to_v5,
    _migrate_v5_to_v6,
    _migrate_v6_to_v7,
    _migrate_v7_to_v8,
    _migrate_v8_to_v9,
    _migrate_v9_to_v10,
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
    # Migrations may toggle `foreign_keys` OFF (v4→v5 does) — PRAGMA changes
    # are only honoured outside a transaction, so restore the enforcement
    # default here, post-commit, before any DAO runs on this connection.
    conn.execute("PRAGMA foreign_keys = ON")
    logger.info("DB migrated to version %d", target)


# ---------- user dictionary DAO ----------


def dict_add(
    lemma: str,
    translation: str,
    *,
    user_id: int = SEED_USER_ID,
    example: str | None = None,
    source_book_id: int | None = None,
) -> None:
    """Insert ``(lemma, translation)`` if the lemma is not already present.

    First write wins — updates require an explicit ``dict_remove`` + add.
    ``user_id`` defaults to :data:`SEED_USER_ID` so pre-M11 call sites keep
    working without changes.

    M16.3: new rows land in the ``status='new'`` lane with ``next_review_at``
    one day ahead of ``first_seen_at``. ``example`` captures the sentence the
    lemma was first met in (used by the sheet UI); ``source_book_id`` records
    which book the word came from, if known.
    """
    conn = get_db()
    now = datetime.now(timezone.utc)
    first_seen = now.isoformat()
    next_review = (now + timedelta(days=1)).isoformat()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_dictionary("
            "user_id, lemma, translation, first_seen_at, "
            "status, correct_streak, wrong_count, "
            "last_reviewed_at, next_review_at, example, source_book_id"
            ") VALUES(?, ?, ?, ?, 'new', 0, 0, NULL, ?, ?, ?)",
            (
                user_id,
                lemma.lower(),
                translation,
                first_seen,
                next_review,
                example,
                source_book_id,
            ),
        )


def dict_remove(lemma: str, *, user_id: int = SEED_USER_ID) -> None:
    """Delete the row for ``lemma`` (case-insensitive). No error if missing."""
    conn = get_db()
    with conn:
        conn.execute(
            "DELETE FROM user_dictionary WHERE user_id = ? AND lemma = ?",
            (user_id, lemma.lower()),
        )


def dict_get(lemma: str, *, user_id: int = SEED_USER_ID) -> str | None:
    """Return the translation for ``lemma`` (case-insensitive), or ``None``."""
    conn = get_db()
    cur = conn.execute(
        "SELECT translation FROM user_dictionary WHERE user_id = ? AND lemma = ?",
        (user_id, lemma.lower()),
    )
    row = cur.fetchone()
    return row["translation"] if row else None


def dict_all(*, user_id: int = SEED_USER_ID) -> dict[str, str]:
    """Return the full dictionary as a ``{lemma: translation}`` dict."""
    conn = get_db()
    cur = conn.execute(
        "SELECT lemma, translation FROM user_dictionary WHERE user_id = ?",
        (user_id,),
    )
    return {row["lemma"]: row["translation"] for row in cur.fetchall()}


# ---------- word progression (M16.3) ----------

# Valid values for ``user_dictionary.status`` — the enum that drives every
# transition rule below. ``mastered`` is the terminal green state; ``new``
# is the entry point from ``dict_add``; ``learning`` / ``review`` are the
# intermediate lanes. Anki-flavoured but deliberately simpler: no per-card
# ease factor, no interval math beyond the fixed 1/3/14/30 day offsets.
DICT_STATUSES = ("new", "learning", "review", "mastered")


def record_training_result(
    lemma: str,
    correct: bool,
    *,
    user_id: int = SEED_USER_ID,
) -> None:
    """Update a word's progression after one training answer.

    Transition rules (spec §3):

    * ``new`` + correct                  → ``learning``, streak=1,
      next_review_at = NOW()+1d
    * ``learning`` + correct (streak≥1)  → ``review``, streak=2,
      next_review_at = NOW()+3d
    * ``learning`` + correct (streak=0)  → stays ``learning``, streak=1
    * ``review``   + correct (streak≥2)  → ``mastered``, next_review_at=NOW()+14d
    * ``review``   + correct (streak<2)  → stays ``review``, streak+=1
    * ``mastered`` + correct             → stays ``mastered`` (streak+=1)
    * any state    + wrong               → ``learning``, streak=0,
      wrong_count+=1, next_review_at = NOW()+1d
      (except ``new`` + wrong stays ``new`` — never trained means no demotion)

    Unknown lemma is a silent no-op: callers (tests, API) get idempotent
    behaviour and a client replaying a stale training result after a
    ``DELETE /api/dictionary/{lemma}`` does not 404 the session.

    Timestamps are UTC ISO-8601 (``isoformat()``) so they sort lexically —
    which is all the ``pick_training_pool`` / ``dict_stats`` queries need.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT status, correct_streak, wrong_count "
        "FROM user_dictionary WHERE user_id = ? AND lemma = ?",
        (user_id, lemma.lower()),
    ).fetchone()
    if row is None:
        # Unknown lemma — no-op rather than raise, so clients can replay a
        # training result after the word was deleted without blowing up.
        return

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    status = row["status"]
    streak = int(row["correct_streak"])
    wrong = int(row["wrong_count"])

    if correct:
        if status == "new":
            new_status = "learning"
            new_streak = 1
            next_review = (now + timedelta(days=1)).isoformat()
        elif status == "learning":
            # Promote to review on the *second* consecutive correct answer.
            if streak >= 1:
                new_status = "review"
                new_streak = streak + 1
                next_review = (now + timedelta(days=3)).isoformat()
            else:
                new_status = "learning"
                new_streak = 1
                next_review = (now + timedelta(days=1)).isoformat()
        elif status == "review":
            # Promote to mastered on the *second* consecutive correct while
            # already in review — streak was at least 2 entering review,
            # so one more correct answer takes it to ≥3 and crosses the
            # mastered threshold. Fresh demotions reset streak to 0, so
            # we compare to 2 rather than being looser.
            if streak >= 2:
                new_status = "mastered"
                new_streak = streak + 1
                next_review = (now + timedelta(days=14)).isoformat()
            else:
                new_status = "review"
                new_streak = streak + 1
                next_review = (now + timedelta(days=3)).isoformat()
        else:  # mastered
            new_status = "mastered"
            new_streak = streak + 1
            # Stay on the long interval while mastered-correct.
            next_review = (now + timedelta(days=14)).isoformat()
        new_wrong = wrong
    else:
        new_wrong = wrong + 1
        if status == "new":
            # A word that was never trained can't be demoted — keep it in
            # ``new`` but bump wrong_count and push next_review out by a day
            # so the user doesn't see it again immediately.
            new_status = "new"
            new_streak = 0
            next_review = (now + timedelta(days=1)).isoformat()
        elif status == "mastered":
            # Spec §3: mastered + wrong → review (not learning). The word is
            # still "mostly known", just needs a nudge — skipping it all the
            # way down to learning would kill the long-interval progress.
            new_status = "review"
            new_streak = 0
            next_review = (now + timedelta(days=1)).isoformat()
        else:
            # review / learning + wrong → back to learning.
            new_status = "learning"
            new_streak = 0
            next_review = (now + timedelta(days=1)).isoformat()

    with conn:
        conn.execute(
            "UPDATE user_dictionary SET status = ?, correct_streak = ?, "
            "wrong_count = ?, last_reviewed_at = ?, next_review_at = ? "
            "WHERE user_id = ? AND lemma = ?",
            (
                new_status,
                new_streak,
                new_wrong,
                now_iso,
                next_review,
                user_id,
                lemma.lower(),
            ),
        )
        # M16.8: stamp the per-day activity row inside the same
        # transaction. Both counters bump on every answer so a mix of
        # correct/wrong still counts toward streak preservation; only
        # ``words_trained_correct`` gates the daily goal. ``date`` is the
        # UTC calendar date so the walk-backwards streak query stays
        # timezone-invariant.
        _record_daily_activity(conn, user_id, now, correct=correct)


def _record_daily_activity(
    conn: sqlite3.Connection,
    user_id: int,
    now: datetime,
    *,
    correct: bool,
) -> None:
    """Upsert the ``daily_activity`` row for ``now``'s UTC date.

    Increments ``words_trained_total`` unconditionally, and
    ``words_trained_correct`` only when ``correct`` is ``True``. Called
    from :func:`record_training_result` inside its ``with conn:`` block
    so the dictionary row update and this counter bump either both land
    or both roll back.
    """
    today = now.date().isoformat()
    delta_correct = 1 if correct else 0
    conn.execute(
        "INSERT INTO daily_activity("
        "user_id, date, words_trained_correct, words_trained_total"
        ") VALUES(?, ?, ?, 1) "
        "ON CONFLICT(user_id, date) DO UPDATE SET "
        "words_trained_total = words_trained_total + 1, "
        "words_trained_correct = words_trained_correct + ?",
        (user_id, today, delta_correct, delta_correct),
    )


def pick_training_pool(
    limit: int = 10,
    *,
    user_id: int = SEED_USER_ID,
) -> list[dict]:
    """Return up to ``limit`` words prioritised for the next training session.

    Priority (spec §4):

    1. ``status='review'`` AND ``next_review_at <= NOW()`` — overdue reviews.
    2. ``status='learning'``  — still being cemented.
    3. ``status='new'``       — not yet trained.

    Within each tier, older ``next_review_at`` wins (NULL last) so the most
    overdue items surface first.  Each entry carries ``lemma``,
    ``translation``, ``status``, ``example`` — enough for the sheet UI to
    render a card without a second round-trip.
    """
    if limit <= 0:
        return []
    conn = get_db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    # Spec §3: a ``mastered`` word that hasn't been touched in >30 days
    # demotes back to ``review`` so it can re-enter the training pool.
    # Folding this sweep into the pool pick keeps the rule alive without
    # a separate cron; users only see the demotion when they open the
    # training screen, which is exactly when it matters.
    cutoff = (now - timedelta(days=30)).isoformat()
    with conn:
        conn.execute(
            "UPDATE user_dictionary SET status = 'review', "
            "next_review_at = ?, correct_streak = 0 "
            "WHERE user_id = ? AND status = 'mastered' "
            "AND last_reviewed_at IS NOT NULL AND last_reviewed_at <= ?",
            (now_iso, user_id, cutoff),
        )
    # Ranking via a CASE expression keeps us in a single query: lower
    # ``priority`` sorts first. ``next_review_at`` tiebreaks within a
    # tier; NULLs are pushed to the end so freshly-added words don't
    # leapfrog overdue ones.
    cur = conn.execute(
        """
        SELECT lemma, translation, status, example
        FROM user_dictionary
        WHERE user_id = ? AND (
            (status = 'review' AND next_review_at IS NOT NULL AND next_review_at <= ?)
            OR status = 'learning'
            OR status = 'new'
        )
        ORDER BY
            CASE
                WHEN status = 'review' THEN 1
                WHEN status = 'learning' THEN 2
                WHEN status = 'new' THEN 3
                ELSE 4
            END,
            CASE WHEN next_review_at IS NULL THEN 1 ELSE 0 END,
            next_review_at ASC,
            lemma ASC
        LIMIT ?
        """,
        (user_id, now_iso, limit),
    )
    return [
        {
            "lemma": row["lemma"],
            "translation": row["translation"],
            "status": row["status"],
            "example": row["example"],
        }
        for row in cur.fetchall()
    ]


def dict_stats(*, user_id: int = SEED_USER_ID) -> dict:
    """Return dictionary-wide progression counts (spec §5).

    ``review_today`` counts words in the ``review`` lane that become due by
    tomorrow-midnight-ish (we use ``NOW()+1day`` which is close enough for
    a home-screen badge). ``active`` is the sum of ``new`` + ``learning``.
    Each individual status is also returned so the UI can render a four-way
    bar without a second request.
    """
    conn = get_db()
    now = datetime.now(timezone.utc)
    tomorrow_iso = (now + timedelta(days=1)).isoformat()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS c_new,
            SUM(CASE WHEN status = 'learning' THEN 1 ELSE 0 END) AS c_learning,
            SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) AS c_review,
            SUM(CASE WHEN status = 'mastered' THEN 1 ELSE 0 END) AS c_mastered,
            SUM(CASE WHEN status = 'review' AND next_review_at IS NOT NULL
                     AND next_review_at <= ? THEN 1 ELSE 0 END) AS c_review_today
        FROM user_dictionary
        WHERE user_id = ?
        """,
        (tomorrow_iso, user_id),
    ).fetchone()
    # SUM over zero rows returns None — coerce to 0 so callers always see ints.
    c_new = int(row["c_new"] or 0)
    c_learning = int(row["c_learning"] or 0)
    c_review = int(row["c_review"] or 0)
    c_mastered = int(row["c_mastered"] or 0)
    c_review_today = int(row["c_review_today"] or 0)
    return {
        "total": int(row["total"] or 0),
        "review_today": c_review_today,
        "active": c_new + c_learning,
        "mastered": c_mastered,
        "new": c_new,
        "learning": c_learning,
        "review": c_review,
    }


def dict_list(
    status: str | None = None,
    *,
    user_id: int = SEED_USER_ID,
) -> list[dict]:
    """Return the full dictionary as the rich sheet-ready list shape.

    ``status`` filters to one of :data:`DICT_STATUSES`; ``None`` or
    ``"all"`` returns every row. Each entry carries ``source_book``
    expanded to ``{id, title}`` via a LEFT JOIN on ``books`` so the
    frontend can render a chip without an extra lookup (and ``None`` when
    the word was added without a known source book).

    ``days_since_review`` is computed server-side (whole days, ``>=0``)
    from ``last_reviewed_at`` so the UI does not need to re-parse the
    timestamp. ``ipa`` and ``pos`` are placeholders per spec §8 — always
    ``None`` in M16.3; future tasks will back them with a static JSON
    lookup table.
    """
    conn = get_db()
    params: list[Any] = [user_id]
    where = "WHERE ud.user_id = ?"
    if status and status != "all":
        where += " AND ud.status = ?"
        params.append(status)
    cur = conn.execute(
        f"""
        SELECT ud.lemma, ud.translation, ud.status, ud.example,
               ud.first_seen_at, ud.last_reviewed_at, ud.source_book_id,
               b.title AS book_title
        FROM user_dictionary ud
        LEFT JOIN books b ON b.id = ud.source_book_id
        {where}
        ORDER BY ud.first_seen_at DESC, ud.lemma ASC
        """,
        tuple(params),
    )
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for row in cur.fetchall():
        source_book: dict | None = None
        if row["source_book_id"] is not None and row["book_title"] is not None:
            source_book = {"id": int(row["source_book_id"]), "title": row["book_title"]}
        days_since_review: int | None = None
        if row["last_reviewed_at"]:
            try:
                reviewed = datetime.fromisoformat(row["last_reviewed_at"])
                days_since_review = max(0, (now - reviewed).days)
            except ValueError:
                days_since_review = None
        out.append(
            {
                "lemma": row["lemma"],
                "translation": row["translation"],
                "status": row["status"],
                "example": row["example"],
                "source_book": source_book,
                "first_seen_at": row["first_seen_at"],
                "last_reviewed_at": row["last_reviewed_at"],
                "days_since_review": days_since_review,
                "ipa": None,
                "pos": None,
            }
        )
    return out


# ---------- daily streak + goal (M16.8) ----------


# Fixed target for the daily training goal. Kept as a module-level constant
# so the UI and the /api/me/streak response agree without threading a
# settings object through; if a future milestone makes this per-user,
# flip this to a DAO lookup and keep the public shape identical.
DAILY_GOAL_TARGET = 10


def compute_streak(user_id: int) -> int:
    """Return the consecutive-days streak ending at today (UTC).

    Walk rule:

    * If today has a ``daily_activity`` row (≥1 answer submitted today),
      start the count at 1 and walk yesterday-backward.
    * If today is empty, *do not* reset — start the walk at yesterday.
      The user just opening the app at 8am on day N shouldn't see their
      day-(N-1) work evaporate; the streak represents the chain up to
      and including the most recent active day, not strictly "today".
    * Stop on the first gap (a calendar day with no row).

    We fetch the activity dates in one round-trip (descending, capped at
    365) and scan the in-memory list — cheaper than one SELECT per
    day-walk step and well within the working-set of any human user.
    """
    conn = get_db()
    today = datetime.now(timezone.utc).date()
    rows = conn.execute(
        "SELECT date FROM daily_activity WHERE user_id = ? " "ORDER BY date DESC LIMIT 365",
        (user_id,),
    ).fetchall()
    active_dates = {row["date"] for row in rows}
    if not active_dates:
        return 0

    # Pick the starting point per the "today empty" rule above.
    if today.isoformat() in active_dates:
        cursor = today
    else:
        cursor = today - timedelta(days=1)

    streak = 0
    while cursor.isoformat() in active_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def today_goal(user_id: int) -> dict:
    """Return the daily-goal shape for ``user_id``: ``{target, done, percent}``.

    ``done`` is ``words_trained_correct`` from today's ``daily_activity``
    row (0 if the user hasn't answered anything yet). ``percent`` is
    clamped to 100 so an over-achieving day still renders as a full bar
    rather than overflow.
    """
    conn = get_db()
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        "SELECT words_trained_correct FROM daily_activity " "WHERE user_id = ? AND date = ?",
        (user_id, today),
    ).fetchone()
    done = int(row["words_trained_correct"]) if row else 0
    target = DAILY_GOAL_TARGET
    percent = min(100, done * 100 // target) if target > 0 else 0
    return {"target": target, "done": done, "percent": percent}


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


# ---------- books/pages DAO (M8.1) ----------


def _pack(obj: Any) -> bytes:
    """Serialize ``obj`` to gzip-compressed UTF-8 JSON bytes.

    ``compresslevel=6`` is the sqlite-friendly default: 10x smaller output
    than raw JSON at ~1/3 the CPU cost of ``level=9``. We rarely care about
    decompress speed here — pages are loaded one-at-a-time in the hot path.
    """
    return gzip.compress(json.dumps(obj).encode("utf-8"), compresslevel=6)


def _unpack(data: bytes) -> Any:
    """Inverse of :func:`_pack`. Assumes trusted input (our own writes)."""
    return json.loads(gzip.decompress(data).decode("utf-8"))


def _mask_marker_tokens(tokens: list[Token]) -> None:
    """Clear ``translatable`` on tokens whose text is an image marker.

    spaCy tokenizes ``IMGabcdef012345`` as a single alphanumeric token on its
    own line, so a full-match on the token text is enough. We keep the
    tokens in the stream so the chunker still sees sentence boundaries; the
    frontend just skips rendering them as ``.word`` spans.
    """
    from .images import IMAGE_MARKER_RE  # lazy import to avoid cycles

    for tok in tokens:
        if IMAGE_MARKER_RE.fullmatch(tok.text):
            tok.translatable = False


def _compute_page_images(page_text: str, id_to_mime: dict[str, str]) -> list[PageImage]:
    """Scan ``page_text`` for ``IMG<id>`` markers and build ``PageImage``s.

    Returns a list sorted by ``position``. Any marker whose id isn't in
    ``id_to_mime`` is skipped — that would only happen if text somehow
    contained a marker-shaped substring unrelated to a stored image.
    """
    from .images import IMAGE_MARKER_RE  # lazy import to avoid cycles

    out: list[PageImage] = []
    for match in IMAGE_MARKER_RE.finditer(page_text):
        image_id = match.group(0)[3:]
        mime = id_to_mime.get(image_id)
        if mime is None:
            continue
        out.append(PageImage(image_id=image_id, mime_type=mime, position=match.start()))
    return out


# Mapping from common image MIME types to the on-disk extension we use
# under ``data/covers/``. The fallback is ``.png`` (matches the most
# common embedded cover format and keeps UA-level MIME sniffing happy).
_COVER_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def _cover_ext_for_mime(mime: str) -> str:
    """Return the filesystem extension (no dot) for a cover MIME type."""
    return _COVER_EXT_BY_MIME.get(mime.lower(), "png")


def book_save(parsed: "ParsedBook", *, user_id: int = SEED_USER_ID) -> int:
    """Run the full analyse + chunk + persist pipeline for ``parsed``.

    Runs in a single ``with conn:`` transaction so a failure midway leaves
    the DB untouched. ``parsed.text`` is expected to already contain
    ``IMG<id>`` markers at the desired positions (the seed script injects
    them before calling this); this function takes care of masking those
    marker tokens before chunking and recomputing per-page ``PageImage``
    lists post-chunk by scanning each page's ``text``.

    M12.4: when ``parsed.cover`` is non-None, the cover bytes are written
    to ``data/covers/<book_id>.<ext>`` and the ``books.cover_path`` column
    is updated in the same transaction. If the disk write fails, the
    transaction rolls back and the file is removed so the DB never
    references a missing cover. The ``books`` insert reserves the row
    first so we know the id; the cover write and the ``UPDATE`` that
    records ``cover_path`` both live inside the same ``with conn:``.
    """
    # Lazy imports keep the storage module importable without paying the
    # spaCy model-load cost during migrations or simple DAO use.
    from .chunker import chunk
    from .nlp import analyze

    tokens, units = analyze(parsed.text)
    _mask_marker_tokens(tokens)
    pages = chunk(tokens, units, parsed.text)

    id_to_mime = {img.image_id: img.mime_type for img in parsed.images}
    for page in pages:
        page.images = _compute_page_images(page.text, id_to_mime)

    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cover_path_written: Path | None = None
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO books(user_id, title, author, language, source_format, "
                "source_bytes_size, total_pages, cover_path, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    parsed.title,
                    parsed.author,
                    parsed.language,
                    parsed.source_format,
                    parsed.source_bytes_size,
                    len(pages),
                    None,
                    created_at,
                ),
            )
            book_id = int(cur.lastrowid)
            for p in pages:
                conn.execute(
                    "INSERT INTO pages(book_id, page_index, text, tokens_gz, "
                    "units_gz, images_gz) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        book_id,
                        p.page_index,
                        p.text,
                        _pack([asdict(t) for t in p.tokens]),
                        _pack([asdict(u) for u in p.units]),
                        _pack([asdict(i) for i in p.images]),
                    ),
                )
            for img in parsed.images:
                image_save(book_id, img.image_id, img.mime_type, img.data)

            if parsed.cover is not None:
                covers_dir = Path("data/covers")
                covers_dir.mkdir(parents=True, exist_ok=True)
                ext = _cover_ext_for_mime(parsed.cover.mime_type)
                cover_path = covers_dir / f"{book_id}.{ext}"
                cover_path.write_bytes(parsed.cover.data)
                cover_path_written = cover_path
                conn.execute(
                    "UPDATE books SET cover_path = ? WHERE id = ?",
                    (str(cover_path), book_id),
                )
    except Exception:
        # Roll back the cover file if the transaction aborts — otherwise
        # a failed book_save would leak a stray image into data/covers/.
        if cover_path_written is not None:
            try:
                cover_path_written.unlink()
            except (FileNotFoundError, OSError):
                pass
        raise
    return book_id


def _row_to_book_meta(row: sqlite3.Row) -> BookMeta:
    return BookMeta(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        language=row["language"],
        source_format=row["source_format"],
        source_bytes_size=row["source_bytes_size"],
        total_pages=row["total_pages"],
        cover_path=row["cover_path"],
        created_at=row["created_at"],
    )


def book_meta(book_id: int, *, user_id: int | None = None) -> BookMeta | None:
    """Return the :class:`BookMeta` for ``book_id`` or ``None`` if missing.

    If ``user_id`` is given, require ownership. Internal helpers that don't
    care about tenancy can call this with the default ``None``.
    """
    conn = get_db()
    if user_id is None:
        cur = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
    else:
        cur = conn.execute(
            "SELECT * FROM books WHERE id = ? AND user_id = ?",
            (book_id, user_id),
        )
    row = cur.fetchone()
    return _row_to_book_meta(row) if row else None


def book_list(*, user_id: int = SEED_USER_ID) -> list[BookMeta]:
    """Return every book, newest first (ordered by ``created_at DESC``)."""
    conn = get_db()
    cur = conn.execute(
        "SELECT * FROM books WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (user_id,),
    )
    return [_row_to_book_meta(row) for row in cur.fetchall()]


def book_delete(book_id: int, *, user_id: int | None = None) -> None:
    """Delete a book and its cascaded pages + book_images rows.

    ``pages`` cascades via the FK, but ``book_images`` predates the FK story
    (v1→v2 migration) so we wipe it explicitly. Runs in a single transaction
    so a partial failure leaves the library consistent. If ``book_id`` is
    the current-book pointer (M10.5, stored in ``meta``), we clear that
    pointer inside the same transaction so the library never references a
    deleted row.
    """
    conn = get_db()
    with conn:
        if user_id is None:
            conn.execute("DELETE FROM book_images WHERE book_id = ?", (book_id,))
            conn.execute("DELETE FROM pages WHERE book_id = ?", (book_id,))
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        else:
            conn.execute(
                "DELETE FROM book_images WHERE book_id IN "
                "(SELECT id FROM books WHERE id = ? AND user_id = ?)",
                (book_id, user_id),
            )
            conn.execute(
                "DELETE FROM pages WHERE book_id IN "
                "(SELECT id FROM books WHERE id = ? AND user_id = ?)",
                (book_id, user_id),
            )
            conn.execute(
                "DELETE FROM books WHERE id = ? AND user_id = ?",
                (book_id, user_id),
            )
        # M11.1: clear current-book pointer on any user whose pointer matched.
        # The FK on reading_progress and pages already cascades, but users.current_book_id
        # has no FK — null it explicitly so no row references a deleted book.
        conn.execute(
            "UPDATE users SET current_book_id = NULL WHERE current_book_id = ?",
            (book_id,),
        )


# ---------- current-book DAO (M10.5) ----------


def current_book_get(*, user_id: int = SEED_USER_ID) -> int | None:
    """Return ``users.current_book_id`` for ``user_id`` or ``None``.

    M11.1 moved this pointer off ``meta`` and onto the users table so each
    user can park on their own most-recent book.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT current_book_id FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row or row["current_book_id"] is None:
        return None
    return int(row["current_book_id"])


def current_book_set(book_id: int | None, *, user_id: int = SEED_USER_ID) -> None:
    """Update ``users.current_book_id``. ``None`` clears it."""
    conn = get_db()
    with conn:
        conn.execute(
            "UPDATE users SET current_book_id = ? WHERE id = ?",
            (book_id, user_id),
        )


def _row_to_page(row: sqlite3.Row) -> Page:
    tokens_raw = _unpack(bytes(row["tokens_gz"]))
    units_raw = _unpack(bytes(row["units_gz"]))
    images_raw = _unpack(bytes(row["images_gz"]))
    tokens = [Token(**t) for t in tokens_raw]
    units = [Unit(**u) for u in units_raw]
    images = [PageImage(**i) for i in images_raw]
    return Page(
        page_index=row["page_index"],
        text=row["text"],
        tokens=tokens,
        units=units,
        images=images,
    )


def page_load(book_id: int, page_index: int) -> Page | None:
    """Load a single :class:`Page` by ``(book_id, page_index)`` or ``None``."""
    conn = get_db()
    cur = conn.execute(
        "SELECT page_index, text, tokens_gz, units_gz, images_gz "
        "FROM pages WHERE book_id = ? AND page_index = ?",
        (book_id, page_index),
    )
    row = cur.fetchone()
    return _row_to_page(row) if row else None


def progress_set(
    book_id: int,
    page_index: int,
    page_offset: float,
    *,
    user_id: int = SEED_USER_ID,
) -> None:
    """UPSERT the reading progress row for ``book_id``.

    Called by ``POST /api/books/{id}/progress`` whenever the frontend
    persists a new position. The ``ON CONFLICT(book_id)`` clause makes
    this idempotent without a separate "exists?" query — a single
    round-trip covers both the first save and every subsequent update.
    """
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO reading_progress(user_id, book_id, last_page_index, "
            "last_page_offset, updated_at) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, book_id) DO UPDATE SET "
            "last_page_index=excluded.last_page_index, "
            "last_page_offset=excluded.last_page_offset, "
            "updated_at=excluded.updated_at",
            (
                user_id,
                book_id,
                page_index,
                page_offset,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def progress_get(book_id: int, *, user_id: int = SEED_USER_ID) -> tuple[int, float]:
    """Return ``(last_page_index, last_page_offset)`` or ``(0, 0.0)``.

    The zero fallback keeps ``/content`` simple: the frontend always
    gets a numeric pair and never has to distinguish "new book" from
    "position cleared" — both mean "start at the top".
    """
    conn = get_db()
    cur = conn.execute(
        "SELECT last_page_index, last_page_offset FROM reading_progress "
        "WHERE user_id = ? AND book_id = ?",
        (user_id, book_id),
    )
    row = cur.fetchone()
    if row is None:
        return (0, 0.0)
    return (int(row["last_page_index"]), float(row["last_page_offset"]))


def pages_load_slice(book_id: int, offset: int, limit: int) -> list[Page]:
    """Return up to ``limit`` pages from ``offset``, ordered by ``page_index``.

    Empty result if the book is unknown, the offset is past the last page,
    or ``limit <= 0``.
    """
    if limit <= 0:
        return []
    conn = get_db()
    cur = conn.execute(
        "SELECT page_index, text, tokens_gz, units_gz, images_gz "
        "FROM pages WHERE book_id = ? ORDER BY page_index ASC LIMIT ? OFFSET ?",
        (book_id, limit, offset),
    )
    return [_row_to_page(row) for row in cur.fetchall()]


# ---------- users DAO (M11.2) ----------


def _row_to_user(row: sqlite3.Row) -> User:
    # M18.1: telegram_id is optional — schema_v<9 rows lack the column,
    # so we defensively try/except the lookup instead of trusting
    # ``row["telegram_id"]`` (which would KeyError on pre-v9 readers).
    try:
        tg = row["telegram_id"]
    except (IndexError, KeyError):
        tg = None
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
        current_book_id=row["current_book_id"],
        telegram_id=tg,
    )


def user_create(email: str, password_hash: str) -> int:
    """Insert a new user row and return its id.

    The caller is expected to have already normalised ``email`` via
    :func:`en_reader.auth.normalize_email` — this DAO stores it verbatim.
    On UNIQUE-constraint violation (duplicate email) raises
    :class:`en_reader.auth.EmailExistsError`. We lazy-import the exception
    inside the function to dodge the circular import between ``auth`` and
    ``storage`` (``auth`` doesn't touch storage, but the app module pulls
    in both).
    """
    from .auth import EmailExistsError  # lazy: avoid import cycle

    conn = get_db()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, created_at) VALUES(?, ?, ?)",
                (email, password_hash, created_at),
            )
    except sqlite3.IntegrityError as e:
        raise EmailExistsError(email) from e
    return int(cur.lastrowid)


def user_by_email(email: str) -> User | None:
    """Return the :class:`User` with this ``email`` or ``None``."""
    conn = get_db()
    cur = conn.execute(
        "SELECT id, email, password_hash, created_at, current_book_id, telegram_id "
        "FROM users WHERE email = ?",
        (email,),
    )
    row = cur.fetchone()
    return _row_to_user(row) if row else None


def user_by_id(user_id: int) -> User | None:
    """Return the :class:`User` with this ``id`` or ``None``."""
    conn = get_db()
    cur = conn.execute(
        "SELECT id, email, password_hash, created_at, current_book_id, telegram_id "
        "FROM users WHERE id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    return _row_to_user(row) if row else None


def user_by_telegram(telegram_id: int) -> User | None:
    """Return the user linked to ``telegram_id`` or None (M18.1)."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, password_hash, created_at, current_book_id, telegram_id "
        "FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    return _row_to_user(row) if row else None


def user_upsert_telegram(
    telegram_id: int,
    *,
    display_name: str | None = None,
) -> User:
    """Return a :class:`User` for this Telegram id, creating it if absent.

    Telegram-only accounts carry a synthetic ``tg-<id>@telegram.local``
    email (the users.email column is NOT NULL UNIQUE from v5) and a
    ``__tg_no_password__`` sentinel in ``password_hash``. The /auth/login
    handler rejects that sentinel so the Mini-App user can't be logged
    in with any password — only with a valid Telegram initData.
    """
    existing = user_by_telegram(telegram_id)
    if existing is not None:
        return existing
    conn = get_db()
    created_at = datetime.now(timezone.utc).isoformat()
    email = f"tg-{telegram_id}@telegram.local"
    # Collision path: someone could have already registered with this
    # synthetic email (extremely unlikely, but guard anyway). Retry with
    # a suffix on IntegrityError.
    with conn:
        try:
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, created_at, telegram_id) "
                "VALUES(?, ?, ?, ?)",
                (email, "__tg_no_password__", created_at, telegram_id),
            )
        except sqlite3.IntegrityError:
            email = f"tg-{telegram_id}-{int(datetime.now().timestamp())}@telegram.local"
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, created_at, telegram_id) "
                "VALUES(?, ?, ?, ?)",
                (email, "__tg_no_password__", created_at, telegram_id),
            )
    uid = int(cur.lastrowid)
    return user_by_id(uid)  # type: ignore[return-value]


# ---------- account linking / merging (M18.4) ----------


def user_has_data(user_id: int) -> bool:
    """True if ``user_id`` owns at least one dictionary word, book, progress row,
    or training-activity row. Used by the link flow to skip the "whose data to
    keep" prompt when one side is empty — auto-merging is safe then.
    """
    conn = get_db()
    row = conn.execute(
        """
        SELECT
          (SELECT 1 FROM user_dictionary WHERE user_id = ? LIMIT 1) AS ud,
          (SELECT 1 FROM books           WHERE user_id = ? LIMIT 1) AS bk,
          (SELECT 1 FROM reading_progress WHERE user_id = ? LIMIT 1) AS rp,
          (SELECT 1 FROM daily_activity  WHERE user_id = ? LIMIT 1) AS da
        """,
        (user_id, user_id, user_id, user_id),
    ).fetchone()
    return any(row[k] is not None for k in ("ud", "bk", "rp", "da"))


def user_merge(dest_id: int, src_id: int) -> None:
    """Move every per-user row from ``src_id`` into ``dest_id`` and delete src.

    All in one transaction:

    * ``books`` reassigns outright (no UNIQUE on ``user_id``).
    * ``user_dictionary`` uses UNIQUE(user_id, lemma) — drop src's duplicates
      first so dest's already-trained version wins; then reassign the rest.
    * ``reading_progress`` has UNIQUE(user_id, book_id), but ``book_id`` is
      globally unique per row in ``books`` — no cross-conflicts possible
      after the books move — so a blanket reassign is safe.
    * ``daily_activity`` (UNIQUE(user_id, date)) drops src rows for days
      dest already has (dest's counters stay), reassigns the rest.
    * ``users.telegram_id`` must be released from src first (partial UNIQUE
      index) before dest can claim it. ``current_book_id`` on dest falls
      back to src's if dest didn't have one.
    * Finally ``DELETE FROM users WHERE id = src`` — ``ON DELETE CASCADE``
      picks up any link_tokens still pointing at src.

    Caller holds the business-logic sanity — this function assumes the two
    ids already passed the "should we merge?" checks and just does the
    UPDATE / DELETE work.
    """
    conn = get_db()
    with conn:  # single BEGIN/COMMIT
        conn.execute(
            "UPDATE books SET user_id = ? WHERE user_id = ?", (dest_id, src_id)
        )
        conn.execute(
            "DELETE FROM user_dictionary WHERE user_id = ? AND lemma IN "
            "(SELECT lemma FROM user_dictionary WHERE user_id = ?)",
            (src_id, dest_id),
        )
        conn.execute(
            "UPDATE user_dictionary SET user_id = ? WHERE user_id = ?",
            (dest_id, src_id),
        )
        conn.execute(
            "UPDATE reading_progress SET user_id = ? WHERE user_id = ?",
            (dest_id, src_id),
        )
        conn.execute(
            "DELETE FROM daily_activity WHERE user_id = ? AND date IN "
            "(SELECT date FROM daily_activity WHERE user_id = ?)",
            (src_id, dest_id),
        )
        conn.execute(
            "UPDATE daily_activity SET user_id = ? WHERE user_id = ?",
            (dest_id, src_id),
        )
        src_row = conn.execute(
            "SELECT telegram_id, current_book_id FROM users WHERE id = ?",
            (src_id,),
        ).fetchone()
        if src_row is None:
            return  # src already gone — nothing to do
        src_tg = src_row["telegram_id"]
        src_cur_book = src_row["current_book_id"]
        # Release UNIQUE on telegram_id before claiming it on dest.
        conn.execute("UPDATE users SET telegram_id = NULL WHERE id = ?", (src_id,))
        if src_tg is not None:
            conn.execute(
                "UPDATE users SET telegram_id = ? WHERE id = ?", (src_tg, dest_id)
            )
        if src_cur_book is not None:
            conn.execute(
                "UPDATE users SET current_book_id = ? WHERE id = ? "
                "AND current_book_id IS NULL",
                (src_cur_book, dest_id),
            )
        conn.execute("DELETE FROM users WHERE id = ?", (src_id,))


# ---------- link_tokens (M18.4) ----------
#
# One-time tokens the /auth/link/telegram flow mints. The authenticated
# web session creates a token, the user then taps a ``t.me/<bot>?start=
# link_<token>`` deep link, and the bot's webhook consumes the token to
# pair the local user with ``message.from.id``. Status transitions:
#
#     pending  → done              (no conflict, no merge needed)
#     pending  → conflict_waiting  → done   (inline keyboard → callback)
#     pending  → failed            (bad token, user refused, etc.)
#
# TTL is enforced in ``link_token_get`` by comparing ``created_at`` to
# now minus 10 minutes; stale rows are ignored but not deleted synchronously.


LINK_TOKEN_TTL_SECONDS = 600


@dataclass
class LinkToken:
    """Snapshot of a ``link_tokens`` row the webhook / status poller reads."""

    token: str
    user_id: int
    created_at: str
    status: str  # 'pending' | 'conflict_waiting' | 'done' | 'failed' | 'expired'
    other_user_id: int | None
    chat_id: int | None
    message_id: int | None
    result: str | None


def _row_to_link_token(row: sqlite3.Row) -> LinkToken:
    return LinkToken(
        token=row["token"],
        user_id=int(row["user_id"]),
        created_at=row["created_at"],
        status=row["status"],
        other_user_id=row["other_user_id"],
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        result=row["result"],
    )


def link_token_create(user_id: int) -> str:
    """Mint a fresh link-flow token for ``user_id``. 32 bytes of urandom."""
    import secrets

    token = secrets.token_urlsafe(24)
    conn = get_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO link_tokens(token, user_id, created_at) VALUES(?, ?, ?)",
            (token, user_id, created_at),
        )
    return token


def link_token_get(token: str) -> LinkToken | None:
    """Return the token row if present and not TTL-expired, else None.

    Expiry is lazy: rows past the TTL still exist in the table (cleanup is
    nobody's hot path); we just refuse to return them. That keeps the
    status endpoint's semantics simple — expired == gone — while leaving
    DELETE for a future broom task.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT token, user_id, created_at, status, other_user_id, chat_id, "
        "message_id, result FROM link_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    # Parse the ISO timestamp we wrote.
    try:
        created = datetime.fromisoformat(row["created_at"])
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    if (now - created).total_seconds() > LINK_TOKEN_TTL_SECONDS:
        return None
    return _row_to_link_token(row)


def link_token_update(
    token: str,
    *,
    status: str | None = None,
    other_user_id: int | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    result: str | None = None,
) -> None:
    """Partial-update a link token. Only non-None fields are written.

    Writing ``None`` to clear a column isn't needed by the current flow,
    so skipping None keeps callers from accidentally zeroing out the
    conflict-keyboard pointers when they only meant to set ``status``.
    """
    sets: list[str] = []
    vals: list[object] = []
    if status is not None:
        sets.append("status = ?")
        vals.append(status)
    if other_user_id is not None:
        sets.append("other_user_id = ?")
        vals.append(other_user_id)
    if chat_id is not None:
        sets.append("chat_id = ?")
        vals.append(chat_id)
    if message_id is not None:
        sets.append("message_id = ?")
        vals.append(message_id)
    if result is not None:
        sets.append("result = ?")
        vals.append(result)
    if not sets:
        return
    vals.append(token)
    conn = get_db()
    with conn:
        conn.execute(
            f"UPDATE link_tokens SET {', '.join(sets)} WHERE token = ?",
            tuple(vals),
        )


# ---------- tiny aggregate helpers (M14.1) ----------


def count_users() -> int:
    """Return the total number of rows in ``users``.

    Includes the migration-seeded ``seed@local`` placeholder; callers that
    want "real" users should subtract one, but for /debug/health we just
    want a ballpark figure.
    """
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"]) if row else 0


def count_books() -> int:
    """Return the total number of rows in ``books`` across all users."""
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS n FROM books").fetchone()
    return int(row["n"]) if row else 0


# ---------- catalog (M16.5) ----------


CATALOG_LEVELS = ("A1", "A2", "B1", "B2", "C1")


def catalog_upsert(
    *,
    title: str,
    author: str,
    level: str,
    pages: int,
    tags: list[str],
    cover_preset: str,
    source_url: str | None,
    source_path: str,
    language: str = "en",
) -> int:
    """Insert or leave-alone a ``catalog_books`` row keyed on (title, author).

    Idempotency is enforced by the ``UNIQUE(title, author)`` constraint
    from the v6→v7 migration. Returns the row id either way so the
    seed script can log what it touched.
    """
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO catalog_books(title, author, language, level, pages, "
            "tags, cover_preset, source_url, source_path, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(title, author) DO NOTHING",
            (
                title,
                author,
                language,
                level,
                pages,
                json.dumps(tags),
                cover_preset,
                source_url,
                source_path,
                now,
            ),
        )
    row = conn.execute(
        "SELECT id FROM catalog_books WHERE title = ? AND author = ?",
        (title, author),
    ).fetchone()
    return int(row["id"])


def _row_to_catalog_item(row: sqlite3.Row) -> dict:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except (TypeError, json.JSONDecodeError):
        tags = []
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "author": row["author"],
        "level": row["level"],
        "pages": int(row["pages"]),
        "tags": tags,
        "cover_preset": row["cover_preset"],
    }


def catalog_list() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, author, level, pages, tags, cover_preset "
        "FROM catalog_books ORDER BY level, title"
    ).fetchall()
    return [_row_to_catalog_item(r) for r in rows]


def catalog_get(catalog_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT id, title, author, language, level, pages, tags, "
        "cover_preset, source_url, source_path, created_at "
        "FROM catalog_books WHERE id = ?",
        (catalog_id,),
    ).fetchone()
    if row is None:
        return None
    out = _row_to_catalog_item(row)
    out["language"] = row["language"]
    out["source_url"] = row["source_url"]
    out["source_path"] = row["source_path"]
    return out


def catalog_sections(user_level: str = "B1") -> list[dict]:
    """Group catalog books into UI sections per the M16.5 spec.

    * "По твоему уровню" — ``level`` within ±1 of ``user_level``
      (e.g. B1 → A2/B1/B2).
    * "Короткое — за выходные" — anything tagged ``short``.
    * "Все книги" — everything else.

    A book can appear in multiple sections; the UI dedupes visually.
    Order inside each section is by ``level`` then ``title``.
    """
    if user_level not in CATALOG_LEVELS:
        user_level = "B1"
    idx = CATALOG_LEVELS.index(user_level)
    neighbours = set(CATALOG_LEVELS[max(0, idx - 1) : idx + 2])
    items = catalog_list()

    by_level = [it for it in items if it["level"] in neighbours]
    shorts = [it for it in items if "short" in it["tags"]]
    return [
        {"key": "По твоему уровню", "items": by_level},
        {"key": "Короткое — за выходные", "items": shorts},
        {"key": "Все книги", "items": items},
    ]


def catalog_already_imported(catalog_id: int, *, user_id: int = SEED_USER_ID) -> int | None:
    """Return the user's ``books.id`` for a previously-imported catalog row, or None.

    Dedup is on (title, author) — the same pair in the user's library is
    treated as "already imported" even if the book got there via upload.
    """
    entry = catalog_get(catalog_id)
    if entry is None:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM books WHERE user_id = ? AND title = ? AND " "(author IS ? OR author = ?)",
        (user_id, entry["title"], entry["author"], entry["author"]),
    ).fetchone()
    return int(row["id"]) if row else None


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
