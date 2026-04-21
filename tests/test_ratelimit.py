"""Tests for the generic in-memory rate limiter (M14.3).

Covers the three runtime wirings:

* ``/api/translate`` — 60 hits / user / 60 s; 61st → 429 with
  ``Retry-After``.
* ``/api/books/upload`` — 5 hits / user / 3600 s; 6th → 429 with
  ``Retry-After``.
* ``/auth/login`` — 10 hits / IP / 60 s (regression guard: M14.3
  refactor must not accidentally delete the M11.2 ``AuthRateLimit``).

Plus a unit-level window-reset test that advances a virtual clock past
the window and confirms the limiter re-opens. We fake time by
monkey-patching :func:`time.time` in ``en_reader.ratelimit`` rather than
sleeping — keeps the suite fast and deterministic.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from en_reader.ratelimit import RateLimit, rl_translate, rl_upload


def test_translate_rate_limit(client: TestClient) -> None:
    """``rl_translate.max`` translates pass, the next returns 429 + Retry-After."""
    # Patch the backend so we don't depend on Gemini / network; each call
    # deterministically returns the same stub. Using a unique lemma per
    # call avoids the dict-cache HIT path so every request exercises the
    # full handler body (and therefore the limiter check). M19.5 raised
    # the ceiling from 60 → 300/min; parameterising on ``rl_translate.max``
    # keeps the assertion honest if we ever re-tune it.
    with patch("en_reader.app.translate_one", Mock(return_value=("перевод", "llm"))):
        statuses: list[int] = []
        for i in range(rl_translate.max):
            r = client.post(
                "/api/translate",
                json={"unit_text": f"w{i}", "sentence": "ctx", "lemma": f"w{i}"},
            )
            statuses.append(r.status_code)
        assert statuses == [200] * rl_translate.max, statuses

        # The next request should be rejected with a 429 + Retry-After.
        r = client.post(
            "/api/translate",
            json={"unit_text": "over", "sentence": "ctx", "lemma": "over"},
        )
        assert r.status_code == 429, r.text
        assert r.headers.get("Retry-After") == str(rl_translate.window)


def test_upload_rate_limit(client: TestClient) -> None:
    """Five uploads pass, the 6th returns 429 with Retry-After header."""
    body = b"Hello world. A tiny book with a couple of sentences here.\n"
    for i in range(5):
        r = client.post(
            "/api/books/upload",
            files={"file": (f"book{i}.txt", body, "text/plain")},
        )
        assert r.status_code == 200, (i, r.text)

    r = client.post(
        "/api/books/upload",
        files={"file": ("over.txt", body, "text/plain")},
    )
    assert r.status_code == 429, r.text
    assert r.headers.get("Retry-After") == str(rl_upload.window)


def test_window_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    """After the window elapses, a full bucket re-opens for fresh hits.

    Driven off a virtual clock — patching ``en_reader.ratelimit.time.time``
    avoids the test having to sleep for 60 real seconds.
    """
    rl = RateLimit(max_hits=3, window_seconds=10)

    clock = {"now": 1000.0}
    monkeypatch.setattr("en_reader.ratelimit.time.time", lambda: clock["now"])

    assert rl.check("k") is True
    assert rl.check("k") is True
    assert rl.check("k") is True
    # Bucket full — next call fails.
    assert rl.check("k") is False

    # Advance past the window; every prior hit prunes and the bucket
    # re-opens to a full ``max_hits``.
    clock["now"] += 11.0
    assert rl.check("k") is True
    assert rl.check("k") is True
    assert rl.check("k") is True
    assert rl.check("k") is False


def test_auth_rate_limit_is_still_active() -> None:
    """Regression guard: 11th /auth/login from same IP still 429s.

    The M14.3 refactor added a new limiter module; if someone deletes
    ``AuthRateLimit`` in the cleanup, this test will catch it. Uses a
    raw client (no fixture signup) so the auth bucket starts empty.
    """
    c = TestClient(app)
    codes: list[int] = []
    for _ in range(11):
        r = c.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass9"},
        )
        codes.append(r.status_code)
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_translate_rate_limit_per_user_isolation() -> None:
    """Two users each get their own 60-hit window on /api/translate.

    ``rl_translate`` buckets by ``str(user.id)`` — a saturated user A
    must not drag user B into a 429. We burn A's 60 hits, confirm A's
    61st trips the limit, and confirm B's first hit still sails through.
    """
    client_a = TestClient(app)
    ra = client_a.post(
        "/auth/signup",
        json={"email": "rl-a@example.com", "password": "longpass1"},
    )
    assert ra.status_code == 200, ra.text

    client_b = TestClient(app)
    rb = client_b.post(
        "/auth/signup",
        json={"email": "rl-b@example.com", "password": "longpass1"},
    )
    assert rb.status_code == 200, rb.text

    with patch("en_reader.app.translate_one", Mock(return_value=("перевод", "llm"))):
        # A burns every allowed hit in their bucket.
        for i in range(rl_translate.max):
            r = client_a.post(
                "/api/translate",
                json={"unit_text": f"a{i}", "sentence": "ctx", "lemma": f"a{i}"},
            )
            assert r.status_code == 200, (i, r.text)

        # A's next hit must now 429 — their own bucket is full.
        over_a = client_a.post(
            "/api/translate",
            json={"unit_text": "aover", "sentence": "ctx", "lemma": "aover"},
        )
        assert over_a.status_code == 429, over_a.text

        # B's first hit must still 200 — B has an independent bucket.
        r_b = client_b.post(
            "/api/translate",
            json={"unit_text": "b1", "sentence": "ctx", "lemma": "b1"},
        )
        assert r_b.status_code == 200, r_b.text
