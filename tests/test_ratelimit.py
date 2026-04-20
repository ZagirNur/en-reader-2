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
    """60 translates pass, the 61st returns 429 with Retry-After header."""
    # Patch the backend so we don't depend on Gemini / network; each call
    # deterministically returns the same stub. Using a unique lemma per
    # call avoids the dict-cache HIT path so every request exercises the
    # full handler body (and therefore the limiter check).
    with patch("en_reader.app.translate_one", Mock(return_value="перевод")):
        statuses: list[int] = []
        for i in range(60):
            r = client.post(
                "/api/translate",
                json={"unit_text": f"w{i}", "sentence": "ctx", "lemma": f"w{i}"},
            )
            statuses.append(r.status_code)
        assert statuses == [200] * 60, statuses

        # The 61st request should be rejected with a 429 + Retry-After.
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
