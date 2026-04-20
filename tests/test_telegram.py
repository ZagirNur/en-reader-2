"""Tests for M18.1 Telegram Mini-App auth.

Three layers, bottom up:

* ``verify_init_data`` — pure HMAC round-trip. We build an ``initData``
  string the way Telegram's JS would (sort, HMAC-SHA256 derived from the
  bot token), hand it back to the verifier, and assert it parses or
  raises appropriately.

* DAO — ``user_upsert_telegram`` creates exactly one row per
  ``telegram_id`` even across repeated calls, and the row carries the
  ``__tg_no_password__`` sentinel that ``check_password`` must refuse.

* HTTP — ``POST /auth/telegram`` with monkey-patched bot token sets the
  session and subsequent ``/api/*`` calls come back authed.

The bot token used in these tests is fake (``123:fake``) — the real one
lives in the server ``.env`` and never enters the test tree.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import urllib.parse
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from en_reader import auth, storage, tg

FAKE_TOKEN = "123456789:fake-bot-token"


def _build_init_data(
    token: str,
    *,
    user: dict,
    auth_date: int = 1700000000,
    extra: dict | None = None,
) -> str:
    """Construct a valid ``initData`` string the same way Telegram's JS does."""
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    if extra:
        fields.update(extra)
    pairs = [f"{k}={fields[k]}" for k in sorted(fields)]
    data_check_string = "\n".join(pairs)
    secret_key = hmac_mod.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac_mod.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = h
    return urllib.parse.urlencode(fields)


# ---------- HMAC verification ----------


def test_verify_init_data_happy_path() -> None:
    init = _build_init_data(FAKE_TOKEN, user={"id": 42, "first_name": "Вася", "username": "vasya"})
    parsed = tg.verify_init_data(init, FAKE_TOKEN)
    assert parsed.id == 42
    assert parsed.first_name == "Вася"
    assert parsed.username == "vasya"


def test_verify_init_data_wrong_hash_rejects() -> None:
    init = _build_init_data(FAKE_TOKEN, user={"id": 1})
    tampered = init.replace("hash=", "hash=0000000000")
    with pytest.raises(tg.InvalidInitDataError):
        tg.verify_init_data(tampered, FAKE_TOKEN)


def test_verify_init_data_wrong_token_rejects() -> None:
    init = _build_init_data(FAKE_TOKEN, user={"id": 1})
    with pytest.raises(tg.InvalidInitDataError):
        tg.verify_init_data(init, "987654321:different")


def test_verify_init_data_missing_user_rejects() -> None:
    # Build without 'user' field
    fields = {
        "auth_date": "1700000000",
        "query_id": "abc",
    }
    pairs = [f"{k}={fields[k]}" for k in sorted(fields)]
    data_check_string = "\n".join(pairs)
    secret_key = hmac_mod.new(b"WebAppData", FAKE_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac_mod.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    init = urllib.parse.urlencode(fields)
    with pytest.raises(tg.InvalidInitDataError):
        tg.verify_init_data(init, FAKE_TOKEN)


def test_verify_init_data_empty_inputs_reject() -> None:
    with pytest.raises(tg.InvalidInitDataError):
        tg.verify_init_data("", FAKE_TOKEN)
    with pytest.raises(tg.InvalidInitDataError):
        tg.verify_init_data("hash=deadbeef", "")


# ---------- DAO ----------


def test_upsert_telegram_creates_and_reuses_row() -> None:
    u1 = storage.user_upsert_telegram(9999, display_name="Test")
    u2 = storage.user_upsert_telegram(9999, display_name="Test")
    assert u1.id == u2.id
    assert u1.telegram_id == 9999
    assert u1.email == "tg-9999@telegram.local"
    # Sentinel must reject every password.
    assert auth.check_password("whatever", u1.password_hash) is False
    assert auth.check_password("", u1.password_hash) is False


def test_user_by_telegram_returns_none_when_absent() -> None:
    assert storage.user_by_telegram(55555) is None


def test_telegram_user_is_isolated_from_email_accounts() -> None:
    """A Telegram user and an email user share nothing but the users table."""
    tg_user = storage.user_upsert_telegram(42)
    # And the email/password signup path is independent.
    email_id = storage.user_create("user@example.com", auth.hash_password("pw12345678"))
    assert tg_user.id != email_id
    email_user = storage.user_by_id(email_id)
    assert email_user is not None
    assert email_user.telegram_id is None


# ---------- HTTP ----------


@pytest.fixture()
def anon_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An un-authed TestClient with TELEGRAM_BOT_TOKEN patched in."""
    from en_reader import app as app_module

    monkeypatch.setattr(app_module, "_TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    yield TestClient(app_module.app)


def test_auth_telegram_happy_path_sets_session(anon_client: TestClient) -> None:
    init = _build_init_data(FAKE_TOKEN, user={"id": 1234567, "first_name": "Alex"})
    resp = anon_client.post("/auth/telegram", json={"init_data": init})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["telegram_id"] == 1234567
    assert body["email"] == "tg-1234567@telegram.local"
    # session cookie must be usable on /api/*
    me = anon_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "tg-1234567@telegram.local"


def test_auth_telegram_wrong_hash_401(anon_client: TestClient) -> None:
    init = _build_init_data(FAKE_TOKEN, user={"id": 1})
    tampered = init.replace("hash=", "hash=ffff")
    resp = anon_client.post("/auth/telegram", json={"init_data": tampered})
    assert resp.status_code == 401


def test_auth_telegram_unconfigured_503() -> None:
    """Without TELEGRAM_BOT_TOKEN set, the endpoint 503s."""
    from en_reader import app as app_module

    original = app_module._TELEGRAM_BOT_TOKEN
    app_module._TELEGRAM_BOT_TOKEN = ""
    try:
        c = TestClient(app_module.app)
        resp = c.post("/auth/telegram", json={"init_data": "anything"})
        assert resp.status_code == 503
    finally:
        app_module._TELEGRAM_BOT_TOKEN = original


def test_tg_webhook_rejects_missing_secret_header(anon_client: TestClient) -> None:
    """Silent 200 (not confirming) when the secret header is missing."""
    resp = anon_client.post("/tg/webhook", json={"message": {"text": "/start"}})
    assert resp.status_code == 200
