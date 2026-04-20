"""Tests for M16.7 training flashcards (flip session).

The flashcard frontend is an ``app.js`` state machine, so these tests
target the two backend endpoints the flip-session consumes:

* ``GET  /api/dictionary/training?limit=10`` — pool fetch on entry
* ``POST /api/dictionary/training/result``  — one call per verdict

The same backend serves the M16.6 MC screen (see
``tests/test_training_mc.py``), so the detailed progression-math
coverage already lives in :mod:`tests.test_progression`. The tests
here focus on the flashcard-specific verdicts (binary
Знал / Не знал → correct True / False), plus the empty-pool branch
the flip screen renders.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from tests.conftest import FIXTURE_EMAIL


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None, "client fixture must have created the user"
    return user.id


def test_flash_empty_pool_branch(client: TestClient) -> None:
    """An empty pool is the signal for the flashcard empty-state screen."""
    resp = client.get("/api/dictionary/training?limit=10")
    assert resp.status_code == 200
    assert resp.json() == []


def test_flash_knew_advances_status(client: TestClient) -> None:
    """Знал → POST {correct: true} promotes new → learning (one streak)."""
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


def test_flash_didnt_know_tracks_miss(client: TestClient) -> None:
    """Не знал → POST {correct: false} leaves status=new, wrong_count += 1."""
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
    # A wrong answer on a `new` row keeps it in `new` (M16.3 §3) and does
    # not promote, but `wrong_count` increments.
    assert row["status"] == "new"
    assert int(row["correct_streak"]) == 0
    assert int(row["wrong_count"]) == 1


def test_flash_didnt_know_demotes_learning_to_learning(client: TestClient) -> None:
    """A Не знал on a learning word keeps it learning but resets the streak.

    This mirrors the MC wrong-answer semantics — flashcards share the
    same DAO, so a Не знал after one correct answer drops the streak
    back to 0 rather than demoting the status back to ``new``.
    """
    user_id = _fixture_user_id()
    storage.dict_add("gloom", "мрак", user_id=user_id)

    # First a Знал to push to learning / streak=1.
    client.post(
        "/api/dictionary/training/result",
        json={"lemma": "gloom", "correct": True},
    )
    # Then a Не знал — streak should reset; status stays learning.
    resp = client.post(
        "/api/dictionary/training/result",
        json={"lemma": "gloom", "correct": False},
    )
    assert resp.status_code == 204

    conn = storage.get_db()
    row = conn.execute(
        "SELECT status, correct_streak, wrong_count FROM user_dictionary "
        "WHERE user_id = ? AND lemma = ?",
        (user_id, "gloom"),
    ).fetchone()
    assert row["status"] == "learning"
    assert int(row["correct_streak"]) == 0
    assert int(row["wrong_count"]) == 1
