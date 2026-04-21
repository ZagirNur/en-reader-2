"""Per-user isolation regression tests (M11.3 spec §9).

Two independent ``TestClient`` instances — each with its own signed-up
session cookie — must not see any of each other's data. We cover all
five isolation-critical surfaces:

* ``GET /api/books`` returns only the caller's books.
* ``GET /api/books/{id}/content`` for someone else's id → 404.
* ``DELETE /api/books/{id}`` for someone else's id → 404.
* ``POST /api/translate`` populates only the caller's dictionary.
* ``POST /api/me/current-book`` / ``GET /api/me/current-book`` are
  independent across users.

The ``scripts.seed.main`` helper now accepts an ``email=`` kwarg (M11.3)
so each user's book is attached to the right ``user_id`` without any
handler-level workarounds.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def _signup(email: str) -> TestClient:
    """Return a :class:`TestClient` with a fresh session for ``email``."""
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": email, "password": "testpass123"})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def two_users_with_books() -> tuple[TestClient, int, TestClient, int]:
    """Spin up users A and B, each with one seeded book.

    Returned as ``(client_a, book_id_a, client_b, book_id_b)`` so tests
    can address either side without having to re-derive book ids.
    """
    client_a = _signup("a@example.com")
    book_a = seed_main(_FIXTURE, email="a@example.com")
    client_b = _signup("b@example.com")
    book_b = seed_main(_FIXTURE, email="b@example.com")
    assert book_a != book_b
    return client_a, book_a, client_b, book_b


# ---------- books list ----------


def test_books_list_only_shows_own(
    two_users_with_books: tuple[TestClient, int, TestClient, int],
) -> None:
    client_a, book_a, client_b, book_b = two_users_with_books

    body_a = client_a.get("/api/books").json()
    assert [b["id"] for b in body_a] == [book_a]

    body_b = client_b.get("/api/books").json()
    assert [b["id"] for b in body_b] == [book_b]


# ---------- content endpoint ----------


def test_content_of_other_users_book_404(
    two_users_with_books: tuple[TestClient, int, TestClient, int],
) -> None:
    client_a, _book_a, _client_b, book_b = two_users_with_books
    # A asking for B's book id → indistinguishable from a missing book.
    resp = client_a.get(f"/api/books/{book_b}/content")
    assert resp.status_code == 404


# ---------- delete endpoint ----------


def test_delete_other_users_book_404(
    two_users_with_books: tuple[TestClient, int, TestClient, int],
) -> None:
    client_a, _book_a, client_b, book_b = two_users_with_books
    resp = client_a.delete(f"/api/books/{book_b}")
    assert resp.status_code == 404
    # And B's book must still be listable by B — the 404 must not have
    # taken the row out from under the real owner.
    remaining = client_b.get("/api/books").json()
    assert [b["id"] for b in remaining] == [book_b]


# ---------- dictionary isolation ----------


def test_translate_populates_only_callers_dict() -> None:
    client_a = _signup("dict-a@example.com")
    client_b = _signup("dict-b@example.com")

    with patch("en_reader.app.translate_one", return_value=("зловещий", "llm")):
        resp = client_a.post(
            "/api/translate",
            json={
                "unit_text": "ominous",
                "sentence": "She whispered an ominous warning.",
                "lemma": "ominous",
            },
        )
        assert resp.status_code == 200

    assert client_a.get("/api/dictionary").json() == {"ominous": "зловещий"}
    assert client_b.get("/api/dictionary").json() == {}


# ---------- current-book isolation ----------


def test_current_book_does_not_bleed(
    two_users_with_books: tuple[TestClient, int, TestClient, int],
) -> None:
    client_a, book_a, client_b, _book_b = two_users_with_books

    # A parks on their book; B must still see a null pointer.
    r = client_a.post("/api/me/current-book", json={"book_id": book_a})
    assert r.status_code == 204

    assert client_a.get("/api/me/current-book").json() == {"book_id": book_a}
    assert client_b.get("/api/me/current-book").json() == {"book_id": None}


def test_current_book_rejects_other_users_book(
    two_users_with_books: tuple[TestClient, int, TestClient, int],
) -> None:
    """Pointing the current-book pointer at someone else's id → 404."""
    client_a, _book_a, _client_b, book_b = two_users_with_books
    resp = client_a.post("/api/me/current-book", json={"book_id": book_b})
    assert resp.status_code == 404
    # And A's pointer must not have moved.
    assert client_a.get("/api/me/current-book").json() == {"book_id": None}
