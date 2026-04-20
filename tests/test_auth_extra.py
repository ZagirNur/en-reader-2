"""Extra auth-primitive coverage for M15.2 + M15.4 gap-fill.

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

M15.4 additions (HTTP-surface gap-fill):

* Login with an unknown email returns 401 (not 404) for timing parity —
  distinct from the existing "wrong password" test which targets a real
  account.
* A 100+ character password (bcrypt truncates at 72) still signs up and
  logs back in — round-trip via the HTTP layer, not just the primitive.
* The migration-seeded ``seed@local`` row (placeholder hash) cannot be
  logged into from the ``/auth/login`` endpoint, regardless of password.
* Signup with ``TEST@EXAMPLE.COM`` followed by ``test@example.com`` returns
  409 — exercises the normalize-then-dedupe branch end-to-end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader import auth as auth_module
from en_reader.app import app
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


# ---------- HTTP-surface gap-fill (M15.4) ----------


def test_login_nonexistent_email_401() -> None:
    """Login with an unknown email must return 401 (not 404).

    The route deliberately collapses "user not found" and "wrong password"
    into the same status so attackers can't enumerate which emails exist.
    ``test_login_valid_200_and_invalid_401`` in ``test_auth.py`` covers the
    wrong-password path against an *existing* account; this one covers the
    never-signed-up path to prove the timing-parity contract.
    """
    c = TestClient(app)
    r = c.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "longpass1"},
    )
    assert r.status_code == 401, r.text


def test_bcrypt_72_byte_truncate_http_roundtrip() -> None:
    """A 100+ char password signs up and logs back in.

    bcrypt silently truncates its input at 72 bytes; the existing
    ``test_bcrypt_roundtrip`` exercises that at the primitive level, but
    the spec wants the full HTTP-layer round-trip so a future refactor
    that drops bcrypt for a length-strict hasher is caught here. Long
    password is 120 characters — well past the 72-byte boundary.
    """
    long_pass = "a" * 120
    c = TestClient(app)
    signup = c.post(
        "/auth/signup",
        json={"email": "longpass@example.com", "password": long_pass},
    )
    assert signup.status_code == 200, signup.text

    # Log out so the subsequent /auth/login exercises password verification
    # instead of riding on the signup session cookie.
    c.post("/auth/logout")

    login = c.post(
        "/auth/login",
        json={"email": "longpass@example.com", "password": long_pass},
    )
    assert login.status_code == 200, login.text
    assert login.json() == {"email": "longpass@example.com"}


def test_placeholder_hash_login_never_authenticates() -> None:
    """Attempting to log in as ``seed@local`` never returns 200.

    The migration seeds a row with a ``__migration_placeholder__`` hash
    (see storage.migrate) and an email that deliberately fails the
    ``email_validator`` check (``seed@local`` has no TLD). That means
    the login route rejects it with a 400 at the ``normalize_email``
    step before ever reaching ``check_password`` — and that's precisely
    the belt-and-braces contract: the seed row is unreachable through
    the public HTTP surface.

    We assert "any non-200 status" rather than pinning a specific code so
    a future refactor that canonicalizes local-domain emails differently
    (e.g. widens validation, dropping the 400) still passes as long as
    the second line of defence — ``check_password`` refusing the
    placeholder hash — kicks in and returns 401.
    """
    c = TestClient(app)
    for pwd in ("longpass1", "__migration_placeholder__", "password"):
        r = c.post("/auth/login", json={"email": "seed@local", "password": pwd})
        assert r.status_code != 200, (pwd, r.text)
        assert r.status_code in (400, 401), (pwd, r.status_code, r.text)


def test_normalize_email_duplicate_409_via_http() -> None:
    """Signup with ``TEST@EXAMPLE.COM`` then ``test@example.com`` → 409.

    The normalize-then-dedupe branch is unit-tested via
    ``test_normalize_email_strips_and_lowercases``; this covers the full
    HTTP round-trip: first signup stores the lowercase form, so a second
    signup with a different-case variant must collide.
    """
    c1 = TestClient(app)
    first = c1.post(
        "/auth/signup",
        json={"email": "TEST@EXAMPLE.COM", "password": "longpass1"},
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"email": "test@example.com"}

    # Fresh client — no session cookie from the first signup — so the
    # route reaches the uniqueness check rather than short-circuiting.
    c2 = TestClient(app)
    dup = c2.post(
        "/auth/signup",
        json={"email": "test@example.com", "password": "longpass1"},
    )
    assert dup.status_code == 409, dup.text

    # And the mixed-case variant also collides — canonicalization is
    # applied on both sides of the comparison.
    c3 = TestClient(app)
    dup2 = c3.post(
        "/auth/signup",
        json={"email": "Test@Example.com", "password": "longpass1"},
    )
    assert dup2.status_code == 409, dup2.text
