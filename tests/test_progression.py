"""Tests for M16.3 word progression + training API.

The autouse ``tmp_db`` fixture in :mod:`tests.conftest` hands us a
freshly-migrated SQLite DB (schema v6, no rows) per test, so every case
here starts from an empty ``user_dictionary`` and never sees state
bleeding in from a neighbour.

Coverage per spec §7:

* State-machine transitions (``new`` → ``learning`` → ``review`` →
  ``mastered``, plus demotion on a wrong answer).
* Spacing-interval math: ``next_review_at`` ends up ~3 days out after
  the first promotion to ``review`` and ~14 days out after
  ``mastered``.
* Training-pool priority (overdue review first, then learning, then
  new).
* Stats aggregator returns the right counts across mixed states.
* ``POST /api/translate`` plumbs ``sentence`` / ``source_book_id``
  through to the dictionary row so the sheet UI can surface both.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from tests.conftest import FIXTURE_EMAIL


def _fixture_user_id() -> int:
    """Return the id of the ``client`` fixture's signed-up user."""
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None, "client fixture must have created the user"
    return user.id


def _get_row(lemma: str, user_id: int) -> dict:
    """Fetch a single ``user_dictionary`` row as a plain dict for assertions."""
    conn = storage.get_db()
    row = conn.execute(
        "SELECT status, correct_streak, wrong_count, last_reviewed_at, "
        "next_review_at FROM user_dictionary WHERE user_id = ? AND lemma = ?",
        (user_id, lemma.lower()),
    ).fetchone()
    assert row is not None, f"missing dict row: {lemma}"
    return {
        "status": row["status"],
        "correct_streak": int(row["correct_streak"]),
        "wrong_count": int(row["wrong_count"]),
        "last_reviewed_at": row["last_reviewed_at"],
        "next_review_at": row["next_review_at"],
    }


def _days_ahead(iso_ts: str) -> float:
    """Return how many days ``iso_ts`` is from now (may be negative)."""
    dt = datetime.fromisoformat(iso_ts)
    return (dt - datetime.now(timezone.utc)).total_seconds() / 86400.0


# ---------- state-machine transitions (spec §7, items 1-4) ----------


def test_new_to_learning_on_correct() -> None:
    storage.dict_add("ominous", "зловещий")
    storage.record_training_result("ominous", correct=True)
    row = _get_row("ominous", storage.SEED_USER_ID)
    assert row["status"] == "learning"
    assert row["correct_streak"] == 1
    assert row["last_reviewed_at"] is not None


def test_learning_to_review_on_two_correct() -> None:
    storage.dict_add("whisper", "шёпот")
    # First correct: new -> learning (streak=1).
    storage.record_training_result("whisper", correct=True)
    # Second correct: learning -> review (streak=2, +3 days).
    storage.record_training_result("whisper", correct=True)
    row = _get_row("whisper", storage.SEED_USER_ID)
    assert row["status"] == "review"
    assert row["correct_streak"] == 2
    # next_review_at should land roughly 3 days in the future.
    delta = _days_ahead(row["next_review_at"])
    assert 2.9 < delta < 3.1


def test_review_to_learning_on_wrong() -> None:
    storage.dict_add("gloom", "мрак")
    # Drive the word into the ``review`` lane (two correct answers).
    storage.record_training_result("gloom", correct=True)
    storage.record_training_result("gloom", correct=True)
    assert _get_row("gloom", storage.SEED_USER_ID)["status"] == "review"
    # Wrong answer demotes to learning and resets streak.
    storage.record_training_result("gloom", correct=False)
    row = _get_row("gloom", storage.SEED_USER_ID)
    assert row["status"] == "learning"
    assert row["correct_streak"] == 0
    assert row["wrong_count"] == 1


def test_review_to_mastered_on_two_correct() -> None:
    storage.dict_add("valley", "долина")
    # new -> learning -> review (streak=2).
    storage.record_training_result("valley", correct=True)
    storage.record_training_result("valley", correct=True)
    assert _get_row("valley", storage.SEED_USER_ID)["status"] == "review"
    # Two more correct answers inside ``review`` promote to mastered.
    # The first bumps streak from 2 -> 3 (still review), the second
    # from 3 -> 4 (mastered, +14 days).  Spec §3 allows either the 1st
    # or 2nd in-review correct to promote; we implement "once streak >= 2
    # at decision time" which takes two to get there from the first
    # correct that entered review.
    storage.record_training_result("valley", correct=True)
    storage.record_training_result("valley", correct=True)
    row = _get_row("valley", storage.SEED_USER_ID)
    assert row["status"] == "mastered"
    assert row["correct_streak"] >= 2
    delta = _days_ahead(row["next_review_at"])
    assert 13.9 < delta < 14.1


# ---------- pool priority + stats (spec §7, items 5-6) ----------


def _set_state(
    lemma: str,
    *,
    status: str,
    next_review_at: str | None = None,
    user_id: int = storage.SEED_USER_ID,
) -> None:
    """Force a dict row into a target state for priority tests.

    We bypass :func:`record_training_result` so the test can express
    "pretend this word is already in ``review`` and overdue" in one line
    without chaining six training calls.
    """
    conn = storage.get_db()
    with conn:
        conn.execute(
            "UPDATE user_dictionary SET status = ?, next_review_at = ? "
            "WHERE user_id = ? AND lemma = ?",
            (status, next_review_at, user_id, lemma.lower()),
        )


