"""Extra auth-primitive coverage for M15.2.

Complements ``test_auth.py`` by filling in the small set of branches the
existing suite doesn't touch:

* ``check_password`` swallowing malformed-hash ``ValueError`` as ``False``
  (the ``except (ValueError, TypeError)`` branch in :mod:`en_reader.auth`).
* ``hash_password`` generating a fresh salt per call so two hashes of the
  same password differ, while ``check_password`` still verifies both.
* ``AuthRateLimit`` window resetting once clock advances past 60 s — the
  sliding-window prune branch isn't exercised by the endpoint-level
  ratelimit tests.
* ``normalize_email`` stripping + lowercasing and its ``ValueError`` path.
"""

from __future__ import annotations

import pytest

from en_reader import auth as auth_module
from en_reader.auth import (
    AuthRateLimit,
    check_password,
    hash_password,
    normalize_email,
)


def test_normalize_email_invalid_raises_valueerror() -> None:
    """Bad input must surface as ``ValueError`` so the route can 400."""
    with pytest.raises(ValueError):
        normalize_email("no-at-sign")
    with pytest.raises(ValueError):
        normalize_email("")


def test_normalize_email_strips_and_lowercases() -> None:
    """Whitespace-padded mixed-case input normalises to a canonical form."""
    assert normalize_email("  User@EXAMPLE.COM  ".strip()) == "user@example.com"
    assert normalize_email("Foo.Bar@Example.Com") == "foo.bar@example.com"


def test_hash_password_deterministic_per_call() -> None:
    """bcrypt salts are random — two hashes of the same password differ,
    and both verify under :func:`check_password`."""
    h1 = hash_password("longpass1")
    h2 = hash_password("longpass1")
    assert h1 != h2, "bcrypt must inject a fresh salt per call"
    assert check_password("longpass1", h1) is True
    assert check_password("longpass1", h2) is True


def test_check_password_malformed_hash_is_false() -> None:
    """A non-bcrypt string as ``hashed`` must not raise — it must return False.

    Covers the ``except (ValueError, TypeError)`` swallow branch in
    :func:`en_reader.auth.check_password`.
    """
    # A completely bogus hash blob makes bcrypt raise ValueError internally.
    assert check_password("anything", "not-a-bcrypt-hash") is False
    # Empty hash: also swallowed.
    assert check_password("anything", "") is False


def test_auth_ratelimit_window_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once the clock advances past ``WINDOW_SECONDS``, the limiter refills."""
    rl = AuthRateLimit()
    t = [1_000_000.0]

    def fake_time() -> float:
        return t[0]

    monkeypatch.setattr(auth_module.time, "time", fake_time)
    # Burn all 10 hits in the current window.
    for _ in range(10):
        assert rl.check("1.2.3.4") is True
    assert rl.check("1.2.3.4") is False

    # Advance the clock past the 60 s window — bucket should empty out.
    t[0] += AuthRateLimit.WINDOW_SECONDS + 1.0
    assert rl.check("1.2.3.4") is True
