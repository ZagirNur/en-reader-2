"""M16.4 — server-side checks for the dictionary screen.

We can't execute the SPA's JS in CI, so these tests pin down:

* ``app.js`` exposes the new ``renderDictionary`` view + state fields
  (``dictWords``, ``dictStats``, ``dictFilter``) and registers the
  ``/dict`` route.
* ``style.css`` carries the canonical selectors the screen relies on
  (``.dict-header``, ``.dict-stats``, ``.dict-filters``, ``.word-item``,
  ``.dict-empty``).
* The two dictionary API endpoints ``renderDictionary`` calls
  (``/api/dictionary/words`` + ``/api/dictionary/stats``) return the
  shape the UI expects, including the full per-word key set.
* A SPA deep-link to ``/dict`` is served by the catch-all (HTML stub +
  200).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from tests.conftest import FIXTURE_EMAIL


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None, "client fixture must have created the user"
    return user.id


# ---------- static-asset contract ----------


def test_app_js_has_dictionary_surface(client: TestClient) -> None:
    """app.js must expose the new dictionary screen hooks."""
    js = client.get("/static/app.js").text
    for name in (
        "renderDictionary",
        "dictWords",
        "dictStats",
        "dictFilter",
        '"/dict"',
    ):
        assert name in js, f"missing {name!r} in app.js"


def test_style_css_has_dictionary_selectors(client: TestClient) -> None:
    """style.css must carry the canonical selectors for the dict screen."""
    css = client.get("/static/style.css").text
    for sel in (".dict-header", ".dict-stats", ".dict-filters", ".word-item", ".dict-empty"):
        assert sel in css, f"missing {sel!r} in style.css"


# ---------- API shape the UI depends on ----------


def test_dictionary_words_shape(client: TestClient) -> None:
    """``/api/dictionary/words`` returns the full per-word key set."""
    uid = _fixture_user_id()
    # Seed three words; promote two of them so we cover multiple statuses.
    storage.dict_add(
        "ominous", "зловещий", user_id=uid, example="She whispered an ominous warning."
    )
    storage.dict_add("whisper", "шёпот", user_id=uid, example="A soft whisper.")
    storage.dict_add("gloom", "мрак", user_id=uid)

    # whisper: two correct → review lane.
    storage.record_training_result("whisper", correct=True, user_id=uid)
    storage.record_training_result("whisper", correct=True, user_id=uid)
    # ominous: one correct → learning.
    storage.record_training_result("ominous", correct=True, user_id=uid)
    # gloom stays ``new``.

    resp = client.get("/api/dictionary/words?status=all")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3

    expected_keys = {
        "lemma",
        "translation",
        "status",
        "example",
        "source_book",
        "first_seen_at",
        "last_reviewed_at",
        "days_since_review",
        "ipa",
        "pos",
    }
    for entry in body:
        assert expected_keys.issubset(
            entry.keys()
        ), f"missing keys in {entry!r}: {expected_keys - entry.keys()}"
        # IPA / POS are placeholders until M17.
        assert entry["ipa"] is None
        assert entry["pos"] is None

    statuses = {e["lemma"]: e["status"] for e in body}
    assert statuses == {
        "ominous": "learning",
        "whisper": "review",
        "gloom": "new",
    }


def test_dictionary_stats_shape(client: TestClient) -> None:
    """``/api/dictionary/stats`` returns the keys the stats card needs."""
    uid = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=uid)
    storage.dict_add("whisper", "шёпот", user_id=uid)
    storage.record_training_result("whisper", correct=True, user_id=uid)

    resp = client.get("/api/dictionary/stats")
    assert resp.status_code == 200
    body = resp.json()

    for key in ("total", "review_today", "active", "mastered", "new", "learning", "review"):
        assert key in body, f"missing {key!r} in /api/dictionary/stats"

    # Sanity check: the two seeded words land in the ``new`` / ``learning``
    # lanes which both roll up to ``active``.
    assert body["total"] == 2
    assert body["active"] == body["new"] + body["learning"]


# ---------- SPA route ----------


def test_dict_route_served_by_spa(client: TestClient) -> None:
    """``/dict`` is a SPA-only path — the catch-all must serve the shell."""
    resp = client.get("/dict")
    assert resp.status_code == 200
    assert 'id="root"' in resp.text
