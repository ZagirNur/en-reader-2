"""M15.5 — integration cross-book: a word translated in book A auto-highlights in book B.

The user dictionary is per-account, not per-book: once a lemma is
translated anywhere, every subsequent ``/content`` request for any of
the user's books should surface the lemma's unit id inside
``auto_unit_ids`` and include the translation in ``user_dict``. This
test pins that contract by walking the full HTTP chain — upload A,
translate, upload B, fetch B's content — with the LLM mocked.

We use the phrasal verb "pick up" as the shared lemma because
``auto_unit_ids`` is derived from ``page.units``, and those units only
cover MWEs / phrasal verbs — single-word tokens don't make it into
that list.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from en_reader.app import app


def _upload(client: TestClient, text: str, filename: str = "book.txt") -> int:
    """POST a text file through ``/api/books/upload`` and return its book id."""
    resp = client.post(
        "/api/books/upload",
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["book_id"])


def test_translation_in_book_a_auto_highlights_in_book_b() -> None:
    client = TestClient(app)

    # Signup first — required for every /api/* call below.
    resp = client.post(
        "/auth/signup",
        json={"email": "cross@example.com", "password": "12345678"},
    )
    assert resp.status_code == 200, resp.text

    mock = Mock(return_value=("поднять", "llm"))
    with patch("en_reader.app.translate_one", mock):
        # Upload book A and translate "pick up" once.
        book_a_id = _upload(
            client,
            "Text A — she picked up the book quickly.",
            filename="book_a.txt",
        )
        r = client.post(
            "/api/translate",
            json={
                "unit_text": "picked up",
                "sentence": "Text A — she picked up the book quickly.",
                "lemma": "pick up",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["ru"] == "поднять"
        assert mock.call_count == 1

        # Upload book B — never touched by translate, but shares the user dict.
        book_b_id = _upload(
            client,
            "Book B: he picked up the phone.",
            filename="book_b.txt",
        )
        assert book_b_id != book_a_id

        # Book B's content must expose the cross-book auto-highlight.
        resp = client.get(f"/api/books/{book_b_id}/content?offset=0&limit=1")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["user_dict"].get("pick up") == "поднять"

        page = body["pages"][0]
        target_unit = next(
            (u for u in page["units"] if (u.get("lemma") or "").lower() == "pick up"),
            None,
        )
        assert target_unit is not None, f"no 'pick up' unit in book B units={page['units']}"
        assert target_unit["id"] in page["auto_unit_ids"]
