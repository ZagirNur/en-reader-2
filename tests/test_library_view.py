"""Server-side checks for the M9.2 library screen.

We can't execute the SPA's JS in CI, so these tests focus on the API
contract the library view depends on (``GET /api/books`` + deletion
consistency) plus a smoke check that the static assets contain the key
class names / function names the spec mandates. Every test gets a fresh
SQLite via the autouse ``tmp_db`` fixture.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_api_books_empty() -> None:
    """With a pristine DB, ``GET /api/books`` must return an empty list."""
    client = TestClient(app)
    resp = client.get("/api/books")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_books_after_seed() -> None:
    """After two seeds, list must be newest-first and carry the expected shape."""
    id1 = seed_main(_FIXTURE)
    id2 = seed_main(_FIXTURE)
    assert id1 != id2

    client = TestClient(app)
    body = client.get("/api/books").json()
    assert [b["id"] for b in body] == [id2, id1]
    assert set(body[0].keys()) == {"id", "title", "author", "total_pages", "has_cover"}


def test_delete_book_via_api() -> None:
    """After ``DELETE``, the subsequent listing must omit the deleted id."""
    id1 = seed_main(_FIXTURE)
    id2 = seed_main(_FIXTURE)

    client = TestClient(app)
    resp = client.delete(f"/api/books/{id1}")
    assert resp.status_code == 204

    remaining = client.get("/api/books").json()
    ids = [b["id"] for b in remaining]
    assert id1 not in ids
    assert ids == [id2]


def test_static_library_assets() -> None:
    """Spot-check that the shipped JS/CSS/HTML include the M9.2 markers."""
    client = TestClient(app)

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "renderLibrary" in js.text

    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert ".library" in css.text
    assert ".add-card" in css.text

    html = client.get("/static/index.html")
    assert html.status_code == 200
    assert "Библиотека" in html.text
