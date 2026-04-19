"""Tests for M10.1 reading-progress storage + POST /progress endpoint.

Covers the storage DAO pair (``progress_set`` / ``progress_get``), the
UPSERT contract (at most one row per book), the REST handler's validation
stack (404 / 400 / 422 precedence), round-tripping through
``GET /api/books/{id}/content``, and the FK cascade on book deletion.
Relies on the autouse ``tmp_db`` fixture from ``conftest.py`` plus the
authenticated ``client`` fixture (M11.3) for the guarded endpoints.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    return user.id


def test_progress_set_and_get(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    storage.progress_set(book_id, 0, 0.5, user_id=_fixture_user_id())
    assert storage.progress_get(book_id, user_id=_fixture_user_id()) == (0, 0.5)


def test_progress_set_is_upsert(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    uid = _fixture_user_id()
    storage.progress_set(book_id, 0, 0.25, user_id=uid)
    storage.progress_set(book_id, 0, 0.75, user_id=uid)

    conn = storage.get_db()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM reading_progress WHERE book_id = ?",
        (book_id,),
    ).fetchone()["c"]
    assert count == 1
    # Second value wins.
    assert storage.progress_get(book_id, user_id=uid) == (0, 0.75)


def test_progress_get_default_for_new_book() -> None:
    # No set call for this book_id — DAO must return the zero pair.
    assert storage.progress_get(12345) == (0, 0.0)


def test_post_progress_204(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 0.5},
    )
    assert resp.status_code == 204
    assert resp.content == b""


def test_content_returns_progress(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 0.42},
    )
    body = client.get(f"/api/books/{book_id}/content").json()
    assert body["last_page_index"] == 0
    assert body["last_page_offset"] == 0.42


def test_post_progress_invalid_offset_422(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 1.5},
    )
    assert resp.status_code == 422


def test_post_progress_invalid_offset_negative_422(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": -0.1},
    )
    assert resp.status_code == 422


def test_post_progress_page_out_of_range_400(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    meta = storage.book_meta(book_id)
    assert meta is not None
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": meta.total_pages, "last_page_offset": 0.0},
    )
    assert resp.status_code == 400


def test_post_progress_missing_book_404(client: TestClient) -> None:
    resp = client.post(
        "/api/books/999/progress",
        json={"last_page_index": 0, "last_page_offset": 0.5},
    )
    assert resp.status_code == 404


def test_delete_book_cascades_progress(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
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
