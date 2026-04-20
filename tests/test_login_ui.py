"""Static-asset checks for the M11.3 login/signup UI.

We don't execute the SPA here — these tests verify that the bundled
``app.js`` / ``style.css`` still contain the symbols the login screen
depends on (so a rename or accidental delete shows up in CI), and that
the SPA catch-all still serves the shell for the ``/login`` + ``/signup``
deep links.

The catch-all pattern in ``en_reader.app`` is the same one M3.2's
``test_spa_routes.py`` exercises — we just re-assert it for the two new
auth routes so a future regex tightening doesn't silently 404 a
legitimate auth path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader.app import app

_client = TestClient(app)


def test_app_js_contains_login_symbols() -> None:
    resp = _client.get("/static/app.js")
    assert resp.status_code == 200
    body = resp.text
    for token in (
        "renderLogin",
        "authMode",
        "authError",
        "/auth/signup",
        "/auth/login",
        "/auth/logout",
        "auth-switch",
        "logout-btn",
    ):
        assert token in body, f"missing token in app.js: {token!r}"


def test_style_css_contains_login_selectors() -> None:
    resp = _client.get("/static/style.css")
    assert resp.status_code == 200
    body = resp.text
    for selector in (".auth-view", ".logout-btn", ".auth-switch"):
        assert selector in body, f"missing selector in style.css: {selector!r}"


def test_login_route_served_by_catch_all() -> None:
    resp = _client.get("/login")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_signup_route_served_by_catch_all() -> None:
    resp = _client.get("/signup")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text
