"""Tests for the dictionary-as-cache short-circuit in `/api/translate` (M6.2).

When a lemma is already in `user_dictionary`, the endpoint must return
the cached translation and skip the LLM call entirely. These tests pin
that behaviour by patching `en_reader.app.translate_one` with a mock and
asserting its call count across sequences of POSTs and DELETEs. They
also verify the `hit`/`miss` counters and the INFO-level log lines.

The `tmp_db` autouse fixture from `tests/conftest.py` gives each test a
fresh SQLite file; a local autouse fixture here zeros the module-level
``counters`` so values don't leak between tests.
"""

from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app
from en_reader.metrics import counters


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


# ---------- cache short-circuit ----------


def test_first_call_invokes_llm() -> None:
    mock = Mock(return_value="зловещий")
    with patch("en_reader.app.translate_one", mock):
        c = TestClient(app)
        resp = c.post("/api/translate", json=_payload())
        assert resp.status_code == 200
        assert resp.json() == {"ru": "зловещий"}
        mock.assert_called_once()


def test_second_call_skips_llm() -> None:
    mock = Mock(return_value="зловещий")
    with patch("en_reader.app.translate_one", mock):
        c = TestClient(app)
        first = c.post("/api/translate", json=_payload())
        assert first.status_code == 200
        second = c.post("/api/translate", json=_payload())
        assert second.status_code == 200
        assert second.json() == {"ru": "зловещий"}
        # Still only one LLM invocation after the second request.
        mock.assert_called_once()
        assert mock.call_count == 1


def test_delete_then_call_invokes_llm_again() -> None:
    mock = Mock(return_value="зловещий")
    with patch("en_reader.app.translate_one", mock):
        c = TestClient(app)
        r1 = c.post("/api/translate", json=_payload())
        assert r1.status_code == 200
        d = c.delete("/api/dictionary/ominous")
        assert d.status_code == 204
        r2 = c.post("/api/translate", json=_payload())
        assert r2.status_code == 200
        assert mock.call_count == 2


# ---------- counters ----------


def test_hit_increments_counter() -> None:
    mock = Mock(return_value="зловещий")
    with patch("en_reader.app.translate_one", mock):
        c = TestClient(app)
        c.post("/api/translate", json=_payload())
        c.post("/api/translate", json=_payload())
        assert counters.translate_miss == 1
        assert counters.translate_hit == 1


# ---------- persistence on miss ----------


def test_miss_calls_llm_and_persists() -> None:
    mock = Mock(return_value="зловещий")
    with patch("en_reader.app.translate_one", mock):
        c = TestClient(app)
        resp = c.post("/api/translate", json=_payload())
        assert resp.status_code == 200
        mock.assert_called_once()
    # After the miss path, the translation must be in the dictionary.
    assert storage.dict_get("ominous") == "зловещий"


# ---------- logging ----------


def test_logs_hit_and_miss(caplog: pytest.LogCaptureFixture) -> None:
    mock = Mock(return_value="зловещий")
    with patch("en_reader.app.translate_one", mock):
        c = TestClient(app)
        with caplog.at_level(logging.INFO, logger="en_reader.app"):
            c.post("/api/translate", json=_payload())
            c.post("/api/translate", json=_payload())

    messages = [r.getMessage() for r in caplog.records if r.name == "en_reader.app"]
    assert any("MISS" in m and "ominous" in m for m in messages)
    assert any("HIT" in m and "ominous" in m for m in messages)
