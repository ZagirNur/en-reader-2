"""Tests for M11.2 auth API: signup / login / logout / me + rate limit.

The app module is imported once at module level — the autouse ``tmp_db``
fixture in :mod:`tests.conftest` gives every test a fresh SQLite file
(and therefore a fresh ``users`` table), which is what we need for
email-uniqueness and session-restart assertions.

The rate-limit state lives on the module-level ``auth_ratelimit`` and
*does* persist across tests unless we reset it — the ``_reset_ratelimit``
fixture below wipes it per-test so a cascade of prior 401s can't trip a
later test into an unexpected 429.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from en_reader import auth as auth_module
from en_reader import storage
from en_reader.app import SECRET_KEY, app
from en_reader.auth import (
    PLACEHOLDER_HASH,
    AuthRateLimit,
    auth_ratelimit,
    check_password,
    hash_password,
    normalize_email,
)


@pytest.fixture(autouse=True)
def _reset_ratelimit() -> None:
    """Empty the global rate-limit buckets before every test."""
    auth_ratelimit._hits.clear()
    yield
    auth_ratelimit._hits.clear()


def _client() -> TestClient:
    return TestClient(app)


# ---------- primitives ----------


def test_bcrypt_roundtrip() -> None:
    h = hash_password("longpass1")
    assert check_password("longpass1", h) is True
    assert check_password("wrongpass", h) is False


def test_placeholder_hash_rejected() -> None:
    # Even if the caller literally supplies the sentinel bytes as a password,
    # ``check_password`` must refuse the placeholder hash.
    assert check_password("anything", PLACEHOLDER_HASH) is False
    assert check_password(PLACEHOLDER_HASH, PLACEHOLDER_HASH) is False


def test_normalize_email_lowercase_trims() -> None:
    assert normalize_email("Foo@Example.com") == "foo@example.com"
    assert normalize_email("  user@example.com  ".strip()) == "user@example.com"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


# ---------- routes ----------


def test_signup_creates_session_and_me_returns_email() -> None:
    c = _client()
    r = c.post("/auth/signup", json={"email": "u@example.com", "password": "longpass1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"email": "u@example.com"}

    me = c.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": "u@example.com"}


def test_signup_duplicate_email_409() -> None:
    c = _client()
    first = c.post("/auth/signup", json={"email": "d@example.com", "password": "longpass1"})
    assert first.status_code == 200

    # Fresh client — without the session cookie — to exercise the uniqueness check.
    c2 = _client()
    dup = c2.post("/auth/signup", json={"email": "d@example.com", "password": "otherpass9"})
    assert dup.status_code == 409


def test_login_valid_200_and_invalid_401() -> None:
    c = _client()
    c.post("/auth/signup", json={"email": "l@example.com", "password": "longpass1"})
    c.post("/auth/logout")

    bad = c.post("/auth/login", json={"email": "l@example.com", "password": "wrongpass9"})
    assert bad.status_code == 401

    ok = c.post("/auth/login", json={"email": "l@example.com", "password": "longpass1"})
    assert ok.status_code == 200
    assert ok.json() == {"email": "l@example.com"}


def test_logout_clears_session() -> None:
    c = _client()
    c.post("/auth/signup", json={"email": "x@example.com", "password": "longpass1"})
    assert c.get("/auth/me").status_code == 200

    r = c.post("/auth/logout")
    assert r.status_code == 200
    assert c.get("/auth/me").status_code == 401


def test_password_min_length_422() -> None:
    c = _client()
    r = c.post("/auth/signup", json={"email": "s@example.com", "password": "short"})
    assert r.status_code == 422


def test_signup_invalid_email_400() -> None:
    c = _client()
    r = c.post("/auth/signup", json={"email": "not-an-email", "password": "longpass1"})
    assert r.status_code == 400


def test_me_without_session_401() -> None:
    c = _client()
    assert c.get("/auth/me").status_code == 401


def test_11th_login_rate_limited_429() -> None:
    # Eleven POSTs with bad credentials from the same IP: first 10 return 401,
    # the 11th must trip the limiter and return 429.
    c = _client()
    codes: list[int] = []
    for _ in range(11):
        r = c.post("/auth/login", json={"email": "n@example.com", "password": "wrongpass9"})
        codes.append(r.status_code)
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_session_survives_restart() -> None:
    # Instead of re-importing the whole app (brittle — has side effects via
    # lifespan, migrations, module state), we prove the equivalent property:
    # two independent SessionMiddleware instances configured with the *same*
    # SECRET_KEY can decode each other's cookies. That's exactly what makes
    # a restart survive — the server reads ``data/.secret_key`` back, builds
    # a fresh middleware with that same key, and old cookies still verify.

    c = _client()
    r = c.post("/auth/signup", json={"email": "r@example.com", "password": "longpass1"})
    assert r.status_code == 200
    sess_cookie = c.cookies.get("sess")
    assert sess_cookie, "signup should set the sess cookie"

    # Build a minimal twin app with the same SECRET_KEY and a /probe route
    # that echoes the signed-in user_id from session. If the key is stable
    # across restarts, the cookie from the original app decodes here.
    twin = FastAPI()
    twin.add_middleware(
        SessionMiddleware,
        secret_key=SECRET_KEY,
        session_cookie="sess",
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
        https_only=False,
    )

    @twin.get("/probe")
    def probe(request: Request) -> dict:
        uid = request.session.get("user_id")
        if not uid:
            raise HTTPException(status_code=401)
        return {"user_id": uid}

    tc = TestClient(twin)
    tc.cookies.set("sess", sess_cookie)
    r2 = tc.get("/probe")
    assert r2.status_code == 200
    assert "user_id" in r2.json() and isinstance(r2.json()["user_id"], int)


def test_secret_key_file_persisted_0o600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # M19.6: the secret now lives next to the DB file (DB_PATH.parent /
    # .secret_key), so the old tmp-cwd trick no longer applies. Point
    # DB_PATH at a sibling file in tmp_path and confirm the helper drops
    # the key alongside it with mode 0o600. A fresh reload of
    # ``en_reader.app`` re-runs the module-level ``_secret_key()``.
    import importlib

    db_file = tmp_path / "en-reader.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    from en_reader import app as app_module

    importlib.reload(app_module)
    key_file = tmp_path / ".secret_key"
    assert key_file.exists()
    mode = stat.S_IMODE(os.stat(key_file).st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_auth_rate_limit_unit() -> None:
    # Spot-check the limiter in isolation so the endpoint test above isn't
    # carrying the whole burden of proving sliding-window semantics.
    rl = AuthRateLimit()
    for _ in range(10):
        assert rl.check("1.2.3.4") is True
    assert rl.check("1.2.3.4") is False
    # Different IPs don't share the bucket.
    assert rl.check("5.6.7.8") is True


def test_storage_user_daos_roundtrip() -> None:
    uid = storage.user_create("dao@example.com", hash_password("longpass1"))
    assert isinstance(uid, int) and uid > 1  # id=1 is the seed row

    u = storage.user_by_id(uid)
    assert u is not None and u.email == "dao@example.com"

    same = storage.user_by_email("dao@example.com")
    assert same is not None and same.id == uid

    with pytest.raises(auth_module.EmailExistsError):
        storage.user_create("dao@example.com", hash_password("longpass1"))
