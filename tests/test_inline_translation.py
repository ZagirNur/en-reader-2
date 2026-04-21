"""Server-side smoke tests for M4.2 (inline translation UI).

We can't run JS in pytest, so we verify:
 - the static bundle ships the new function names,
 - XSS discipline — ru-derived values never flow through innerHTML,
 - the style bundle contains the new CSS classes,
 - the demo fixture still yields a split_phrasal with a shared pair_id,
 - POST /api/translate keeps working with a monkeypatched `translate_one`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/02-phrasal.txt"

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "en_reader" / "static"


@pytest.fixture()
def seeded_client(client: TestClient) -> TestClient:
    seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    return client


# ---------- static bundle checks ----------


def test_app_js_has_new_function_names() -> None:
    text = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for name in (
        "apiPost",
        "onWordTap",
        "translateAndReplace",
        "revertTranslation",
        "openWordSheet",
        "toast",
        "withScrollAnchor",
    ):
        assert name in text, f"expected function name {name!r} in app.js"


def test_app_js_no_innerhtml_on_ru() -> None:
    """Russian strings from /api/translate must never be set via innerHTML."""
    text = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # No line should funnel `ru` (or `ruText`) through innerHTML.
    bad = re.compile(r"\binnerHTML\b.*\bru(?:Text)?\b")
    for line in text.splitlines():
        assert not bad.search(line), f"innerHTML over ru-derived value: {line!r}"
    # And no innerHTML use on sentence-derived strings either.
    bad2 = re.compile(r"\binnerHTML\b.*\bsentence(?:Text)?\b")
    for line in text.splitlines():
        assert not bad2.search(line), f"innerHTML over sentence value: {line!r}"


def test_style_css_has_sheet_and_toast_rules() -> None:
    text = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    for needle in (".toast", ".sheet", ".word.loading", ".sheet-headword"):
        assert needle in text, f"expected CSS rule {needle!r} in style.css"


# ---------- demo + endpoint sanity ----------


def test_demo_split_phrasal_has_shared_pair_id(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/api/books/1/content?offset=0&limit=20")
    assert resp.status_code == 200
    body = resp.json()

    found = False
    for page in body["pages"]:
        by_pair: dict[int, list[dict]] = {}
        for unit in page["units"]:
            if unit.get("pair_id") is None:
                continue
            by_pair.setdefault(unit["pair_id"], []).append(unit)
        for pair_id, halves in by_pair.items():
            if len(halves) == 2 and all(u["kind"] == "split_phrasal" for u in halves):
                for u in halves:
                    assert u["pair_id"] == pair_id
                    assert u["pair_id"] is not None
                found = True
                break
        if found:
            break
    assert found, "expected at least one split_phrasal pair with a shared non-null pair_id"


def test_translate_endpoint_success_for_m4_2(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirror the pattern from tests/test_translate.py — patch the symbol
    # imported into app.py so the endpoint returns cleanly without Gemini.
    def _fake(*_args, **_kwargs) -> str:
        return ("зловещий", "llm")

    monkeypatch.setattr("en_reader.app.translate_one", _fake)
    resp = client.post(
        "/api/translate",
        json={
            "unit_text": "ominous",
            "sentence": "She whispered an ominous warning.",
            "lemma": "ominous",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ru": "зловещий", "source": "llm"}
