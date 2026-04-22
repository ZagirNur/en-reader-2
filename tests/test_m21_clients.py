"""Tests for the M21 multi-client surface.

Covers the five new capabilities native / extension clients depend on:

* Bearer tokens: ``/auth/token`` (password + telegram modes),
  ``/auth/token/refresh`` (single-use), ``/auth/token/revoke``.
* ``get_current_user`` accepts bearer alongside cookie.
* Path-rewrite alias: ``/api/v1/…`` hits the same handlers as ``/api/…``.
* Dictionary delta-sync: ``/api/dictionary/sync`` returns upserts +
  tombstones, respects ``?since=``.
* Batch translate: ``/api/translate/batch`` up to 50 items.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from en_reader import storage, tokens
from en_reader.app import app
from tests.conftest import FIXTURE_EMAIL


# ---------- tokens module unit tests ----------


def test_issue_and_verify_round_trip() -> None:
    user_id = storage.user_create("t21@example.com", "hashed-placeholder")
    pair = tokens.issue(user_id)
    assert pair["token_type"] == "Bearer"
    assert pair["access_token"].startswith("er_")
    assert pair["refresh_token"].startswith("er_")
    assert tokens.verify_access(pair["access_token"]) == user_id
    # Refresh token should NOT verify as access (kind mismatch).
    assert tokens.verify_access(pair["refresh_token"]) is None


def test_rotate_refresh_is_single_use() -> None:
    user_id = storage.user_create("t21b@example.com", "p")
    pair1 = tokens.issue(user_id)
    pair2 = tokens.rotate_refresh(pair1["refresh_token"])
    assert pair2 is not None
    # First refresh was burned.
    assert tokens.rotate_refresh(pair1["refresh_token"]) is None
    # New pair works.
    assert tokens.verify_access(pair2["access_token"]) == user_id


def test_revoke_kills_access_immediately() -> None:
    user_id = storage.user_create("t21c@example.com", "p")
    pair = tokens.issue(user_id)
    assert tokens.verify_access(pair["access_token"]) == user_id
    tokens.revoke_token(pair["access_token"])
    assert tokens.verify_access(pair["access_token"]) is None


def test_revoke_all_clears_every_live_token() -> None:
    user_id = storage.user_create("t21d@example.com", "p")
    p1 = tokens.issue(user_id)
    p2 = tokens.issue(user_id)
    n = tokens.revoke_all(user_id)
    assert n >= 4  # two pairs = four rows
    assert tokens.verify_access(p1["access_token"]) is None
    assert tokens.verify_access(p2["access_token"]) is None


# ---------- endpoint tests ----------


def test_auth_token_password_returns_pair() -> None:
    c = TestClient(app)
    c.post("/auth/signup", json={"email": "api21@example.com", "password": "longpass1"})
    r = c.post(
        "/auth/token",
        json={"mode": "password", "email": "api21@example.com", "password": "longpass1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"].startswith("er_")
    assert body["refresh_token"].startswith("er_")
    # Using the bearer, /auth/me must succeed WITHOUT a cookie.
    bare = TestClient(app)
    me = bare.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "api21@example.com"


def test_auth_token_password_wrong_creds_401() -> None:
    c = TestClient(app)
    c.post("/auth/signup", json={"email": "api21b@example.com", "password": "longpass1"})
    r = c.post(
        "/auth/token",
        json={"mode": "password", "email": "api21b@example.com", "password": "WRONG"},
    )
    assert r.status_code == 401


def test_refresh_endpoint_rotates_and_single_use() -> None:
    c = TestClient(app)
    c.post("/auth/signup", json={"email": "api21c@example.com", "password": "longpass1"})
    r = c.post(
        "/auth/token",
        json={"mode": "password", "email": "api21c@example.com", "password": "longpass1"},
    )
    body = r.json()
    r2 = c.post("/auth/token/refresh", json={"refresh_token": body["refresh_token"]})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["access_token"] != body["access_token"]
    # Re-using the first refresh now fails.
    r3 = c.post("/auth/token/refresh", json={"refresh_token": body["refresh_token"]})
    assert r3.status_code == 401


def test_revoke_endpoint_kills_future_access() -> None:
    c = TestClient(app)
    c.post("/auth/signup", json={"email": "api21d@example.com", "password": "longpass1"})
    body = c.post(
        "/auth/token",
        json={"mode": "password", "email": "api21d@example.com", "password": "longpass1"},
    ).json()
    r = c.post("/auth/token/revoke", json={"token": body["access_token"]})
    assert r.status_code == 204
    bare = TestClient(app)
    me = bare.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 401


# ---------- bearer acceptance on /api/* ----------


def test_bearer_auth_on_api_dictionary() -> None:
    c = TestClient(app)
    c.post("/auth/signup", json={"email": "api21e@example.com", "password": "longpass1"})
    body = c.post(
        "/auth/token",
        json={"mode": "password", "email": "api21e@example.com", "password": "longpass1"},
    ).json()
    bare = TestClient(app)
    r = bare.get(
        "/api/dictionary",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json() == {}


# ---------- /api/v1 alias ----------


def test_api_v1_alias_routes_same_handler(client: TestClient) -> None:
    """``GET /api/v1/dictionary`` must behave identically to ``GET /api/dictionary``."""
    r_v = client.get("/api/v1/dictionary")
    r_orig = client.get("/api/dictionary")
    assert r_v.status_code == 200
    assert r_orig.status_code == 200
    assert r_v.json() == r_orig.json()


# ---------- dictionary sync ----------


def test_dictionary_sync_full_snapshot_and_delta(client: TestClient) -> None:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    storage.dict_add("alpha", "альфа", user_id=user.id)
    storage.dict_add("beta", "бета", user_id=user.id)
    storage.dict_remove("beta", user_id=user.id)  # produces a tombstone

    r = client.get("/api/dictionary/sync")
    assert r.status_code == 200
    body = r.json()
    server_time_first = body["server_time"]
    upserts = {u["lemma"] for u in body["upserts"]}
    deletes = {d["lemma"] for d in body["deletes"]}
    assert "alpha" in upserts
    assert "beta" not in upserts  # deleted
    assert "beta" in deletes

    # Delta with ``since = server_time_first`` returns nothing new.
    r2 = client.get(f"/api/dictionary/sync?since={server_time_first}")
    body2 = r2.json()
    assert body2["upserts"] == []
    assert body2["deletes"] == []

    # Add one more lemma; the delta now contains just it.
    storage.dict_add("gamma", "гамма", user_id=user.id)
    r3 = client.get(f"/api/dictionary/sync?since={server_time_first}")
    body3 = r3.json()
    assert {u["lemma"] for u in body3["upserts"]} == {"gamma"}


# ---------- batch translate ----------


def test_translate_batch_runs_every_item(client: TestClient) -> None:
    with patch("en_reader.app.translate_one", Mock(return_value=("перевод", "llm"))):
        r = client.post(
            "/api/translate/batch",
            json={
                "items": [
                    {"unit_text": f"w{i}", "sentence": f"context {i}", "lemma": f"w{i}"}
                    for i in range(5)
                ]
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == 5
    assert all(item["ru"] == "перевод" for item in body["results"])
    # Every item should be a fresh insert → source "llm".
    assert all(item["source"] == "llm" for item in body["results"])


def test_translate_batch_mixed_mode(client: TestClient) -> None:
    with patch("en_reader.app.simplify_one", Mock(return_value=("ran", False, "llm"))):
        r = client.post(
            "/api/translate/batch",
            json={
                "items": [
                    {"unit_text": "sprinted", "sentence": "x", "lemma": "sprint"},
                ],
                "mode": "simplify",
            },
        )
    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["mode"] == "simplify"
    assert result["text"] == "ran"


def test_translate_batch_caps_at_50_items(client: TestClient) -> None:
    r = client.post(
        "/api/translate/batch",
        json={"items": [{"unit_text": "x", "sentence": "x", "lemma": "x"}] * 51},
    )
    assert r.status_code == 422