def test_pick_training_pool_priority() -> None:
    past = "2020-01-01T00:00:00+00:00"
    future = "2099-01-01T00:00:00+00:00"

    # Seed four lemmas, one per state-ish category.
    storage.dict_add("alpha", "альфа")
    _set_state("alpha", status="review", next_review_at=past)

    storage.dict_add("beta", "бета")
    _set_state("beta", status="learning", next_review_at=past)

    storage.dict_add("gamma", "гамма")
    _set_state("gamma", status="new", next_review_at=future)

    storage.dict_add("delta", "дельта")
    # A future-dated review should NOT appear in the pool (not yet due).
    _set_state("delta", status="review", next_review_at=future)

    # A mastered word should never surface in training.
    storage.dict_add("epsilon", "эпсилон")
    _set_state("epsilon", status="mastered", next_review_at=future)

    pool = storage.pick_training_pool(limit=10)
    lemmas = [w["lemma"] for w in pool]

    # review-overdue first, then learning, then new. delta (future review)
    # and epsilon (mastered) are excluded entirely.
    assert lemmas == ["alpha", "beta", "gamma"]
    assert all("lemma" in w and "translation" in w and "status" in w for w in pool)
    # ``example`` is nullable but the key must always be present.
    assert all("example" in w for w in pool)


def test_dict_stats_counts() -> None:
    # 2 new, 1 learning, 2 review (one due now, one due far future),
    # 1 mastered — 6 total.
    for lemma in ("w1", "w2"):
        storage.dict_add(lemma, "tr")
    storage.dict_add("w3", "tr")
    _set_state("w3", status="learning", next_review_at="2020-01-01T00:00:00+00:00")
    storage.dict_add("w4", "tr")
    _set_state("w4", status="review", next_review_at="2020-01-01T00:00:00+00:00")
    storage.dict_add("w5", "tr")
    _set_state("w5", status="review", next_review_at="2099-01-01T00:00:00+00:00")
    storage.dict_add("w6", "tr")
    _set_state("w6", status="mastered", next_review_at="2099-01-01T00:00:00+00:00")

    stats = storage.dict_stats()
    assert stats["total"] == 6
    assert stats["new"] == 2
    assert stats["learning"] == 1
    assert stats["review"] == 2
    assert stats["mastered"] == 1
    assert stats["active"] == 3  # new + learning
    # Only the past-dated review counts toward review_today.
    assert stats["review_today"] == 1


# ---------- translate wiring (spec §7, item 7) ----------


@pytest.fixture()
def fake_translate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``translate_one`` so the API test never calls Gemini."""

    def _fake(unit_text: str, sentence: str) -> str:  # noqa: ARG001
        return "зловещий"

    monkeypatch.setattr("en_reader.app.translate_one", _fake)


def test_translate_populates_example_and_source_book(
    client: TestClient, fake_translate: None, seed_book: int
) -> None:
    """``POST /api/translate`` with a source book captures example + book id.

    Uses the ``seed_book`` fixture so the ``source_book_id`` points at a
    real row owned by the fixture user — the FK constraint would reject
    a phantom id.
    """
    sentence = "She whispered an ominous warning."
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": sentence,
            "lemma": "ominous",
            "source_book_id": seed_book,
        },
    )
    assert resp.status_code == 200

    user_id = _fixture_user_id()
    conn = storage.get_db()
    row = conn.execute(
        "SELECT example, source_book_id, status FROM user_dictionary "
        "WHERE user_id = ? AND lemma = ?",
        (user_id, "ominous"),
    ).fetchone()
    assert row is not None
    assert row["example"] == sentence
    assert int(row["source_book_id"]) == seed_book
    assert row["status"] == "new"

    # The /api/dictionary/words route should surface the joined book metadata.
    words = client.get("/api/dictionary/words").json()
    match = next(w for w in words if w["lemma"] == "ominous")
    assert match["example"] == sentence
    assert match["source_book"] == {"id": seed_book, "title": "Fixture Book"}
    assert match["ipa"] is None
    assert match["pos"] is None


# ---------- misc DAO edges ----------


def test_record_training_result_unknown_lemma_is_noop() -> None:
    """Replaying a result for a deleted word must not raise."""
    # No insert beforehand — function should silently succeed.
    storage.record_training_result("never-seen", correct=True)
    storage.record_training_result("never-seen", correct=False)


def test_training_result_api_returns_204(client: TestClient) -> None:
    """The POST endpoint returns 204 and updates progression state."""
    user_id = _fixture_user_id()
    storage.dict_add("ominous", "зловещий", user_id=user_id)
    resp = client.post(
        "/api/dictionary/training/result",
        json={"lemma": "ominous", "correct": True},
    )
    assert resp.status_code == 204
    conn = storage.get_db()
    row = conn.execute(
        "SELECT status FROM user_dictionary WHERE user_id = ? AND lemma = ?",
        (user_id, "ominous"),
    ).fetchone()
    assert row["status"] == "learning"


def test_dictionary_stats_endpoint(client: TestClient) -> None:
    user_id = _fixture_user_id()
    storage.dict_add("a", "a", user_id=user_id)
    storage.dict_add("b", "b", user_id=user_id)
    resp = client.get("/api/dictionary/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["new"] == 2


def test_dictionary_words_filter(client: TestClient) -> None:
    user_id = _fixture_user_id()
    storage.dict_add("a", "a", user_id=user_id)
    storage.dict_add("b", "b", user_id=user_id)
    # Promote ``a`` one step via the DAO so there's a mix of statuses.
    storage.record_training_result("a", correct=True, user_id=user_id)
    body = client.get("/api/dictionary/words?status=learning").json()
    assert [w["lemma"] for w in body] == ["a"]

    body_all = client.get("/api/dictionary/words?status=all").json()
    assert {w["lemma"] for w in body_all} == {"a", "b"}

    # Unknown status is a 400.
    assert client.get("/api/dictionary/words?status=bogus").status_code == 400
