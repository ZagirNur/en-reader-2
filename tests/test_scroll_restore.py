"""Server-side checks for the M10.2 scroll-restore flow.

The scroll-restore sequence itself (ResizeObserver, document.fonts.ready,
sequenced `scrollToOffset` passes) is pure JS and lives entirely in
``src/en_reader/static/app.js``; we can't execute it under pytest. These
tests instead pin the contract in two complementary ways:

1. **Static-file asserts**: the shipped ``app.js`` contains the identifiers
   the spec names — ``scrollToOffset``, ``restoreScroll``, the
   ``document.fonts.ready`` await, the ``ResizeObserver`` subscription,
   and the new ``state.restoring`` / ``state.targetPageIndex`` /
   ``state.targetOffset`` fields the M10.2 state machine depends on. A
   future refactor that drops any of these will flag here instead of
   shipping a silently-broken restore.
2. **Integration guard**: a POST to ``/api/books/{id}/progress`` is
   round-tripped via ``GET /content?offset=0&limit=1`` — the shape the
   M10.2 first-phase fetch relies on — so ``last_page_offset`` survives
   the fetch with the same precision the JS consumes.

The single-page case (book with 1 page → ``last_page_index`` stays 0, no
second fetch) is a JS-only branch and is not testable here; the JS
guards it directly (``if (lastIdx > 0)``).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_app_js_contains_scroll_restore_markers() -> None:
    """app.js must ship the M10.2 helpers + state fields the spec names."""
    client = TestClient(app)
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    js = resp.text
    for marker in (
        "restoreScroll",
        "scrollToOffset",
        "document.fonts.ready",
        "ResizeObserver",
        "state.restoring",
        "state.targetPageIndex",
        "state.targetOffset",
    ):
        assert marker in js, f"expected {marker!r} in app.js"


def test_content_offset_zero_returns_saved_progress() -> None:
    """First-phase fetch (offset=0&limit=1) must surface last_page_offset."""
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    post = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 0, "last_page_offset": 0.42},
    )
    assert post.status_code == 204

    body = client.get(
        f"/api/books/{book_id}/content?offset=0&limit=1",
    ).json()
    assert body["last_page_index"] == 0
    assert body["last_page_offset"] == 0.42
    # Same call also returns total_pages + page 0, which M10.2 reuses when
    # the user was last on page 0 (no second fetch required).
    assert "total_pages" in body
    assert isinstance(body["pages"], list) and len(body["pages"]) == 1
    assert body["pages"][0]["page_index"] == 0
