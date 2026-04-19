"""Server-side checks for the M9.3 sticky reader header.

The SPA's JS can't run in CI, so these tests verify that the shipped
static assets contain the key class names and helper identifiers the
spec mandates, and that the content API the reader depends on is still
reachable after a seed (regression guard for the new header flow).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_reader_header_js_markers() -> None:
    """app.js must ship the M9.3 header markup hooks and scroll helper."""
    client = TestClient(app)
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    js = resp.text
    for marker in (
        "reader-header",
        "back-btn",
        "progress-fill",
        "findVisiblePageIndex",
    ):
        assert marker in js, f"expected {marker!r} in app.js"


def test_reader_header_css_markers() -> None:
    """style.css must ship the M9.3 header + auto-hide rules."""
    client = TestClient(app)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    css = resp.text
    for marker in (".reader-header", ".reader-header.hidden", ".progress-fill"):
        assert marker in css, f"expected {marker!r} in style.css"


def test_content_api_still_works_after_seed() -> None:
    """Regression guard: the reader still loads page content as before."""
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    resp = client.get(f"/api/books/{book_id}/content?offset=0&limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["book_id"] == book_id
    assert "pages" in body
    assert "total_pages" in body
