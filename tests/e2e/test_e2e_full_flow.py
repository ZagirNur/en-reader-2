"""End-to-end happy path: signup → upload → reader → click → inline RU.

Exercises the full frontend wiring that unit/integration tests can't
cover: the auth form mounted at ``/login``, the hidden file input
fired by ``.add-card`` clicks, reader rendering into ``.page-body``,
and the word-tap handler that mutates a ``.word`` span into a
``.translated`` one with the Russian text swapped in-place.

Gemini is stubbed via ``E2E_MOCK_LLM=1`` (see
:mod:`tests.e2e.conftest`), so the assertion checks that the clicked
span's text starts with ``RU:``.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

FIXTURE_TXT = Path(__file__).resolve().parents[1] / "fixtures" / "parsers" / "sample_utf8.txt"


def test_e2e_full_flow(page: Page, live_server: str) -> None:
    # --- signup via the /login screen --------------------------------
    page.goto(f"{live_server}/login")
    # Default mode is "login"; flip to signup via the toggle button.
    page.click("#auth-switch")
    page.fill("input[name=email]", "e2e-full@test.com")
    page.fill("input[name=password]", "pw12345678")
    page.click("#auth-form button[type=submit]")
    # Library view after successful signup.
    expect(page).to_have_url(f"{live_server}/", timeout=10_000)

    # --- upload a tiny fixture via the hidden file chooser ----------
    with page.expect_file_chooser() as fc_info:
        page.click(".add-card")
    fc_info.value.set_files(str(FIXTURE_TXT))

    # Upload handler navigates to /books/<id> and the reader renders
    # .page-body once content is fetched.
    page.wait_for_selector(".page-body", timeout=15_000)

    # --- tap a word, expect inline RU translation -------------------
    first_word = page.locator(".word").first
    first_word.wait_for(state="visible", timeout=5_000)
    # Span text before the click; we only assert the post-click text
    # starts with "RU:" because the stub returns f"RU:{unit_text}".
    first_word.click()

    # The handler removes .loading and adds .translated once the
    # /api/translate POST resolves — wait for the class to land
    # rather than polling on text to avoid racing the swap.
    expect(first_word).to_have_class(re.compile(r"\btranslated\b"), timeout=10_000)
    text = first_word.inner_text()
    assert text.startswith("RU:"), f"expected RU:-prefixed text, got {text!r}"
