"""Tests for M16.6 training multiple-choice screen.

The frontend state machine lives entirely in ``app.js`` — these tests
exercise the API round-trip the MC screen depends on: the pool fetch
(``GET /api/dictionary/training``) and the per-answer report
(``POST /api/dictionary/training/result``). The heavier progression
math (interval math, status demotion, sweep semantics) already has
dedicated coverage in :mod:`tests.test_progression`; here we focus on
the contract that the MC session actually touches.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from tests.conftest import FIXTURE_EMAIL


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None, "client fixture must have created the user"
    return user.id


def test_training_pool_returns_seeded_words(client: TestClient) -> None:
    """The MC session's first fetch surfaces the user's eligible words."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)
    storage.dict_add("whisper", "шёпот", user_id=user_id)
    storage.dict_add("gloom", "мрак", user_id=user_id)

    resp = client.get("/api/dictionary/training?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    lemmas = {w["lemma"] for w in body}
    assert lemmas == {"ominous", "whisper", "gloom"}
    # Each row must carry the fields the MC card renders.
    for w in body:
        assert "lemma" in w
        assert "translation" in w
        assert "example" in w  # nullable but the key is required


def test_training_pool_empty_when_no_words(client: TestClient) -> None:
    """A fresh account shows the empty-state branch on the MC screen."""
    resp = client.get("/api/dictionary/training?limit=10")
    assert resp.status_code == 200
    assert resp.json() == []


def test_training_pool_excludes_mastered(client: TestClient) -> None:
    """Mastered words are filtered out of the training pool."""
    user_id = _fixture_user_id()
    storage.dict_add("alpha", "альфа", user_id=user_id)
    storage.dict_add("beta", "бета", user_id=user_id)

    # Hand-promote ``alpha`` to mastered so it stops surfacing.
    conn = storage.get_db()
    with conn:
        conn.execute(
            "UPDATE user_dictionary SET status='mastered', correct_streak=3 "
            "WHERE user_id = ? AND lemma = 'alpha'",
            (user_id,),
        )

    body = client.get("/api/dictionary/training?limit=10").json()
    assert [w["lemma"] for w in body] == ["beta"]


def test_training_result_correct_promotes_status(client: TestClient) -> None:
    """POST /training/result with correct=True advances new → learning."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)

    resp = client.post(
        "/api/dictionary/training/result",
        json={"lemma": "ominous", "correct": True},
    )
    assert resp.status_code == 204

    conn = storage.get_db()
    row = conn.execute(
        "SELECT status, correct_streak FROM user_dictionary " "WHERE user_id = ? AND lemma = ?",
        (user_id, "ominous"),
    ).fetchone()
    assert row["status"] == "learning"
    assert int(row["correct_streak"]) == 1


def test_training_result_wrong_bumps_wrong_count(client: TestClient) -> None:
    """A wrong answer on a fresh word keeps status=new but tracks the miss."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)

    resp = client.post(
        "/api/dictionary/training/result",
        json={"lemma": "ominous", "correct": False},
    )
    assert resp.status_code == 204

    conn = storage.get_db()
    row = conn.execute(
        "SELECT status, correct_streak, wrong_count FROM user_dictionary "
        "WHERE user_id = ? AND lemma = ?",
        (user_id, "ominous"),
    ).fetchone()
    # A wrong answer on a `new` row keeps it in `new` (per M16.3 §3)
    # and does not promote, but `wrong_count` increments.
    assert row["status"] == "new"
    assert int(row["correct_streak"]) == 0
    assert int(row["wrong_count"]) == 1


def test_training_result_unknown_lemma_is_204(client: TestClient) -> None:
    """A stale replay for a deleted word must not 404 — the DAO no-ops."""
    resp = client.post(
        "/api/dictionary/training/result",
        json={"lemma": "never-seen", "correct": True},
    )
    assert resp.status_code == 204
