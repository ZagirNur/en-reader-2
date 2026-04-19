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

from .models import BookMeta, Page, PageImage, Token, Unit

if TYPE_CHECKING:
    from .parsers import ParsedBook

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


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
    _migrate_v1_to_v2,
    _migrate_v2_to_v3,
    _migrate_v3_to_v4,
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


def book_save(parsed: "ParsedBook") -> int:
    """Run the full analyse + chunk + persist pipeline for ``parsed``.

    Runs in a single ``with conn:`` transaction so a failure midway leaves
    the DB untouched. ``parsed.text`` is expected to already contain
    ``IMG<id>`` markers at the desired positions (the seed script injects
    them before calling this); this function takes care of masking those
    marker tokens before chunking and recomputing per-page ``PageImage``
    lists post-chunk by scanning each page's ``text``.
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
    with conn:
        cur = conn.execute(
            "INSERT INTO books(title, author, language, source_format, "
            "source_bytes_size, total_pages, cover_path, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
        # cover_path handling lands with the real parsers in M12.
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


def book_meta(book_id: int) -> BookMeta | None:
    """Return the :class:`BookMeta` for ``book_id`` or ``None`` if missing."""
    conn = get_db()
    cur = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
    row = cur.fetchone()
    return _row_to_book_meta(row) if row else None


def book_list() -> list[BookMeta]:
    """Return every book, newest first (ordered by ``created_at DESC``)."""
    conn = get_db()
    cur = conn.execute("SELECT * FROM books ORDER BY created_at DESC, id DESC")
    return [_row_to_book_meta(row) for row in cur.fetchall()]


def book_delete(book_id: int) -> None:
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
        conn.execute("DELETE FROM book_images WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM pages WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        # M10.5: clear current-book pointer if it matched this book. We read
        # + write inside the same `with conn:` block so the cascade lands
        # atomically.
        row = conn.execute("SELECT value FROM meta WHERE key='current_book_id'").fetchone()
        if row and row["value"] and int(row["value"]) == book_id:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('current_book_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("",),
            )


# ---------- current-book DAO (M10.5) ----------


def current_book_get() -> int | None:
    """Return the current-book id from ``meta``, or ``None`` if unset.

    Stored as a string in ``meta.value`` (``""`` meaning "no current book")
    so we don't have to invent a new sentinel value or a second column.
    M11.1 will migrate this to ``users.current_book_id``.
    """
    conn = get_db()
    row = conn.execute("SELECT value FROM meta WHERE key='current_book_id'").fetchone()
    if not row or not row["value"]:
        return None
    return int(row["value"])


def current_book_set(book_id: int | None) -> None:
    """UPSERT the current-book pointer. ``None`` clears it.

    Callers: ``POST /api/me/current-book`` and ``book_delete`` (cascade).
    The UPSERT keeps this idempotent without a separate "exists?" query.
    """
    val = "" if book_id is None else str(book_id)
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('current_book_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (val,),
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


def progress_set(book_id: int, page_index: int, page_offset: float) -> None:
    """UPSERT the reading progress row for ``book_id``.

    Called by ``POST /api/books/{id}/progress`` whenever the frontend
    persists a new position. The ``ON CONFLICT(book_id)`` clause makes
    this idempotent without a separate "exists?" query — a single
    round-trip covers both the first save and every subsequent update.
    """
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO reading_progress(book_id, last_page_index, "
            "last_page_offset, updated_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(book_id) DO UPDATE SET "
            "last_page_index=excluded.last_page_index, "
            "last_page_offset=excluded.last_page_offset, "
            "updated_at=excluded.updated_at",
            (
                book_id,
                page_index,
                page_offset,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def progress_get(book_id: int) -> tuple[int, float]:
    """Return ``(last_page_index, last_page_offset)`` or ``(0, 0.0)``.

    The zero fallback keeps ``/content`` simple: the frontend always
    gets a numeric pair and never has to distinguish "new book" from
    "position cleared" — both mean "start at the top".
    """
    conn = get_db()
    cur = conn.execute(
        "SELECT last_page_index, last_page_offset FROM reading_progress " "WHERE book_id = ?",
        (book_id,),
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
