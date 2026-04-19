"""Server-side assertions for the M3.3 reader render.

We can't run JS in pytest, but we can verify:
 - the static bundle ships the renderer (word spans, design tokens, Geist link),
 - /api/books/{id}/content yields at least one phrasal unit on the phrasal
   fixture, so the frontend walker has real split/multi-token content to
   exercise.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/02-phrasal.txt"


@pytest.fixture()
def seeded_client(client: TestClient) -> TestClient:
    seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    return client


def test_app_js_emits_word_spans(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/static/app.js")
    assert resp.status_code == 200
    assert 'class="word"' in resp.text or '"word"' in resp.text
    assert "data-unit-id" in resp.text or "unitId" in resp.text


def test_style_css_has_word_and_tokens(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/static/style.css")
    assert resp.status_code == 200
    assert ".word.translated" in resp.text
    assert "--accent" in resp.text


def test_index_html_has_geist_font(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/static/index.html")
    assert resp.status_code == 200
    assert "fonts.googleapis.com" in resp.text
    assert "Geist" in resp.text


def test_demo_has_phrasal_unit(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/api/books/1/content?offset=0&limit=20")
    assert resp.status_code == 200
    body = resp.json()

    kinds: set[str] = set()
    for page in body["pages"]:
        for unit in page["units"]:
            kinds.add(unit["kind"])

    assert (
        "phrasal" in kinds or "split_phrasal" in kinds
    ), f"expected a phrasal unit on 02-phrasal fixture, saw kinds={kinds}"


def test_app_js_preserves_zero_pair_id(seeded_client: TestClient) -> None:
    # Regression: `if (unit.pair_id)` drops pair_id=0 (the first pair emitted
    # by the chunker). The fix must be a nullish check so every split-PV half
    # gets data-pair-id.
    resp = seeded_client.get("/static/app.js")
    assert resp.status_code == 200
    assert "unit.pair_id != null" in resp.text
    assert "if (unit.pair_id) " not in resp.text


def test_render_error_no_html_interpolation(seeded_client: TestClient) -> None:
    # renderError must not interpolate state.error via innerHTML — it was the
    # only path that took an unsanitized string (e.g. `Unknown route: ${path}`)
    # straight into markup.
    resp = seeded_client.get("/static/app.js")
    text = resp.text
    # Crude check: the renderError function body should use textContent for
    # the message box rather than innerHTML with a template expression of msg.
    assert 'class="error">${msg}' not in text
    assert 'class="error">${state.error' not in text
