"""Tests for M18.4 — the email-account → Telegram link flow.

We cover each branch of ``_handle_link_start`` and ``_handle_link_callback``
without talking to ``api.telegram.org`` (monkeypatch ``tg.send_plain``,
``tg.send_link_choice``, ``tg.answer_callback``, ``tg.edit_message``,
``tg._call``). The test token ``FAKE_TOKEN`` is bound via the same
``anon_client`` pattern ``test_telegram.py`` uses.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from en_reader import auth, storage, tg
from en_reader import app as app_module

FAKE_TOKEN = "123456789:fake-bot-token"
WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture()
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient with the Telegram env vars patched + outbound bot calls stubbed.

    ``tg._call`` is the single exit point to api.telegram.org; we replace
    it with a no-op that records what was called so assertions can
    inspect the sequence of outbound requests.
    """
    monkeypatch.setattr(app_module, "_TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(app_module, "_TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    app_module._BOT_USERNAME_CACHE[FAKE_TOKEN] = "test_en_reader_bot"

    calls: list[tuple[str, dict]] = []

    def fake_call(bot_token: str, method: str, payload: dict) -> dict:
        calls.append((method, payload))
        # Mimic Telegram's send* response: include message_id so the
        # conflict-keyboard branch can store it.
        if method == "sendMessage":
            return {"message_id": 777, "chat": {"id": payload.get("chat_id")}}
        if method == "getMe":
            return {"username": "test_en_reader_bot"}
        return {}

    monkeypatch.setattr(tg, "_call", fake_call)

    c = TestClient(app_module.app)
    c._sent = calls  # type: ignore[attr-defined]
    yield c
    app_module._BOT_USERNAME_CACHE.pop(FAKE_TOKEN, None)


def _signup(client: TestClient, email: str) -> int:
    """Sign up an email user and return their id."""
    r = client.post("/auth/signup", json={"email": email, "password": "passw0rd1"})
    assert r.status_code == 200, r.text
    me = client.get("/auth/me").json()
    return storage.user_by_email(me["email"]).id  # type: ignore[union-attr]


def _webhook(client: TestClient, update: dict) -> None:
    r = client.post(
        "/tg/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
    )
    assert r.status_code == 200


# ---------- /auth/link/telegram/init ----------


def test_init_requires_auth(wired: TestClient) -> None:
    r = wired.post("/auth/link/telegram/init")
    assert r.status_code == 401


def test_init_returns_deep_link(wired: TestClient) -> None:
    _signup(wired, "link-a@example.com")
    r = wired.post("/auth/link/telegram/init")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deep_link"].startswith(
        "https://t.me/test_en_reader_bot?start=link_"
    )
    assert body["token"] == body["deep_link"].rsplit("link_", 1)[1]


def test_init_persists_token_row(wired: TestClient) -> None:
    uid = _signup(wired, "link-b@example.com")
    r = wired.post("/auth/link/telegram/init")
    token = r.json()["token"]
    link = storage.link_token_get(token)
    assert link is not None
    assert link.user_id == uid
    assert link.status == "pending"


# ---------- webhook: /start link_<token> (no conflict) ----------


def test_webhook_link_happy_path_no_tg_account(wired: TestClient) -> None:
    """Most common path: email user links, no separate tg row exists yet."""
    uid = _signup(wired, "link-c@example.com")
    r = wired.post("/auth/link/telegram/init")
    token = r.json()["token"]

    _webhook(wired, {
        "message": {
            "chat": {"id": 100},
            "from": {"id": 55555},
            "text": f"/start link_{token}",
        }
    })

    link = storage.link_token_get(token)
    assert link is not None and link.status == "done"
    assert link.result == "linked"
    user = storage.user_by_id(uid)
    assert user is not None and user.telegram_id == 55555
    # A sendMessage was emitted — content shape matters to the UX.
    calls = wired._sent  # type: ignore[attr-defined]
    assert any(m == "sendMessage" and "Привязал" in p.get("text", "") for m, p in calls)


def test_webhook_link_already_linked_is_noop(wired: TestClient) -> None:
    _signup(wired, "link-d@example.com")
    r = wired.post("/auth/link/telegram/init")
    token1 = r.json()["token"]
    _webhook(wired, {
        "message": {"chat": {"id": 200}, "from": {"id": 7777}, "text": f"/start link_{token1}"}
    })
    # Same user tries to link the same TG id again via a fresh token.
    r = wired.post("/auth/link/telegram/init")
    token2 = r.json()["token"]
    _webhook(wired, {
        "message": {"chat": {"id": 200}, "from": {"id": 7777}, "text": f"/start link_{token2}"}
    })
    link2 = storage.link_token_get(token2)
    assert link2 is not None and link2.result == "already_linked"


def test_webhook_link_bad_token_rejected(wired: TestClient) -> None:
    _signup(wired, "link-e@example.com")
    _webhook(wired, {
        "message": {"chat": {"id": 300}, "from": {"id": 1}, "text": "/start link_bogus_token"}
    })
    calls = wired._sent  # type: ignore[attr-defined]
    assert any(
        m == "sendMessage" and "просрочена" in p.get("text", "")
        for m, p in calls
    )


# ---------- webhook: auto-merge when one side is empty ----------


def test_webhook_auto_merge_empty_src(wired: TestClient) -> None:
    """TG row exists but is data-empty → merge silently, no keyboard."""
    uid_email = _signup(wired, "link-f@example.com")
    # Seed an empty TG-only user directly in DB.
    storage.user_upsert_telegram(9001)
    r = wired.post("/auth/link/telegram/init")
    token = r.json()["token"]

    _webhook(wired, {
        "message": {"chat": {"id": 400}, "from": {"id": 9001}, "text": f"/start link_{token}"}
    })

    link = storage.link_token_get(token)
    assert link is not None and link.result == "merged_auto"
    user = storage.user_by_id(uid_email)
    assert user is not None and user.telegram_id == 9001
    # Old synthetic row is gone.
    assert storage.user_by_email("tg-9001@telegram.local") is None
    # No keyboard was shown (only a plain "merged" message).
    calls = wired._sent  # type: ignore[attr-defined]
    assert not any("inline_keyboard" in p.get("reply_markup", {}) for _, p in calls)


