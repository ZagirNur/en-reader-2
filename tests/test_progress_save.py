"""M10.4 — client-side debounced progress save (static-asset assertions).

We can't execute JS from pytest, so this suite verifies two things:

1. The required tokens and shape live in ``src/en_reader/static/app.js``:
   the new helper names, module-level state, unload hook, and — critically
   for the stale-save bug M10.4 exists to fix — ``clearTimeout`` runs
   inside ``scheduleProgressSave`` before any of its no-op early returns.

2. The server side round-trip still works end-to-end:
   POST /api/books/{id}/progress → 204 → ``storage.progress_get`` returns
   the posted values. This guards against a refactor accidentally breaking
   the endpoint that the JS now leans on harder than before.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/long.txt"
_APP_JS = Path(__file__).resolve().parent.parent / "src" / "en_reader" / "static" / "app.js"


def test_app_js_contains_m10_4_symbols() -> None:
    """Every M10.4 contract symbol must be present in the bundle."""
    js = _APP_JS.read_text(encoding="utf-8")
    expected = [
        "scheduleProgressSave",
        "computeOffset",
        "findVisiblePageSection",
        "_saveTimer",
        "_lastSaved",
        "sendBeacon",
        "beforeunload",
        "state.restoring",
    ]
    missing = [tok for tok in expected if tok not in js]
    assert not missing, f"app.js missing M10.4 symbols: {missing}"


def test_schedule_progress_save_clears_timer_before_early_return() -> None:
    """Stale-save guard: clearTimeout must run inside scheduleProgressSave.

    The M10.4 fix relies on always clearing the pending timer before the
    "value didn't change meaningfully" early return. We assert both that
    ``clearTimeout`` appears inside the function body and that it precedes
    the ``_lastSaved.pageIndex ===`` skip check.
    """
    js = _APP_JS.read_text(encoding="utf-8")

    # Grab the body of scheduleProgressSave up to the next top-level
    # function declaration. Simple but robust enough for this file.
    m = re.search(
        r"function scheduleProgressSave\s*\([^)]*\)\s*\{(.*?)\n\}\n",
        js,
        flags=re.DOTALL,
    )
    assert m, "Could not locate scheduleProgressSave body"
    body = m.group(1)

    assert "clearTimeout" in body, "clearTimeout missing inside scheduleProgressSave"

    clear_pos = body.find("clearTimeout")
    skip_pos = body.find("_lastSaved.pageIndex ===")
    assert skip_pos != -1, "Early-return identity check missing"
    assert clear_pos < skip_pos, (
        "clearTimeout must run BEFORE the _lastSaved early return — "
        "otherwise a stale timer could still fire."
    )


def test_post_progress_roundtrips_to_storage() -> None:
    """POST /progress with (8, 0.4) → 204 and storage reflects it."""
    book_id = seed_main(_FIXTURE)
    client = TestClient(app)
    resp = client.post(
        f"/api/books/{book_id}/progress",
        json={"last_page_index": 8, "last_page_offset": 0.4},
    )
    assert resp.status_code == 204
    page_idx, offset = storage.progress_get(book_id)
    assert page_idx == 8
    assert abs(offset - 0.4) < 1e-9
