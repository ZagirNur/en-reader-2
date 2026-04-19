"""Tests for `en_reader.translate` and the `POST /api/translate` endpoint.

All Gemini calls are stubbed via ``monkeypatch`` — no network access.
``_sleep`` is replaced with a no-op so retry paths don't add wall time.
``_client`` is reset before each test so lazy-init state from a previous
test cannot leak in.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable

import pytest
from fastapi.testclient import TestClient

from en_reader import translate as translate_mod
from en_reader.app import app
from en_reader.translate import TranslateError, translate_one


class _FakeClient:
    """Minimal stand-in for ``genai.Client`` driven by a scripted reply list."""

    def __init__(self, replies: Iterable[str]) -> None:
        self._replies = list(replies)
        self.calls = 0
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, *, model, contents, config):  # noqa: ARG002
        idx = min(self.calls, len(self._replies) - 1)
        reply = self._replies[idx]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with no lazy client and an instant `_sleep`."""
    monkeypatch.setattr(translate_mod, "_client", None)
    monkeypatch.setattr(translate_mod, "_sleep", lambda _s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, replies: Iterable[str]) -> _FakeClient:
    fake = _FakeClient(replies)
    monkeypatch.setattr(translate_mod, "_get_client", lambda: fake)
    return fake


# ---------- translate_one unit tests ----------


def test_translate_one_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_client(monkeypatch, ["зловещий"])
    out = translate_one("ominous", "She whispered an ominous warning.")
    assert out == "зловещий"
    assert fake.calls == 1


def test_translate_one_retry_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_client(monkeypatch, ["", "зловещий"])
    out = translate_one("ominous", "She whispered an ominous warning.")
    assert out == "зловещий"
    assert fake.calls == 2


def test_translate_one_all_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_client(monkeypatch, ["   ", "   ", "   "])
    with pytest.raises(TranslateError):
        translate_one("ominous", "She whispered an ominous warning.")
    assert fake.calls == 3


def test_translate_one_rejects_long_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    long_reply = "a" * 70
    fake = _install_fake_client(monkeypatch, [long_reply, long_reply, long_reply])
    with pytest.raises(TranslateError):
        translate_one("ominous", "She whispered an ominous warning.")
    assert fake.calls == 3


def test_translate_one_rejects_html_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_client(monkeypatch, ["<b>зловещий</b>", "зловещий"])
    out = translate_one("ominous", "She whispered an ominous warning.")
    assert out == "зловещий"
    assert fake.calls == 2


def test_translate_one_rejects_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_client(monkeypatch, ["зловещий\n- sinister", "зловещий"])
    out = translate_one("ominous", "She whispered an ominous warning.")
    assert out == "зловещий"
    assert fake.calls == 2


def test_translate_one_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(translate_mod, "_client", None)
    # Don't install a fake _get_client — we want the real one to see the gap.
    with pytest.raises(TranslateError):
        translate_one("ominous", "She whispered an ominous warning.")


# ---------- endpoint tests ----------


def test_translate_endpoint_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, ["зловещий"])
    client = TestClient(app)
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": "She whispered an ominous warning.",
            "lemma": "ominous",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ru": "зловещий"}


def test_translate_endpoint_502_on_TranslateError(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(unit_text: str, sentence: str) -> str:
        raise TranslateError("forced")

    # Patch the symbol imported into app.py, not just the translate module.
    monkeypatch.setattr("en_reader.app.translate_one", _boom)
    client = TestClient(app)
    resp = client.post(
        "/api/translate",
        json={"unit_text": "ominous", "sentence": "She whispered.", "lemma": "ominous"},
    )
    assert resp.status_code == 502
    assert "forced" in resp.json()["detail"]


def test_translate_endpoint_422_on_empty_unit() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/translate",
        json={"unit_text": "", "sentence": "She whispered.", "lemma": "ominous"},
    )
    assert resp.status_code == 422
