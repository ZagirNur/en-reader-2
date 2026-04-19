"""Tests for the M9.1 books list + delete API.

Covers ``GET /api/books`` (ordering, ``has_cover`` flag) and
``DELETE /api/books/{id}`` (204 happy path with full row-level cascade,
404 for unknown ids). Uses the autouse ``tmp_db`` fixture from
``conftest.py`` so every test starts with an empty SQLite file, plus the
shared ``client`` fixture (M11.3) which signs up the fixture user the
seed calls below attach their books to.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_list_two_books_newest_first(client: TestClient) -> None:
    id1 = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    id2 = seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    assert id1 != id2

    resp = client.get("/api/books")
    assert resp.status_code == 200
    body = resp.json()

    assert isinstance(body, list)
    assert len(body) == 2
    # Newest (highest id, inserted last) comes first.
    assert body[0]["id"] == id2
    assert body[1]["id"] == id1
    # Shape sanity on the first item.
    assert set(body[0].keys()) == {"id", "title", "author", "total_pages", "has_cover"}
    assert body[0]["total_pages"] >= 1


def test_delete_book_cascades(client: TestClient) -> None:
    book_id = seed_main(_FIXTURE, email=FIXTURE_EMAIL)

    resp = client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 204
    assert resp.content == b""

    # List is now empty.
    assert client.get("/api/books").json() == []

    # Content endpoint for the deleted id 404s.
    assert client.get(f"/api/books/{book_id}/content").status_code == 404

    # Raw SQL: no orphan pages / book_images rows for this book_id.
    conn = storage.get_db()
    pages_count = conn.execute(
        "SELECT COUNT(*) AS c FROM pages WHERE book_id = ?", (book_id,)
    ).fetchone()["c"]
    images_count = conn.execute(
        "SELECT COUNT(*) AS c FROM book_images WHERE book_id = ?", (book_id,)
    ).fetchone()["c"]
    assert pages_count == 0
    assert images_count == 0


def test_delete_missing_book_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/books/999")
    assert resp.status_code == 404


def test_list_item_has_cover_flag(client: TestClient) -> None:
    seed_main(_FIXTURE, email=FIXTURE_EMAIL)

    body = client.get("/api/books").json()
    assert len(body) == 1
    # Pre-M12: seed never sets cover_path, so the flag is False.
    assert body[0]["has_cover"] is False
