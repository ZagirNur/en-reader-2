"""M15.5 — integration happy path: signup → upload → content → translate → cache → dictionary.

Exercises the full HTTP chain a first-time user walks through: create an
account, upload a tiny TXT, pull the content slice, click a word, hit
the LLM mock once, hit cache on the repeat, and confirm the translation
landed in ``/api/dictionary``. The LLM symbol is monkeypatched at
``en_reader.app.translate_one`` — same spot :mod:`tests.test_translate_cache`
patches — so no network traffic leaves the TestClient.

We pick a phrasal lemma ("pick up") as the translate target because the
/content payload's ``units`` list only carries MWEs and phrasal verbs —
single-word tokens live under ``tokens``. That makes phrasals the
natural fit for a "locate the unit, translate it, observe it in the
dictionary" scenario.

Uses a bare ``TestClient(app)`` rather than the authed ``client`` fixture
because ``/auth/signup`` is itself part of the scenario under test.
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


def test_signup_upload_translate_cache_dictionary() -> None:
    client = TestClient(app)

    # 1. Signup — creates the user + session cookie.
    resp = client.post(
        "/auth/signup",
        json={"email": "happy@example.com", "password": "12345678"},
    )
    assert resp.status_code == 200, resp.text

    # 2. Upload a small txt containing a phrasal verb the NLP pipeline
    # recognises as a Unit (single-word tokens don't appear in
    # ``page.units``; only MWEs / phrasals do).
    sentence = "She picked up the book from the floor."
    book_id = _upload(client, sentence)

    # 3. Grab the first page and locate the "pick up" unit.
    resp = client.get(f"/api/books/{book_id}/content?offset=0&limit=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_pages"] >= 1
    page = body["pages"][0]
    target_unit = next(
        (u for u in page["units"] if (u.get("lemma") or "").lower() == "pick up"),
        None,
    )
    assert target_unit is not None, f"no 'pick up' unit in page units={page['units']}"

    # 4. Translate via mocked LLM — miss path persists into the user dict.
    mock = Mock(return_value=("поднять", "llm"))
    with patch("en_reader.app.translate_one", mock):
        payload = {
            "unit_text": "picked up",
            "sentence": sentence,
            "lemma": "pick up",
        }
        r1 = client.post("/api/translate", json=payload)
        assert r1.status_code == 200, r1.text
        assert r1.json()["ru"] == "поднять"
        assert mock.call_count == 1

        # 5. Second POST still invokes ``translate_one`` (M19.1 moved the
        # cache from ``user_dictionary`` into the prompt-hash ``llm_cache``
        # inside ``translate_one`` itself). The user observes the same
        # ``ru`` but the app-level entry point is no longer short-circuited.
        r2 = client.post("/api/translate", json=payload)
        assert r2.status_code == 200, r2.text
        assert r2.json()["ru"] == "поднять"
        assert mock.call_count == 2

    # 6. Dictionary endpoint reflects the translation.
    resp = client.get("/api/dictionary")
    assert resp.status_code == 200, resp.text
    dictionary = resp.json()
    assert dictionary.get("pick up") == "поднять"
