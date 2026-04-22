"""Tests for the M20.3 simplify mode (``/api/translate?mode=simplify``).

Three surfaces:

* :func:`translate.simplify_one` — direct unit test with a stubbed
  Gemini that returns either a simpler synonym or the ``@SAME@``
  sentinel.
* The endpoint with ``mode="simplify"`` — must never touch
  ``user_dictionary`` and must return ``is_simplest`` correctly.
* The endpoint with ``mode="translate"`` (legacy) — sanity-checked
  here so a regression that broke the translate branch while wiring
  simplify is caught right next to the new behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from en_reader import translate as translate_mod
from tests.conftest import FIXTURE_EMAIL


@pytest.fixture(autouse=True)
def _reset_translate_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(translate_mod, "_client", None)
    monkeypatch.setattr(translate_mod, "_sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("E2E_MOCK_LLM", raising=False)


def _stub_call_model(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[str]:
    """Replace the Gemini round-trip with a fixed reply."""
    seen: list[str] = []

    def fake(client, model, system, user):  # noqa: ARG001
        seen.append(user)
        return reply

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)
    return seen


# ---------- simplify_one ----------


def test_simplify_one_returns_simpler_synonym(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_call_model(monkeypatch, "ran")
    text, is_simplest, source = translate_mod.simplify_one(
        "sprinted", "She sprinted across the meadow."
    )
    assert text == "ran"
    assert is_simplest is False
    assert source == "llm"


def test_simplify_one_same_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_call_model(monkeypatch, "@SAME@")
    text, is_simplest, source = translate_mod.simplify_one("run", "She had to run.")
    assert text is None
    assert is_simplest is True
    assert source == "llm"


def test_simplify_one_cache_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _stub_call_model(monkeypatch, "ran")
    first = translate_mod.simplify_one("sprinted", "She sprinted away.")
    second = translate_mod.simplify_one("sprinted", "She sprinted away.")
    assert first[0] == second[0] == "ran"
    assert first[2] == "llm"
    assert second[2] == "cache"
    assert len(seen) == 1


# ---------- endpoint ----------


def test_endpoint_simplify_returns_text_and_skips_dict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "en_reader.app.simplify_one",
        lambda *_a, **_k: ("ran", False, "llm"),
    )
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "sprinted",
            "sentence": "She sprinted across the meadow.",
            "lemma": "sprint",
            "mode": "simplify",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "ran"
    assert body["is_simplest"] is False
    assert body["mode"] == "simplify"
    assert body["source"] == "llm"
    # And — crucially — no row landed in the user dictionary.
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    assert storage.dict_get("sprint", user_id=user.id) is None


def test_endpoint_simplify_is_simplest_no_replacement(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "en_reader.app.simplify_one",
        lambda *_a, **_k: (None, True, "cache"),
    )
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "run",
            "sentence": "She had to run.",
            "lemma": "run",
            "mode": "simplify",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_simplest"] is True
    assert body["text"] is None
    # ``ru`` falls back to the input word so the field is never empty
    # — keeps the legacy contract usable for any client that ignores
    # the new ``text`` / ``is_simplest`` fields.
    assert body["ru"] == "run"


def test_endpoint_translate_branch_unaffected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default mode (translate) still uses translate_one + dict_add."""
    monkeypatch.setattr(
        "en_reader.app.translate_one",
        lambda *_a, **_k: ("зловещий", "llm"),
    )
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": "She whispered.",
            "lemma": "ominous",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ru"] == "зловещий"
    assert body["mode"] == "translate"
    assert body["is_simplest"] is False
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    assert storage.dict_get("ominous", user_id=user.id) == "зловещий"


def test_endpoint_simplify_invalid_mode_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "x",
            "sentence": "x",
            "lemma": "x",
            "mode": "garbage",
        },
    )
    assert resp.status_code == 422
