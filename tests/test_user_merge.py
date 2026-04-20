"""Tests for :func:`storage.user_merge` + :func:`storage.user_has_data` (M18.4).

Merge collapses two user rows — typically an email account (dest) and a
Telegram-only account (src) that the owner wants to link together — into
one. We verify:

* Data rows (``books``, ``user_dictionary``, ``reading_progress``,
  ``daily_activity``) reassign from ``src`` to ``dest`` without tripping
  the per-table UNIQUE constraints.
* Conflicting ``user_dictionary`` lemmas keep dest's version (already
  trained); conflicting ``daily_activity`` dates keep dest's counters.
* ``telegram_id`` flips over to dest (the partial UNIQUE index requires
  a two-step release-then-claim to avoid a mid-transaction violation).
* ``users.id = src`` is deleted after the move — ``ON DELETE CASCADE``
  cleans up any link_tokens without a separate sweep.
* ``user_has_data`` returns ``True`` as soon as any of the four
  owned-by-user tables is non-empty, ``False`` on a brand-new row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from en_reader import storage


@pytest.fixture()
def reset_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_file = tmp_path / "merge.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    storage._reset_for_tests()
    storage.migrate()
    yield db_file
    storage._reset_for_tests()


def _mk_user(email: str, *, telegram_id: int | None = None) -> int:
    """Insert a fresh users row and return its id.

    Skips the auth-flow plumbing (hash_password etc.) — these tests only
    care about the storage-layer merge, not the HTTP surface.
    """
    conn = storage.get_db()
    with conn:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, created_at, telegram_id) "
            "VALUES(?, ?, datetime('now'), ?)",
            (email, "h", telegram_id),
        )
    return int(cur.lastrowid)


def _add_book(user_id: int, title: str) -> int:
    conn = storage.get_db()
    with conn:
        cur = conn.execute(
            "INSERT INTO books(user_id, title, author, language, source_format, "
            "source_bytes_size, total_pages, created_at) "
            "VALUES(?, ?, 'A', 'en', 'txt', 10, 1, datetime('now'))",
            (user_id, title),
        )
    return int(cur.lastrowid)


def _add_dict(user_id: int, lemma: str, translation: str) -> None:
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, ?, ?, datetime('now'))",
            (user_id, lemma, translation),
        )


def _add_progress(user_id: int, book_id: int, page: int) -> None:
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO reading_progress(user_id, book_id, last_page_index, "
            "last_page_offset, updated_at) VALUES(?, ?, ?, 0, datetime('now'))",
            (user_id, book_id, page),
        )


def _add_daily(user_id: int, date: str, correct: int, total: int) -> None:
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO daily_activity(user_id, date, words_trained_correct, "
            "words_trained_total) VALUES(?, ?, ?, ?)",
            (user_id, date, correct, total),
        )


def _count_for_user(table: str, user_id: int) -> int:
    conn = storage.get_db()
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,)
    ).fetchone()
    return int(row["n"])


# ---------- user_has_data ----------


def test_has_data_false_on_fresh_user(reset_db: Path) -> None:
    uid = _mk_user("fresh@x.test")
    assert storage.user_has_data(uid) is False


def test_has_data_true_with_dictionary(reset_db: Path) -> None:
    uid = _mk_user("a@x.test")
    _add_dict(uid, "anxious", "встревоженный")
    assert storage.user_has_data(uid) is True


def test_has_data_true_with_book(reset_db: Path) -> None:
    uid = _mk_user("b@x.test")
    _add_book(uid, "Book")
    assert storage.user_has_data(uid) is True


def test_has_data_true_with_daily_activity(reset_db: Path) -> None:
    uid = _mk_user("d@x.test")
    _add_daily(uid, "2026-04-21", 3, 5)
    assert storage.user_has_data(uid) is True


# ---------- user_merge happy paths ----------


def test_merge_moves_books_and_deletes_src(reset_db: Path) -> None:
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=111)
    _add_book(src, "Only Book")

    storage.user_merge(dest_id=dest, src_id=src)

    assert _count_for_user("books", dest) == 1
    assert storage.user_by_id(src) is None
    # telegram_id migrates to dest on merge.
    dest_user = storage.user_by_id(dest)
    assert dest_user is not None and dest_user.telegram_id == 111


def test_merge_dict_conflict_dest_wins(reset_db: Path) -> None:
    """Same lemma in both → dest's translation stays (treated as canonical)."""
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=222)
    _add_dict(dest, "anxious", "встревоженный")  # dest's
    _add_dict(src, "anxious", "тревожный")       # conflicts, must be dropped
    _add_dict(src, "brave", "смелый")            # unique — migrates

    storage.user_merge(dest_id=dest, src_id=src)

    conn = storage.get_db()
    rows = {
        r["lemma"]: r["translation"]
        for r in conn.execute(
            "SELECT lemma, translation FROM user_dictionary WHERE user_id = ?",
            (dest,),
        )
    }
    assert rows == {"anxious": "встревоженный", "brave": "смелый"}


