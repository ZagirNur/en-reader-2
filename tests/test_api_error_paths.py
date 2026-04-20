"""Error-path coverage for the auth'd API routes (M15.2).

These tests target the 4xx/5xx branches of ``app.py`` that existing
suites don't already hit:

* ``POST /api/books/upload`` — storage-layer crash turns into a 500 and
  leaves no partial book row in the DB.
* ``POST /api/translate`` — missing ``lemma`` field is a 422 (Pydantic).
* ``GET /api/books/{id}/content`` — non-integer path param is a 422.
* ``DELETE /api/dictionary/{lemma}`` — missing lemma is idempotent 204.
* ``GET /auth/me`` / ``get_current_user`` — a session that references a
  deleted user row returns 401 and clears the cookie.
* ``GET /api/books/{id}/cover`` — the book exists but ``cover_path`` is
  NULL → 404 (covers the ``not meta.cover_path`` branch).
* ``POST /api/me/current-book`` — pointing at a foreign / unknown book
  is a 404.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app
from tests.conftest import FIXTURE_EMAIL


def test_upload_storage_failure_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A crash in ``storage.book_save`` surfaces as a generic 500.

    The route catches ``Exception`` and re-raises as ``HTTPException(500)``
    with a sanitized message; no partial books row must leak into
    ``GET /api/books`` afterwards.
    """
    before = client.get("/api/books").json()

    def _boom(parsed, *, user_id):  # noqa: ARG001
        raise RuntimeError("boom")

    # Patch the symbol as the route sees it.
    monkeypatch.setattr("en_reader.app.storage.book_save", _boom)

    resp = client.post(
        "/api/books/upload",
        files={
            "file": (
                "oops.txt",
                b"Some text. Another sentence here.",
                "text/plain",
            )
        },
    )
    assert resp.status_code == 500
    assert "boom" not in resp.json().get("detail", "")

    after = client.get("/api/books").json()
    assert before == after, "failed book_save must not leak a row into the library"


def test_translate_rejects_invalid_body_422(client: TestClient) -> None:
    """POST /api/translate without ``lemma`` fails Pydantic validation."""
    resp = client.post(
        "/api/translate",
        json={"unit_text": "ominous", "sentence": "She whispered."},
    )
    assert resp.status_code == 422


def test_content_invalid_book_id_type(client: TestClient) -> None:
    """Non-integer ``book_id`` path param → FastAPI path validation 422."""
    resp = client.get("/api/books/notanumber/content")
    assert resp.status_code == 422


def test_delete_dictionary_idempotent_204(client: TestClient) -> None:
    """DELETE on a lemma that doesn't exist still returns 204."""
    resp = client.delete("/api/dictionary/never-added")
    assert resp.status_code == 204
    assert resp.content == b""


def test_me_with_deleted_user_returns_401(client: TestClient) -> None:
    """Session pointing at a vanished users row → 401 + session cleared.

    Covers the ``user is None`` branch in both ``get_current_user`` and
    ``/auth/me``. We delete the fixture user directly from storage while
    the client still holds a valid session cookie.
    """
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    conn = storage.get_db()
    # ON DELETE CASCADE on books/dictionary/progress handles the rest.
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user.id,))

    # /auth/me: exercises the direct session-based check (lines 676-680).
    resp_me = client.get("/auth/me")
    assert resp_me.status_code == 401

    # /api/books: exercises get_current_user's deleted-user branch (354-355).
    # The previous /auth/me call already cleared the cookie, so re-seed a
    # fresh session pointing at the now-stale user id to drive this path.
    # Easiest way: use a raw TestClient with a hand-crafted session cookie
    # would require re-signing — instead, re-sign up under a fresh email
    # and then delete *that* user mid-session.
    c2 = TestClient(app)
    resp = c2.post(
        "/auth/signup",
        json={"email": "ephemeral@example.com", "password": "longpass1"},
    )
    assert resp.status_code == 200
    ephemeral = storage.user_by_email("ephemeral@example.com")
    assert ephemeral is not None
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (ephemeral.id,))
    resp_books = c2.get("/api/books")
    assert resp_books.status_code == 401


def test_cover_endpoint_404_when_no_cover(client: TestClient, seed_book: int) -> None:
    """A book with ``cover_path IS NULL`` → 404 on the cover route.

    The ``seed_book`` fixture inserts a parsed book with ``cover=None``,
    so no cover file is ever written and the route hits the
    ``if not meta.cover_path`` branch (lines 505-506 in app.py).
    """
    resp = client.get(f"/api/books/{seed_book}/cover")
    assert resp.status_code == 404


def test_current_book_set_unknown_id_404(client: TestClient) -> None:
    """POST /api/me/current-book pointing at a phantom id → 404."""
    resp = client.post("/api/me/current-book", json={"book_id": 99999})
    assert resp.status_code == 404


def test_current_book_set_and_clear_roundtrip(client: TestClient, seed_book: int) -> None:
    """Happy path for POST then clear via ``{"book_id": null}``."""
    resp = client.post("/api/me/current-book", json={"book_id": seed_book})
    assert resp.status_code == 204

    got = client.get("/api/me/current-book").json()
    assert got == {"book_id": seed_book}

    cleared = client.post("/api/me/current-book", json={"book_id": None})
    assert cleared.status_code == 204
    assert client.get("/api/me/current-book").json() == {"book_id": None}


def test_login_invalid_email_400(client: TestClient) -> None:
    """login with an unparseable email hits normalize_email's ValueError → 400.

    Covers lines 652-653 in app.py (the login ValueError branch). The
    fixture client has already signed up, so we drop its cookies and POST
    with garbage to hit the route cleanly.
    """
    client.cookies.clear()
    resp = client.post(
        "/auth/login",
        json={"email": "not-an-email", "password": "longpass1"},
    )
    assert resp.status_code == 400
