"""Tests for M10.5 current-book pointer + redirect-flow APIs.

Covers:
* ``POST /api/me/current-book`` set + ``GET`` round-trip.
* Clearing via ``{"book_id": null}`` and via an empty body (Pydantic default).
* Rejection of unknown book ids (404).
* Cascade on ``DELETE /api/books/{id}``: deleting the current book nulls
  the pointer inside the same transaction as the row deletion.

Relies on the autouse ``tmp_db`` fixture from ``conftest.py`` so every
test starts with a fresh SQLite file and an empty ``meta`` table.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_post_and_get() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)

    resp = client.post("/api/me/current-book", json={"book_id": book_id})
    assert resp.status_code == 204
    assert resp.content == b""

    body = client.get("/api/me/current-book").json()
    assert body == {"book_id": book_id}


def test_post_null() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    # First set it, then clear.
    client.post("/api/me/current-book", json={"book_id": book_id})
    resp = client.post("/api/me/current-book", json={"book_id": None})
    assert resp.status_code == 204

    body = client.get("/api/me/current-book").json()
    assert body == {"book_id": None}


def test_post_unknown_book_404() -> None:
    client = TestClient(app)
    resp = client.post("/api/me/current-book", json={"book_id": 999})
    assert resp.status_code == 404


def test_delete_current_book_clears_it() -> None:
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    client.post("/api/me/current-book", json={"book_id": book_id})
    assert client.get("/api/me/current-book").json() == {"book_id": book_id}

    resp = client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 204

    body = client.get("/api/me/current-book").json()
    assert body == {"book_id": None}
    # Sanity: the storage DAO also sees the cleared pointer.
    assert storage.current_book_get() is None


def test_post_missing_body_field_defaults_null() -> None:
    # The Pydantic model defaults `book_id` to None, so an empty body is a
    # valid way to clear the pointer. Pin this behaviour so we don't
    # accidentally tighten the contract later.
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    client.post("/api/me/current-book", json={"book_id": book_id})

    resp = client.post("/api/me/current-book", json={})
    assert resp.status_code == 204
    assert client.get("/api/me/current-book").json() == {"book_id": None}


def test_get_default_is_null() -> None:
    # Fresh DB (autouse fixture) — the pointer must start as null even
    # before anything has written to `meta`.
    client = TestClient(app)
    body = client.get("/api/me/current-book").json()
    assert body == {"book_id": None}
