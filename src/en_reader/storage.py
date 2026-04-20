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
from dataclasses import asdict
from datetime import datetime, timezone
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


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
    _migrate_v1_to_v2,
    _migrate_v2_to_v3,
    _migrate_v3_to_v4,
    _migrate_v4_to_v5,
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


def dict_add(lemma: str, translation: str, *, user_id: int = SEED_USER_ID) -> None:
    """Insert ``(lemma, translation)`` if the lemma is not already present.

    First write wins — updates require an explicit ``dict_remove`` + add.
    ``user_id`` defaults to :data:`SEED_USER_ID` so pre-M11 call sites keep
    working without changes.
    """
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, ?, ?, ?)",
            (
                user_id,
                lemma.lower(),
                translation,
                datetime.now(timezone.utc).isoformat(),
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
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
        current_book_id=row["current_book_id"],
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
        "SELECT id, email, password_hash, created_at, current_book_id "
        "FROM users WHERE email = ?",
        (email,),
    )
    row = cur.fetchone()
    return _row_to_user(row) if row else None


def user_by_id(user_id: int) -> User | None:
    """Return the :class:`User` with this ``id`` or ``None``."""
    conn = get_db()
    cur = conn.execute(
        "SELECT id, email, password_hash, created_at, current_book_id " "FROM users WHERE id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    return _row_to_user(row) if row else None


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
