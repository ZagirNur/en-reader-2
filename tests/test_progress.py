"""Tests for M10.1 reading-progress storage + POST /progress endpoint.

Covers the storage DAO pair (``progress_set`` / ``progress_get``), the
UPSERT contract (at most one row per book), the REST handler's validation
stack (404 / 400 / 422 precedence), round-tripping through
``GET /api/books/{id}/content``, and the FK cascade on book deletion.
Relies on the autouse ``tmp_db`` fixture from ``conftest.py`` so every
test starts with an empty SQLite file and closes its connection cleanly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_progress_set_and_get() -> None:
    book_id = seed_main(_FIXTURE)
    storage.progress_set(book_id, 0, 0.5)
    assert storage.progress_get(book_id) == (0, 0.5)


def test_progress_set_is_upsert() -> None:
    book_id = seed_main(_FIXTURE)
    storage.progress_set(book_id, 0, 0.25)
    storage.progress_set(book_id, 0, 0.75)

    conn = storage.get_db()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM reading_progress WHERE book_id = ?",
        (book_id,),
    ).fetchone()["c"]
    assert count == 1
    # Second value wins.
    assert storage.progress_get(book_id) == (0, 0.75)


def test_progress_get_default_for_new_book() -> None:
    # No set call for this book_id — DAO must return the zero pair.
    assert storage.progress_get(12345) == (0, 0.0)


def test_post_progress_204() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 0.5},
    )
    assert resp.status_code == 204
    assert resp.content == b""


def test_content_returns_progress() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 0.42},
    )
    body = client.get(f"/api/books/{book_id}/content").json()
    assert body["last_page_index"] == 0
    assert body["last_page_offset"] == 0.42


def test_post_progress_invalid_offset_422() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 1.5},
    )
    assert resp.status_code == 422


def test_post_progress_invalid_offset_negative_422() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": -0.1},
    )
    assert resp.status_code == 422


def test_post_progress_page_out_of_range_400() -> None:
    book_id = seed_main(_FIXTURE)
    meta = storage.book_meta(book_id)
    assert meta is not None
    client = TestClient(app)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": meta.total_pages, "last_page_offset": 0.0},
    )
    assert resp.status_code == 400


def test_post_progress_missing_book_404() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/books/999/progress",
        json={"last_page_index": 0, "last_page_offset": 0.5},
    )
    assert resp.status_code == 404


def test_delete_book_cascades_progress() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 0.5},
    )
    # Sanity: row exists.
    conn = storage.get_db()
    assert (
        conn.execute(
            "SELECT COUNT(*) AS c FROM reading_progress WHERE book_id = ?",
            (book_id,),
        ).fetchone()["c"]
        == 1
    )

    resp = client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 204

    # FK cascade wipes the progress row.
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM reading_progress WHERE book_id = ?",
        (book_id,),
    ).fetchone()["c"]
    assert count == 0
