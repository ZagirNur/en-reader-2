"""Tests for the SQLite-backed storage layer (M6.1).

Exercises the ``dict_*`` DAO, migration idempotency, and
survival-across-reopen so we catch regressions in the connection
lifecycle. Each test gets its own tmp DB via the ``tmp_db`` autouse
fixture in ``conftest.py``; a local ``reset_db`` fixture provides the
same setup explicitly so these tests document the contract without
relying on globals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from en_reader import storage


@pytest.fixture()
def reset_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pin DB_PATH to a per-test file and apply migrations.

    Redundant with the autouse ``tmp_db`` fixture in conftest.py, but
    kept explicit so these tests spell out the usage pattern. Returns
    the DB file path for tests that need to inspect it.
    """
    db_file = tmp_path / "storage.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    storage._reset_for_tests()
    storage.migrate()
    yield db_file
    storage._reset_for_tests()


def test_dict_add_and_get(reset_db: Path) -> None:
    storage.dict_add("ominous", "зловещий")
    assert storage.dict_get("ominous") == "зловещий"
    # Case-insensitive on the read side too.
    assert storage.dict_get("Ominous") == "зловещий"


def test_dict_add_ignores_duplicate(reset_db: Path) -> None:
    storage.dict_add("ominous", "зловещий")
    storage.dict_add("ominous", "грозный")
    # First write wins (INSERT OR IGNORE).
    assert storage.dict_get("ominous") == "зловещий"


def test_dict_remove(reset_db: Path) -> None:
    storage.dict_add("ominous", "зловещий")
    storage.dict_remove("ominous")
    assert storage.dict_get("ominous") is None
    # Removing a missing key is a no-op, not an error.
    storage.dict_remove("ominous")


def test_dict_all(reset_db: Path) -> None:
    storage.dict_add("ominous", "зловещий")
    storage.dict_add("gather", "собирать")
    assert storage.dict_all() == {
        "ominous": "зловещий",
        "gather": "собирать",
    }


def test_migrate_idempotent(reset_db: Path) -> None:
    # reset_db already ran migrate() once; running it again must be safe.
    storage.migrate()
    storage.migrate()
    conn = storage.get_db()
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert row["value"] == str(len(storage.MIGRATIONS))


def test_persistence_across_reopen(reset_db: Path) -> None:
    storage.dict_add("ominous", "зловещий")
    # Close the cached connection; next call reopens the same file.
    storage._reset_for_tests()
    assert storage.dict_get("ominous") == "зловещий"


def test_pack_unpack_roundtrip(reset_db: Path) -> None:
    """_pack / _unpack is the on-disk page-blob codec; it must round-trip.

    Covers the gzip+JSON helper pair used by page_load / pages_load_slice
    without needing to plumb a full book through analyse+chunk.
    """
    obj = {"x": 1, "xs": [1, 2, 3], "s": "hello"}
    packed = storage._pack(obj)
    assert isinstance(packed, bytes) and len(packed) > 0
    assert storage._unpack(packed) == obj


def test_migrate_idempotent_is_noop(reset_db: Path) -> None:
    """Calling migrate() a second time on a migrated DB is a no-op, not an error."""
    # reset_db already migrated once — run twice more.
    storage.migrate()
    storage.migrate()


def test_count_users_and_books_empty(reset_db: Path) -> None:
    """On a freshly migrated DB: one seed user, zero real books."""
    # The v4→v5 migration inserts the seed@local user, so count is 1, not 0.
    assert storage.count_users() == 1
    assert storage.count_books() == 0


def test_pages_load_slice_limits(reset_db: Path) -> None:
    """limit=0 short-circuits; offset past the end returns empty."""
    # limit=0 must return an empty list without even hitting the DB.
    assert storage.pages_load_slice(book_id=999, offset=0, limit=0) == []
    # offset past the end of a nonexistent book also yields empty.
    assert storage.pages_load_slice(book_id=999, offset=50, limit=10) == []
