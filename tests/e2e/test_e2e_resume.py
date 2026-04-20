"""End-to-end resume flow: scroll → reload → land back at same spot.

M10.5 tracks the last-read book + scroll offset on the server. The
integration suite covers the storage round-trip; this test covers the
full browser wiring: the reader's scroll-debounce timer POSTs a save,
bootstrap on ``/`` consults ``/api/me/current-book``, and the reader
restores ``window.scrollY`` after re-rendering the page it was on.

Two quirks the tests have to accommodate:

1. The SPA uses ``history.pushState`` for in-app navigation, which
   updates ``location.pathname`` but does NOT fire a frame navigation,
   so Playwright's ``page.url`` still reads the last hard-loaded URL.
   We inspect ``location.pathname`` via ``page.evaluate`` instead.

2. ``renderReader`` sets ``state.restoring = true`` for a 2s window on
   every mount, during which ``scheduleProgressSave`` is a no-op. We
   wait out that window before scrolling so the first save actually
   lands.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

LONG_TXT = Path(__file__).resolve().parents[1] / "fixtures" / "long.txt"


def test_e2e_resume(page: Page, live_server: str) -> None:
    # Small viewport so our fixture (first page ~600 px tall) overflows
    # and vertical scrolling is actually possible.
    page.set_viewport_size({"width": 400, "height": 400})

    # --- signup ------------------------------------------------------
    page.goto(f"{live_server}/login")
    page.click("#auth-switch")
    page.fill("input[name=email]", "e2e-resume@test.com")
    page.fill("input[name=password]", "pw12345678")
    page.click("#auth-form button[type=submit]")
    expect(page).to_have_url(f"{live_server}/", timeout=10_000)

    # --- upload the multi-page fixture -------------------------------
    with page.expect_file_chooser() as fc_info:
        page.click(".add-card")
    fc_info.value.set_files(str(LONG_TXT))

    # Upload handler navigates into /books/<id>; capture the id via
    # location.pathname (see module docstring for why page.url is
    # unreliable for pushState navigations).
    page.wait_for_selector(".page-body", timeout=20_000)
    pathname = page.evaluate("() => location.pathname")
    m = re.match(r"^/books/(\d+)$", pathname)
    assert m, f"expected /books/<id> after upload, got {pathname!r}"
    book_path = pathname

    # Wait out the 2s restoring window before scrolling — otherwise
    # scheduleProgressSave short-circuits and no POST ever fires.
    page.wait_for_timeout(2_500)

    # --- scroll + wait for the debounced save POST to land ----------
    with page.expect_response(
        lambda r: "/progress" in r.url and r.request.method == "POST" and r.ok,
        timeout=10_000,
    ):
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight / 3)")

    # Sanity check: we actually moved off the top before the reload.
    scrolled_y = page.evaluate("() => window.scrollY")
    assert scrolled_y > 0, f"test precondition: scroll did not move (scrollY={scrolled_y})"

    # --- re-open the library; bootstrap should redirect back --------
    page.goto(f"{live_server}/")

    # Bootstrap: /auth/me → /api/me/current-book → navigate() back into
    # the book. We poll location.pathname because the SPA navigation is
    # pushState-based.
    end_by_ms = 10_000
    elapsed = 0
    step = 100
    while elapsed < end_by_ms:
        if page.evaluate("() => location.pathname") == book_path:
            break
        page.wait_for_timeout(step)
        elapsed += step
    assert (
        page.evaluate("() => location.pathname") == book_path
    ), f"expected bootstrap to land on {book_path!r}"

    page.wait_for_selector(".page-body", timeout=10_000)

    # Give the reader a beat to restore scroll after content mounts.
    # Note: the production CSP forbids 'unsafe-eval', so we can't use
    # page.wait_for_function() (it stringifies + evals in-page). Poll
    # via page.evaluate() which runs as a proper function call.
    scroll_y = 0
    deadline_ms = 5_000
    waited_ms = 0
    step_ms = 100
    while waited_ms < deadline_ms:
        scroll_y = page.evaluate("() => window.scrollY")
        if scroll_y > 0:
            break
        page.wait_for_timeout(step_ms)
        waited_ms += step_ms
    assert scroll_y > 0, f"expected resume restore, got scrollY={scroll_y}"
