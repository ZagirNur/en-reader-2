"""Tests for the user dictionary endpoints (M5.1, re-pointed at SQLite in M6.1).

Covers:
* `POST /api/translate` populates the server-side dictionary.
* `GET /api/dictionary` returns current entries.
* `DELETE /api/dictionary/{lemma}` is idempotent.
* Lemma keys are normalized to lowercase.
* `GET /api/books/{id}/content` is enriched with `user_dict` and per-page
  `auto_unit_ids`.

All LLM calls are monkeypatched — no network hits. The ``tmp_db``
autouse fixture in ``conftest.py`` gives each test its own SQLite file,
and the ``client`` fixture signs up the fixture user that every
seed/dict call attaches data to.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/02-phrasal.txt"


@pytest.fixture()
def fake_translate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out `translate_one` so `/api/translate` returns a fixed string."""

    def _fake(*_args, **_kwargs) -> str:  # noqa: ARG001
        return "зловещий"

    monkeypatch.setattr("en_reader.app.translate_one", _fake)


@pytest.fixture()
def demo_client(client: TestClient) -> TestClient:
    """Authenticated client with the phrasal fixture seeded under the fixture user.

    Function-scoped so it composes with the autouse ``tmp_db`` fixture,
    which is itself function-scoped.
    """
    seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    return client


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None, "client fixture must have created the user"
    return user.id


# ---------- translate -> dictionary wiring ----------


def test_translate_populates_dictionary(client: TestClient, fake_translate: None) -> None:
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

    got = client.get("/api/dictionary")
    assert got.status_code == 200
    assert got.json() == {"ominous": "зловещий"}


def test_missing_lemma_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/translate",
        json={"unit_text": "ominous", "sentence": "She whispered."},
    )
    assert resp.status_code == 422


def test_lemma_lowercased(client: TestClient, fake_translate: None) -> None:
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "Ominous",
            "sentence": "Ominous clouds gathered.",
            "lemma": "Ominous",
        },
    )
    assert resp.status_code == 200
    assert client.get("/api/dictionary").json() == {"ominous": "зловещий"}


# ---------- DELETE ----------


def test_delete_dictionary(client: TestClient) -> None:
    storage.dict_add("ominous", "зловещий", user_id=_fixture_user_id())
    resp = client.delete("/api/dictionary/ominous")
    assert resp.status_code == 204
    assert client.get("/api/dictionary").json() == {}


def test_delete_is_idempotent(client: TestClient) -> None:
    # Nonexistent key still returns 204.
    resp = client.delete("/api/dictionary/does-not-exist")
    assert resp.status_code == 204


def test_delete_is_case_insensitive(client: TestClient) -> None:
    storage.dict_add("ominous", "зловещий", user_id=_fixture_user_id())
    resp = client.delete("/api/dictionary/Ominous")
    assert resp.status_code == 204
    assert client.get("/api/dictionary").json() == {}


# ---------- content enrichment ----------


def test_content_includes_user_dict_and_auto_unit_ids(demo_client: TestClient) -> None:
    # Pick a lemma that actually appears on some page of the phrasal fixture.
    base = demo_client.get("/api/books/1/content?offset=0&limit=20").json()
    assert "user_dict" in base and base["user_dict"] == {}
    for page in base["pages"]:
        assert page.get("auto_unit_ids") == []

    target_lemma: str | None = None
    target_unit_id: int | None = None
    target_page_index: int | None = None
    for page in base["pages"]:
        for unit in page.get("units", []):
            lemma = (unit.get("lemma") or "").strip()
            if lemma:
                target_lemma = lemma.lower()
                target_unit_id = unit["id"]
                target_page_index = page["page_index"]
                break
        if target_lemma is not None:
            break
    assert target_lemma is not None, "no units with a lemma in the phrasal fixture"

    storage.dict_add(target_lemma, "тест-перевод", user_id=_fixture_user_id())

    body = demo_client.get("/api/books/1/content?offset=0&limit=20").json()
    assert body["user_dict"] == {target_lemma: "тест-перевод"}

    matched_page = next(p for p in body["pages"] if p["page_index"] == target_page_index)
    assert target_unit_id in matched_page["auto_unit_ids"]

    # Pages that do not contain a matching unit must have an empty list,
    # not a missing key.
    for page in body["pages"]:
        assert "auto_unit_ids" in page
        for unit_id in page["auto_unit_ids"]:
            unit = next(u for u in page["units"] if u["id"] == unit_id)
            assert (unit["lemma"] or "").lower() == target_lemma
