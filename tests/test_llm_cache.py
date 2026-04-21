"""Tests for the M19.1 prompt-hash LLM cache + background training card.

Three surfaces under test:

* ``storage.llm_cache_get`` / ``llm_cache_put`` — the DAO layer.
* ``translate._cached_llm_call`` — the wrapper that turns a system/user
  prompt into a cached Gemini round-trip. A fake ``_call_model`` proves
  identical prompts hit the cache and differing prompts miss.
* ``/api/translate`` background task — asserts the card is stored in
  ``user_dictionary.card_text`` after the response is delivered.

``translate_mod._sleep`` is replaced with a no-op so retry paths don't
slow the suite down. The shared ``tmp_db`` autouse fixture in
``tests/conftest.py`` gives each test a fresh SQLite file.
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
    """Reset the lazy Gemini client + make retries instant."""
    monkeypatch.setattr(translate_mod, "_client", None)
    monkeypatch.setattr(translate_mod, "_sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("E2E_MOCK_LLM", raising=False)


# ---------- DAO ----------


def test_llm_cache_put_and_get_round_trip() -> None:
    storage.llm_cache_put("hashA", "gemini-x", "ответ")
    assert storage.llm_cache_get("hashA") == "ответ"


def test_llm_cache_get_miss_returns_none() -> None:
    assert storage.llm_cache_get("nonexistent") is None


def test_llm_cache_first_write_wins() -> None:
    """OR IGNORE semantics: second put on the same hash is a no-op."""
    storage.llm_cache_put("hashB", "gemini-x", "первый")
    storage.llm_cache_put("hashB", "gemini-x", "второй")
    assert storage.llm_cache_get("hashB") == "первый"


# ---------- cached_llm_call ----------


def test_cached_llm_call_hit_skips_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical (model, system, user) prompts resolve to a single call."""
    calls: list[tuple[str, str, str, str]] = []

    def fake(client, model, system, user):  # noqa: ARG001
        calls.append((model, system, user, "кот"))
        return "кот"

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)

    r1 = translate_mod.translate_one("cat", "The cat sat.")
    r2 = translate_mod.translate_one("cat", "The cat sat.")

    assert r1 == r2 == "кот"
    assert len(calls) == 1, f"expected a single SDK call, got {len(calls)}"


def test_cached_llm_call_miss_on_different_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing prev/next sentence changes the hash and forces a new call."""
    calls: list[str] = []

    def fake(client, model, system, user):  # noqa: ARG001
        calls.append(user)
        return "кот"

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)

    translate_mod.translate_one("cat", "The cat sat.", "", "")
    translate_mod.translate_one("cat", "The cat sat.", "It was dark.", "")
    translate_mod.translate_one("cat", "The cat sat.", "", "Then it jumped.")

    assert len(calls) == 3


def test_prompt_hash_pins_context_layout() -> None:
    """The four-line user prompt is a stable contract between layers.

    Regressing this format changes every cached key in production, so
    we pin it explicitly. If someone deliberately bumps the layout, the
    ``v1`` prefix in ``_prompt_hash`` should be bumped too to invalidate
    the old cache in-place.
    """
    prompt = translate_mod._build_translate_prompt(
        "cat",
        "The cat sat.",
        "It was dark.",
        "Then it jumped.",
    )
    assert (
        prompt
        == "Word: cat\nPrevious: It was dark.\nSentence: The cat sat.\nNext: Then it jumped."
    )


def test_translate_with_context_sends_neighbours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user prompt reaching the SDK includes prev/next lines."""
    seen: list[str] = []

    def fake(client, model, system, user):  # noqa: ARG001
        seen.append(user)
        return "кот"

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)

    translate_mod.translate_one("cat", "The cat sat.", "It was dark.", "Then it jumped.")
    assert seen == [
        "Word: cat\nPrevious: It was dark.\nSentence: The cat sat.\nNext: Then it jumped."
    ]


# ---------- training card generation ----------


def test_generate_training_card_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card generator shares the llm_cache with translation.

    Two card builds for the same (word, ru, context) tuple collapse
    into one SDK call, because the prompt hash is identical.
    """
    sentinel = (
        "**Значение:** домашнее животное.\n"
        "**Пример:** A small cat.\n"
        "**Запомни:** кис-кис."
    )
    calls: list[str] = []

    def fake(client, model, system, user):  # noqa: ARG001
        calls.append(system)
        return sentinel

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)

    c1 = translate_mod.generate_training_card("cat", "кот", "The cat sat.")
    c2 = translate_mod.generate_training_card("cat", "кот", "The cat sat.")
    assert c1 == c2 == sentinel
    assert len(calls) == 1


def test_translate_endpoint_schedules_background_card(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First translation of a lemma triggers an async card build that
    lands in ``user_dictionary.card_text``.
    """
    monkeypatch.setattr(
        "en_reader.app.translate_one",
        lambda *a, **k: "зловещий",  # noqa: ARG005
    )
    card_text = (
        "**Значение:** пугающий.\n"
        "**Пример:** An ominous silence.\n"
        "**Запомни:** тёмное предчувствие."
    )
    monkeypatch.setattr(
        "en_reader.app.generate_training_card",
        lambda *a, **k: card_text,  # noqa: ARG005
    )

    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": "She whispered an ominous warning.",
            "lemma": "ominous",
        },
    )
    assert resp.status_code == 200

    # TestClient runs BackgroundTasks synchronously after the response
    # returns, so by the time .post() returns the card is already
    # persisted — no sleep needed.
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    stored = storage.card_get("ominous", user_id=user.id)
    assert stored == card_text


def test_card_backfill_on_second_translation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a lemma already exists but has no card yet, the next translate
    re-schedules the background card build.

    Guards against the failure mode where a migration adds a word but
    the background task crashes mid-flight; the next click should
    quietly recover.
    """
    monkeypatch.setattr(
        "en_reader.app.translate_one",
        lambda *a, **k: "зловещий",  # noqa: ARG005
    )
    call_count = {"n": 0}

    def card_once(*_a, **_k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise translate_mod.TranslateError("simulated transient failure")
        return "**Значение:** пугающий."

    monkeypatch.setattr("en_reader.app.generate_training_card", card_once)

    r1 = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": "She whispered.",
            "lemma": "ominous",
        },
    )
    assert r1.status_code == 200

    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    assert storage.card_get("ominous", user_id=user.id) is None  # first attempt crashed

    r2 = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": "She whispered.",
            "lemma": "ominous",
        },
    )
    assert r2.status_code == 200
    assert storage.card_get("ominous", user_id=user.id) == "**Значение:** пугающий."
    assert call_count["n"] == 2
