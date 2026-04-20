"""M16.1 — static asserts on the shipped design-token CSS, the index
document's font link, and the theme-toggle helper in app.js.

The SPA's JS can't run in CI, so (like test_reader_header.py) this
module verifies the served artifacts contain the tokens, class names,
and identifiers M16.1 guarantees. Later UI tasks (M9.3 settings sheet,
M17.x, M18.x) depend on these exact names — if they disappear, fail
early rather than at runtime in the browser.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_style_css_palette_tokens(client: TestClient) -> None:
    """Both light (`:root`) and dark (`.dark`) blocks must ship the
    canonical palette vars the rest of the stylesheet reads."""
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    css = resp.text
    assert ":root" in css
    assert ".dark" in css
    for token in ("--bg", "--ink", "--accent", "--line", "--bg-2", "--soft"):
        assert token in css, f"missing palette token {token!r}"


def test_style_css_button_primitives(client: TestClient) -> None:
    """`.btn` + its primary/accent/ghost variants are the shared
    foundation for every CTA in the app."""
    css = client.get("/static/style.css").text
    for sel in (".btn", ".btn.primary", ".btn.accent", ".btn.ghost"):
        assert sel in css, f"missing button selector {sel!r}"


def test_style_css_chip_primitive(client: TestClient) -> None:
    """Chips are used by upcoming settings sheets (M9.3+); ensure the
    base + `.on` state are defined."""
    css = client.get("/static/style.css").text
    assert ".chip" in css
    assert ".chip.on" in css


def test_style_css_pbar_primitive(client: TestClient) -> None:
    """Generic `.pbar` coexists with the reader-specific
    `.progress-fill`; keep both shipping."""
    css = client.get("/static/style.css").text
    assert ".pbar" in css


def test_style_css_reduced_motion(client: TestClient) -> None:
    """Accessibility guard: the stylesheet must honor the user's
    reduced-motion preference."""
    css = client.get("/static/style.css").text
    assert "prefers-reduced-motion" in css


def test_index_html_fonts(client: TestClient) -> None:
    """The Google Fonts `<link>` must request both Geist and Instrument
    Serif in a single stylesheet so CSP (M14.2) stays unchanged."""
    html = client.get("/static/index.html").text
    assert "fonts.googleapis.com" in html
    assert "Geist" in html
    assert "Instrument+Serif" in html


def test_app_js_theme_api(client: TestClient) -> None:
    """`app.js` must expose the named theme API so the settings sheet
    and tests can drive theming without reimplementing the handshake."""
    js = client.get("/static/app.js").text
    assert "THEME_KEY" in js
    assert "en-reader.theme" in js
    assert "function setTheme" in js
    assert "function currentTheme" in js
