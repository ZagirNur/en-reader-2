"""Server-side assertions for the M3.3 reader render.

We can't run JS in pytest, but we can verify:
 - the static bundle ships the renderer (word spans, design tokens, Geist link),
 - /api/demo yields at least one phrasal unit on the phrasal fixture,
   so the frontend walker has real split/multi-token content to exercise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.build_demo import main as build_demo_main

_FIXTURE = "tests/fixtures/golden/02-phrasal.txt"


@pytest.fixture(scope="module")
def client() -> TestClient:
    out_path: Path = build_demo_main(_FIXTURE)
    try:
        yield TestClient(app)
    finally:
        if out_path.exists():
            out_path.unlink()


def test_app_js_emits_word_spans(client: TestClient) -> None:
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert 'class="word"' in resp.text or '"word"' in resp.text
    assert "data-unit-id" in resp.text or "unitId" in resp.text


def test_style_css_has_word_and_tokens(client: TestClient) -> None:
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert ".word.translated" in resp.text
    assert "--accent" in resp.text


def test_index_html_has_geist_font(client: TestClient) -> None:
    resp = client.get("/static/index.html")
    assert resp.status_code == 200
    assert "fonts.googleapis.com" in resp.text
    assert "Geist" in resp.text


def test_demo_has_phrasal_unit(client: TestClient) -> None:
    resp = client.get("/api/demo")
    assert resp.status_code == 200
    body = resp.json()

    kinds: set[str] = set()
    for page in body["pages"]:
        for unit in page["units"]:
            kinds.add(unit["kind"])

    assert (
        "phrasal" in kinds or "split_phrasal" in kinds
    ), f"expected a phrasal unit on 02-phrasal fixture, saw kinds={kinds}"
