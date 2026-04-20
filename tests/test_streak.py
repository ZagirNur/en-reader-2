"""Tests for the M16.8 daily streak + goal pipeline.

The training result endpoint now also stamps a ``daily_activity`` row,
``storage.compute_streak`` walks it backwards to produce the consecutive
days count, and ``GET /api/me/streak`` ties both to today's goal shape.
These tests pin down:

* End-to-end: a correct POST lands in the daily_activity row and the
  streak + goal derived from it.
* Wrong answers count toward the streak (``words_trained_total``
  increments) but not toward ``done`` (``words_trained_correct``).
* The walk-backwards algorithm honours the "today empty" clause so a
  user opening the app first thing in the morning doesn't see the
  previous day's work evaporate.
* Gaps break the chain at the first missing calendar day.
* ``/api/me/streak`` carries the exact documented shape and refuses
  anonymous callers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from en_reader import storage
from tests.conftest import FIXTURE_EMAIL


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None, "client fixture must have created the user"
    return user.id


def _plant_activity(
    user_id: int,
    *,
    days_ago: int,
    correct: int = 1,
    total: int = 1,
) -> None:
    """Insert a synthetic daily_activity row ``days_ago`` calendar days back."""
    date = (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO daily_activity(user_id, date, words_trained_correct, "
            "words_trained_total) VALUES(?, ?, ?, ?)",
            (user_id, date, correct, total),
        )


def test_post_one_correct_sets_streak_and_goal(client: TestClient) -> None:
    """A single correct answer today → streak=1, done=1, percent=10."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)

    resp = client.post(
        "/api/dictionary/training/result",
        json={"lemma": "ominous", "correct": True},
    )
    assert resp.status_code == 204

    body = client.get("/api/me/streak").json()
    assert body["streak"] == 1
    assert body["today"]["target"] == 10
    assert body["today"]["done"] == 1
    assert body["today"]["percent"] == 10


def test_wrong_answers_count_streak_but_not_goal(client: TestClient) -> None:
    """5 correct + 3 wrong → streak=1, done=5 (correct only), percent=50."""
    user_id = _fixture_user_id()
    for lemma, ru in [
        ("a", "а"),
        ("b", "б"),
        ("c", "в"),
        ("d", "г"),
        ("e", "д"),
    ]:
        storage.dict_add(lemma, ru, user_id=user_id)

    for lemma in ("a", "b", "c", "d", "e"):
        client.post(
            "/api/dictionary/training/result",
            json={"lemma": lemma, "correct": True},
        )
    for lemma in ("a", "b", "c"):
        client.post(
            "/api/dictionary/training/result",
            json={"lemma": lemma, "correct": False},
        )

    body = client.get("/api/me/streak").json()
    assert body["streak"] == 1
    # Goal counts *correct* only — 5 out of the 8 total answers.
    assert body["today"]["done"] == 5
    assert body["today"]["percent"] == 50


def test_yesterday_activity_extends_streak(client: TestClient) -> None:
    """Yesterday planted + today correct → streak=2."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)
    _plant_activity(user_id, days_ago=1)

    client.post(
        "/api/dictionary/training/result",
        json={"lemma": "ominous", "correct": True},
    )

    body = client.get("/api/me/streak").json()
    assert body["streak"] == 2


def test_streak_includes_yesterday_when_today_empty(client: TestClient) -> None:
    """Morning-open rule: today empty → streak walks from yesterday."""
    user_id = _fixture_user_id()
    _plant_activity(user_id, days_ago=1)
    _plant_activity(user_id, days_ago=2)

    body = client.get("/api/me/streak").json()
    # Today is empty but yesterday and day-before both carry rows —
    # streak spans the two-day chain ending at yesterday.
    assert body["streak"] == 2
    # Nothing answered today → done=0, percent=0.
    assert body["today"]["done"] == 0
    assert body["today"]["percent"] == 0


def test_gap_breaks_streak(client: TestClient) -> None:
    """Yesterday + skip two days back → streak=1 (gap on day-2)."""
    user_id = _fixture_user_id()
    _plant_activity(user_id, days_ago=1)
    _plant_activity(user_id, days_ago=3)  # intentional gap at days_ago=2

    body = client.get("/api/me/streak").json()
    assert body["streak"] == 1


def test_streak_endpoint_shape(client: TestClient) -> None:
    """``GET /api/me/streak`` returns exactly ``{streak, today:{target,done,percent}}``."""
    body = client.get("/api/me/streak").json()
    assert set(body.keys()) == {"streak", "today"}
    assert set(body["today"].keys()) == {"target", "done", "percent"}
    assert body["streak"] == 0
    assert body["today"] == {"target": 10, "done": 0, "percent": 0}


def test_streak_requires_auth() -> None:
    """Anonymous callers get 401 — no leaking per-user progress."""
    from en_reader.app import app

    anon = TestClient(app)
    resp = anon.get("/api/me/streak")
    assert resp.status_code == 401


def test_training_result_upserts_daily_activity(client: TestClient) -> None:
    """Two POSTs on the same day fold into a single daily_activity row."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)
    storage.dict_add("whisper", "шёпот", user_id=user_id)

    client.post(
        "/api/dictionary/training/result",
        json={"lemma": "ominous", "correct": True},
    )
    client.post(
        "/api/dictionary/training/result",
        json={"lemma": "whisper", "correct": False},
    )

    today = datetime.now(timezone.utc).date().isoformat()
    row = (
        storage.get_db()
        .execute(
            "SELECT words_trained_correct, words_trained_total "
            "FROM daily_activity WHERE user_id = ? AND date = ?",
            (user_id, today),
        )
        .fetchone()
    )
    assert row is not None
    assert int(row["words_trained_correct"]) == 1
    assert int(row["words_trained_total"]) == 2