def test_merge_reading_progress_moves(reset_db: Path) -> None:
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=333)
    book = _add_book(src, "X")
    _add_progress(src, book, 7)

    storage.user_merge(dest_id=dest, src_id=src)

    conn = storage.get_db()
    row = conn.execute(
        "SELECT user_id, book_id, last_page_index FROM reading_progress"
    ).fetchone()
    assert row["user_id"] == dest
    assert row["last_page_index"] == 7


def test_merge_daily_activity_keeps_dest_on_conflict(reset_db: Path) -> None:
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=444)
    _add_daily(dest, "2026-04-20", correct=2, total=4)  # conflicts — dest wins
    _add_daily(src, "2026-04-20", correct=9, total=9)
    _add_daily(src, "2026-04-19", correct=1, total=1)   # non-conflicting

    storage.user_merge(dest_id=dest, src_id=src)

    conn = storage.get_db()
    rows = {
        r["date"]: (r["words_trained_correct"], r["words_trained_total"])
        for r in conn.execute(
            "SELECT date, words_trained_correct, words_trained_total "
            "FROM daily_activity WHERE user_id = ?",
            (dest,),
        )
    }
    assert rows == {"2026-04-20": (2, 4), "2026-04-19": (1, 1)}


def test_merge_telegram_id_hand_off(reset_db: Path) -> None:
    """Partial UNIQUE on telegram_id: release from src, then claim on dest.

    Doing it in the wrong order (claim first) would hit the index. This
    test would fail with an IntegrityError if user_merge forgot the
    release step.
    """
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=555)
    storage.user_merge(dest_id=dest, src_id=src)
    dest_user = storage.user_by_id(dest)
    assert dest_user is not None and dest_user.telegram_id == 555
    # And src is gone — the UNIQUE index has exactly one non-NULL row.
    conn = storage.get_db()
    rows = conn.execute(
        "SELECT id FROM users WHERE telegram_id = 555"
    ).fetchall()
    assert len(rows) == 1 and rows[0]["id"] == dest


def test_merge_current_book_falls_back(reset_db: Path) -> None:
    """Dest keeps its current_book_id if set, else inherits src's."""
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=666)
    src_book = _add_book(src, "Src Book")
    conn = storage.get_db()
    with conn:
        conn.execute(
            "UPDATE users SET current_book_id = ? WHERE id = ?", (src_book, src)
        )
    storage.user_merge(dest_id=dest, src_id=src)
    dest_user = storage.user_by_id(dest)
    assert dest_user is not None and dest_user.current_book_id == src_book


def test_merge_preserves_dest_current_book(reset_db: Path) -> None:
    """If dest already has a current book, merging doesn't overwrite it."""
    dest = _mk_user("dest@x.test")
    src = _mk_user("src@x.test", telegram_id=777)
    dest_book = _add_book(dest, "Dest Book")
    src_book = _add_book(src, "Src Book")
    conn = storage.get_db()
    with conn:
        conn.execute("UPDATE users SET current_book_id = ? WHERE id = ?", (dest_book, dest))
        conn.execute("UPDATE users SET current_book_id = ? WHERE id = ?", (src_book, src))
    storage.user_merge(dest_id=dest, src_id=src)
    dest_user = storage.user_by_id(dest)
    assert dest_user is not None and dest_user.current_book_id == dest_book


def test_merge_empty_src_is_noop_on_data(reset_db: Path) -> None:
    """A src with no data just hands off its telegram_id and vanishes."""
    dest = _mk_user("dest@x.test")
    _add_book(dest, "Dest Book")
    src = _mk_user("src@x.test", telegram_id=888)
    assert storage.user_has_data(src) is False

    storage.user_merge(dest_id=dest, src_id=src)

    assert _count_for_user("books", dest) == 1
    assert storage.user_by_id(src) is None
    dest_user = storage.user_by_id(dest)
    assert dest_user is not None and dest_user.telegram_id == 888
