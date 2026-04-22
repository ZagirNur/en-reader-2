"""Tests for `en_reader.dictionary` and the M20.1 rich training card.

Hits on the real ``dictionaryapi.dev`` are stubbed via ``httpx.Client``
monkeypatch so the suite stays offline + deterministic. The prompt-
hash cache round-trip is exercised directly via SQLite — each test
gets a fresh DB from the ``tmp_db`` autouse fixture.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from en_reader import dictionary, storage
from en_reader import translate as translate_mod


_DROP_PAYLOAD = [
    {
        "word": "drop",
        "phonetic": "/drɒp/",
        "phonetics": [
            {"text": "/drɒp/", "audio": "https://example/drop.mp3"},
            {"text": "/drɑːp/", "audio": ""},
        ],
        "meanings": [
            {
                "partOfSpeech": "noun",
                "definitions": [
                    {"definition": "A small amount of liquid.", "example": "A drop of water."},
                    {"definition": "A decrease."},
                ],
                "synonyms": ["droplet", "bead"],
            },
            {
                "partOfSpeech": "verb",
                "definitions": [
                    {"definition": "To let fall.", "example": "Drop the ball."},
                ],
                "synonyms": ["release"],
            },
        ],
    }
]


class _FakeClient:
    """Stand-in for ``httpx.Client`` wired with a scripted status + body."""

    def __init__(self, status: int, body) -> None:
        self._status = status
        self._body = body

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, _url: str):  # noqa: ARG002
        return SimpleNamespace(
            status_code=self._status,
            json=lambda: self._body,
        )


def _install_client(monkeypatch: pytest.MonkeyPatch, status: int, body) -> list[str]:
    """Patch ``httpx.Client`` to hand out ``_FakeClient`` and return a call log."""
    calls: list[str] = []

    def factory(*_a, **_k):
        calls.append("new-client")
        return _FakeClient(status, body)

    monkeypatch.setattr(dictionary.httpx, "Client", factory)
    return calls


# ---------- fetch_entry ----------


def test_fetch_entry_parses_ipa_and_meanings(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, 200, _DROP_PAYLOAD)
    entry = dictionary.fetch_entry("drop")
    assert entry is not None
    assert entry.word == "drop"
    assert entry.ipa == "/drɒp/"
    assert entry.audio_url == "https://example/drop.mp3"
    pos_list = [m.pos for m in entry.meanings]
    assert pos_list == ["noun", "verb"]
    assert "A small amount of liquid." in entry.meanings[0].definitions
    assert "A drop of water." in entry.meanings[0].examples
    assert "droplet" in entry.synonyms


def test_fetch_entry_404_returns_none_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_client(monkeypatch, 404, {})
    assert dictionary.fetch_entry("not-a-real-word") is None
    # The 404 is itself cached as ``[]`` so a repeat lookup doesn't
    # re-hit the network. Swap the factory to one that would fail to
    # confirm the second call never reaches HTTP.

    def fail_factory(*_a, **_k):
        raise AssertionError("fetch_entry should not re-hit HTTP on cached 404")

    monkeypatch.setattr(dictionary.httpx, "Client", fail_factory)
    assert dictionary.fetch_entry("not-a-real-word") is None
    assert calls == ["new-client"], "first call should have made a network request"


def test_fetch_entry_cache_hit_skips_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_client(monkeypatch, 200, _DROP_PAYLOAD)
    first = dictionary.fetch_entry("drop")
    assert first is not None
    # Second call MUST use the cached SQLite row.

    def fail_factory(*_a, **_k):
        raise AssertionError("fetch_entry should not re-hit HTTP on cache HIT")

    monkeypatch.setattr(dictionary.httpx, "Client", fail_factory)
    second = dictionary.fetch_entry("drop")
    assert second is not None
    assert second.ipa == first.ipa
    assert calls == ["new-client"]


def test_fetch_entry_network_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom_factory(*_a, **_k):
        raise dictionary.httpx.ConnectError("network down")

    monkeypatch.setattr(dictionary.httpx, "Client", boom_factory)
    assert dictionary.fetch_entry("drop") is None
    # Nothing cached: next call retries HTTP (don't pin a bogus miss).
    conn = storage.get_db()
    rows = conn.execute("SELECT COUNT(*) AS n FROM llm_cache").fetchone()
    assert rows["n"] == 0


# ---------- build_rich_card ----------


def _stub_llm(monkeypatch: pytest.MonkeyPatch, json_response: dict) -> list[str]:
    """Replace Gemini SDK with a synchronous stub that returns a JSON string."""
    seen: list[str] = []

    def fake(client, model, system, user):  # noqa: ARG001
        seen.append(user)
        return json.dumps(json_response, ensure_ascii=False)

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)
    monkeypatch.setattr(translate_mod, "_sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(translate_mod, "_client", None)
    return seen


def test_build_rich_card_with_dictionary(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, 200, _DROP_PAYLOAD)
    _stub_llm(
        monkeypatch,
        {
            "definitions_ru": [
                "Небольшое количество жидкости.",
                "Уменьшение.",
                "Ронять.",
            ],
            "examples": [
                {"en": "A drop of rain fell.", "ru": "Упала капля дождя."},
                {"en": "The prices had a drop.", "ru": "Цены упали."},
                {"en": "Don't drop the glass.", "ru": "Не урони стакан."},
            ],
            "usage_note_ru": "‘drop’ — и существительное (капля), и глагол (ронять).",
        },
    )
    card = translate_mod.build_rich_card("drop", "капля", "A drop of water fell.")
    assert card["word"] == "drop"
    assert card["ipa"] == "/drɒp/"
    assert card["translation"] == "капля"
    assert card["source"] == "dictionary+llm"
    # Definitions were merged positionally back into the POS blocks.
    noun = card["meanings"][0]
    assert noun["definitions_ru"][0] == "Небольшое количество жидкости."
    assert len(card["examples_ru"]) >= 3
    assert card["usage_note_ru"].startswith("‘drop’")


def test_build_rich_card_falls_back_without_dictionary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 404 = phrasal verb / unknown word. The LLM-only branch must still
    # produce a valid card with examples.
    _install_client(monkeypatch, 404, {})
    _stub_llm(
        monkeypatch,
        {
            "definitions_ru": [],
            "examples": [
                {"en": "Please pick up the book.", "ru": "Подними книгу, пожалуйста."},
                {"en": "I'll pick up the phone.", "ru": "Я возьму трубку."},
                {"en": "Can you pick up milk?", "ru": "Можешь купить молоко?"},
            ],
            "usage_note_ru": "pick up меняет смысл по контексту.",
        },
    )
    card = translate_mod.build_rich_card("pick up", "поднять", "She picked up the phone.")
    assert card["source"] == "llm"
    assert card["meanings"] == []
    assert len(card["examples_ru"]) == 3


def test_build_rich_card_survives_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A total Gemini failure still returns a renderable dictionary-only card."""
    _install_client(monkeypatch, 200, _DROP_PAYLOAD)

    def always_fail(*_a, **_k):
        raise RuntimeError("Gemini on fire")

    monkeypatch.setattr(translate_mod, "_call_model", always_fail)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)
    monkeypatch.setattr(translate_mod, "_sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(translate_mod, "_client", None)

    card = translate_mod.build_rich_card("drop", "капля", "A drop of water fell.")
    assert card["word"] == "drop"
    assert card["ipa"] == "/drɒp/"
    assert card["translation"] == "капля"
    assert card["source"] == "dictionary-only"
    # LLM-sourced fields stay empty but the shape is intact.
    assert card["examples_ru"] == []
    assert card["usage_note_ru"] == ""


def test_build_rich_card_tolerates_code_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini occasionally wraps its JSON in a ``` fence; we peel it."""
    _install_client(monkeypatch, 200, _DROP_PAYLOAD)

    body = json.dumps(
        {
            "definitions_ru": ["RU", "RU", "RU"],
            "examples": [{"en": "x", "ru": "y"}] * 3,
            "usage_note_ru": "hint",
        }
    )
    fenced = f"```json\n{body}\n```"

    def fake(client, model, system, user):  # noqa: ARG001
        return fenced

    monkeypatch.setattr(translate_mod, "_call_model", fake)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: None)
    monkeypatch.setattr(translate_mod, "_sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(translate_mod, "_client", None)

    card = translate_mod.build_rich_card("drop", "капля", "A drop of water fell.")
    assert card["usage_note_ru"] == "hint"
    assert len(card["examples_ru"]) == 3
