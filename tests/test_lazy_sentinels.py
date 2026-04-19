"""Server-side checks for the M10.3 lazy-sentinel flow.

The observer wiring, scroll compensation, and re-entrancy guard live
entirely in ``src/en_reader/static/app.js`` — there's no pytest harness
that can execute them. These tests pin the contract from two angles:

1. **Static-file asserts** — the shipped JS/CSS still names the
   identifiers the spec calls out: ``sentinel-top``, ``sentinel-bottom``,
   ``loadAbove``, ``loadBelow``, ``IntersectionObserver``, ``rootMargin``,
   ``document.documentElement.scrollHeight`` (scroll compensation), and
   the module-level ``_loadingTop`` / ``_loadingBottom`` guards. A
   refactor that drops any of these flips the test red before shipping.
2. **Integration guard** — the reader fetches neighbors one page at a
   time via ``GET /api/books/{id}/content?offset=N&limit=1``; the endpoint
   must return exactly that page for arbitrary N so the client-side
   prepend/append path lines up. We exercise three offsets over a
   multi-page fixture.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/long.txt"


def test_app_js_contains_lazy_sentinel_markers() -> None:
    """app.js must ship the M10.3 helpers + identifiers the spec names."""
    client = TestClient(app)
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    js = resp.text
    for marker in (
        "sentinel-top",
        "sentinel-bottom",
        "loadAbove",
        "loadBelow",
        "IntersectionObserver",
        "rootMargin",
        "documentElement.scrollHeight",
        "_loadingTop",
        "_loadingBottom",
    ):
        assert marker in js, f"expected {marker!r} in app.js"


def test_style_css_contains_sentinel_rule() -> None:
    """style.css must ship the .sentinel rule (1 px height)."""
    client = TestClient(app)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert ".sentinel" in resp.text


@pytest.fixture()
def seeded_client() -> TestClient:
    seed_main(_FIXTURE)
    return TestClient(app)


def test_content_single_page_fetch_round_trip(seeded_client: TestClient) -> None:
    """Neighbor fetches use offset=N&limit=1; endpoint returns exactly page N."""
    # long.txt produces enough pages for a stable 3-offset probe.
    meta = seeded_client.get("/api/books/1/content?offset=0&limit=1").json()
    total = meta["total_pages"]
    assert total >= 3, f"fixture must yield >=3 pages (got {total})"

    for offset in (0, 1, 2):
        body = seeded_client.get(f"/api/books/1/content?offset={offset}&limit=1").json()
        assert isinstance(body["pages"], list)
        assert len(body["pages"]) == 1, (
            f"expected exactly one page for offset={offset}, " f"got {len(body['pages'])}"
        )
        assert (
            body["pages"][0]["page_index"] == offset
        ), f"offset={offset} returned page_index={body['pages'][0]['page_index']}"
        assert body["total_pages"] == total