# ---------- webhook: conflict → keyboard → callback_query ----------


def test_webhook_conflict_shows_keyboard_then_callback_merges(
    wired: TestClient,
) -> None:
    """Both sides non-empty → keyboard sent; callback resolves the merge."""
    uid_email = _signup(wired, "link-g@example.com")
    # Give the email account some data so it's "non-empty".
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, 'email-word', 'email-слово', datetime('now'))",
            (uid_email,),
        )
    # Create tg-only user and give them a book.
    tg_user = storage.user_upsert_telegram(3141)
    with conn:
        conn.execute(
            "INSERT INTO books(user_id, title, author, language, source_format, "
            "source_bytes_size, total_pages, created_at) "
            "VALUES(?, 'Telegram Book', 'Auth', 'en', 'txt', 10, 1, datetime('now'))",
            (tg_user.id,),
        )

    r = wired.post("/auth/link/telegram/init")
    token = r.json()["token"]

    _webhook(wired, {
        "message": {"chat": {"id": 500}, "from": {"id": 3141}, "text": f"/start link_{token}"}
    })

    link = storage.link_token_get(token)
    assert link is not None and link.status == "conflict_waiting"
    assert link.chat_id == 500 and link.message_id == 777
    assert link.other_user_id == tg_user.id

    # User taps "Оставить текущий" → callback_data = "lk:<token>:dest".
    _webhook(wired, {
        "callback_query": {
            "id": "cb123",
            "data": f"lk:{token}:dest",
            "from": {"id": 3141},
        }
    })
    link = storage.link_token_get(token)
    assert link is not None and link.status == "done"
    assert link.result == "merged_dest"
    # Email user kept id + inherited the TG book + telegram_id.
    user = storage.user_by_id(uid_email)
    assert user is not None and user.telegram_id == 3141
    books = conn.execute(
        "SELECT title FROM books WHERE user_id = ?", (uid_email,)
    ).fetchall()
    assert [b["title"] for b in books] == ["Telegram Book"]


def test_webhook_conflict_keep_tg_winner_is_src(wired: TestClient) -> None:
    """Tapping "Оставить Telegram" picks tg-user as the survivor."""
    uid_email = _signup(wired, "link-h@example.com")
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, 'only-email', 'только-email', datetime('now'))",
            (uid_email,),
        )
    tg_user = storage.user_upsert_telegram(2718)
    with conn:
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, 'only-tg', 'только-tg', datetime('now'))",
            (tg_user.id,),
        )

    r = wired.post("/auth/link/telegram/init")
    token = r.json()["token"]
    _webhook(wired, {
        "message": {"chat": {"id": 600}, "from": {"id": 2718}, "text": f"/start link_{token}"}
    })
    _webhook(wired, {
        "callback_query": {"id": "cb456", "data": f"lk:{token}:src", "from": {"id": 2718}}
    })
    link = storage.link_token_get(token)
    assert link is not None and link.result == "merged_src"
    # The original email user row is gone; tg_user survived and absorbed data.
    assert storage.user_by_id(uid_email) is None
    tg_user2 = storage.user_by_id(tg_user.id)
    assert tg_user2 is not None
    rows = conn.execute(
        "SELECT lemma FROM user_dictionary WHERE user_id = ? ORDER BY lemma", (tg_user.id,)
    ).fetchall()
    assert [r["lemma"] for r in rows] == ["only-email", "only-tg"]


# ---------- /auth/link/telegram/status ----------


def test_status_pending_then_done(wired: TestClient) -> None:
    _signup(wired, "link-i@example.com")
    token = wired.post("/auth/link/telegram/init").json()["token"]
    r = wired.get(f"/auth/link/telegram/status?token={token}")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    # Advance the flow.
    _webhook(wired, {
        "message": {"chat": {"id": 700}, "from": {"id": 42}, "text": f"/start link_{token}"}
    })
    r = wired.get(f"/auth/link/telegram/status?token={token}")
    body = r.json()
    assert body["status"] == "done"
    assert body["result"] == "linked"


def test_status_reissues_session_when_winner_differs(wired: TestClient) -> None:
    """After a keep-TG merge the email session must flip to the surviving id."""
    uid_email = _signup(wired, "link-j@example.com")
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, 'e-word', 'e', datetime('now'))",
            (uid_email,),
        )
    tg_user = storage.user_upsert_telegram(6161)
    with conn:
        conn.execute(
            "INSERT INTO user_dictionary(user_id, lemma, translation, first_seen_at) "
            "VALUES(?, 't-word', 't', datetime('now'))",
            (tg_user.id,),
        )
    token = wired.post("/auth/link/telegram/init").json()["token"]
    _webhook(wired, {
        "message": {"chat": {"id": 800}, "from": {"id": 6161}, "text": f"/start link_{token}"}
    })
    _webhook(wired, {
        "callback_query": {"id": "cb789", "data": f"lk:{token}:src", "from": {"id": 6161}}
    })
    r = wired.get(f"/auth/link/telegram/status?token={token}")
    body = r.json()
    assert body["status"] == "done"
    assert body.get("session_reissued") is True
    # Follow-up /auth/me is now bound to the surviving TG-user row.
    me = wired.get("/auth/me").json()
    assert me["email"] == f"tg-6161@telegram.local"
