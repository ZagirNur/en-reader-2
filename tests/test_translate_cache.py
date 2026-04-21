"""Tests for the M19.1 per-instance translate endpoint contract.

In M6.2 the endpoint short-circuited on ``user_dictionary`` membership:
same lemma → one LLM call, regardless of sentence. M19.1 moves the
cache one level down — ``translate_one`` is called on every request,
and the prompt-hash cache lives inside it (``llm_cache`` table). The
endpoint's observable contract becomes:

* Every request funnels through ``translate_one``. Identical
  ``(unit_text, sentence, prev, next)`` tuples still turn into one
  real Gemini round-trip because the prompt-hash cache dedupes, but
  the endpoint itself does not skip the call.
* The first translation of a lemma for a user populates
  ``user_dictionary`` and bumps ``translate_miss``; subsequent calls
  bump ``translate_hit`` instead (used for observability).
* Deleting the dictionary row and calling again re-enters the miss
  path, re-populating the dictionary.

These tests pin the new contract by patching
``en_reader.app.translate_one`` directly (so the prompt-hash cache is
bypassed and every call is counted), which lets us verify the endpoint
side without asserting on the SDK wrapper.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.metrics import counters
from tests.conftest import FIXTURE_EMAIL


@pytest.fixture(autouse=True)
def _reset_counters() -> None:
    """Zero out the module-level counters before each test."""
    counters.translate_hit = 0
    counters.translate_miss = 0
    yield
    counters.translate_hit = 0
    counters.translate_miss = 0


def _payload(lemma: str = "ominous") -> dict[str, str]:
    return {
        "unit_text": lemma,
        "sentence": f"She whispered an {lemma} warning.",
        "lemma": lemma,
    }


# ---------- endpoint always invokes translate_one (M19.1) ----------


def test_first_call_invokes_llm(client: TestClient) -> None:
    mock = Mock(return_value=("зловещий", "llm"))
    with patch("en_reader.app.translate_one", mock):
        resp = client.post("/api/translate", json=_payload())
        assert resp.status_code == 200
        assert resp.json() == {"ru": "зловещий", "source": "llm"}
        mock.assert_called_once()


def test_second_call_also_invokes_llm(client: TestClient) -> None:
    """Under M19.1 the endpoint no longer short-circuits on lemma membership.

    The prompt-hash cache inside ``translate_one`` takes that role — but
    since we patch the symbol at the app level here, each call goes
    through the mock and counts as a real invocation.
    """
    mock = Mock(return_value=("зловещий", "llm"))
    with patch("en_reader.app.translate_one", mock):
        first = client.post("/api/translate", json=_payload())
        assert first.status_code == 200
        # M19.4: first call sources from "llm" (fresh) + insert into dict.
        assert first.json()["source"] == "llm"
        second = client.post("/api/translate", json=_payload())
        assert second.status_code == 200
        # Second call re-translates through translate_one (the prompt-hash
        # cache would short-circuit in real life), but the endpoint now
        # labels the result "dict" because the lemma is already known.
        assert second.json() == {"ru": "зловещий", "source": "dict"}
        assert mock.call_count == 2


def test_delete_then_call_invokes_llm_again(client: TestClient) -> None:
    mock = Mock(return_value=("зловещий", "llm"))
    with patch("en_reader.app.translate_one", mock):
        r1 = client.post("/api/translate", json=_payload())
        assert r1.status_code == 200
        d = client.delete("/api/dictionary/ominous")
        assert d.status_code == 204
        r2 = client.post("/api/translate", json=_payload())
        assert r2.status_code == 200
        assert mock.call_count == 2


# ---------- counters ----------


def test_hit_and_miss_counters(client: TestClient) -> None:
    """First call of a lemma → miss (dict insert); subsequent → hit (dict present).

    The counters now track dictionary-state transitions rather than
    LLM-cache outcomes, which is still the useful signal for observing
    "how many fresh words did the user hit today".
    """
    mock = Mock(return_value=("зловещий", "llm"))
    with patch("en_reader.app.translate_one", mock):
        client.post("/api/translate", json=_payload())
        client.post("/api/translate", json=_payload())
        assert counters.translate_miss == 1
        assert counters.translate_hit == 1


# ---------- persistence on miss ----------


def test_miss_calls_llm_and_persists(client: TestClient) -> None:
    mock = Mock(return_value=("зловещий", "llm"))
    with patch("en_reader.app.translate_one", mock):
        resp = client.post("/api/translate", json=_payload())
        assert resp.status_code == 200
        mock.assert_called_once()
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    assert storage.dict_get("ominous", user_id=user.id) == "зловещий"


# ---------- per-instance: different sentence → separate LLM call ----------


def test_different_sentence_triggers_separate_call(client: TestClient) -> None:
    """Two translations of the same lemma in different sentences both run.

    The server-side prompt-hash cache would make the second one free in
    practice, but the endpoint itself does not gate on lemma membership
    any more — every click is its own context-aware call.
    """
    mock = Mock(return_value=("зловещий", "llm"))
    with patch("en_reader.app.translate_one", mock):
        r1 = client.post(
            "/api/translate",
            json={
                "unit_text": "ominous",
                "sentence": "She whispered an ominous warning.",
                "lemma": "ominous",
                "prev_sentence": "The night was quiet.",
                "next_sentence": "Then the door creaked.",
            },
        )
        r2 = client.post(
            "/api/translate",
            json={
                "unit_text": "ominous",
                "sentence": "The ominous clouds gathered.",
                "lemma": "ominous",
                "prev_sentence": "",
                "next_sentence": "",
            },
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both sentences reach translate_one — the per-instance guarantee.
    assert mock.call_count == 2
