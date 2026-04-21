"""Tests for M14.2: security headers + Origin-check CSRF guard.

Two middlewares wired in :mod:`en_reader.app`:

* :class:`SecurityHeadersMiddleware` stamps CSP / XFO / XCTO /
  Referrer-Policy / Permissions-Policy on **every** response.
* :class:`OriginCheckMiddleware` rejects non-safe-method requests whose
  ``Origin`` (or ``Referer`` as fallback) is set but doesn't match the
  request's own ``base_url``. Missing both headers is allowed so
  ``sendBeacon`` / curl-without-Origin keep working.

The :func:`tests.conftest.client` fixture already signs up a fresh user
and hands back a cookie-preserving :class:`TestClient`, which is what we
need to hit authed POSTs (``/api/translate``). Unauthenticated cases
spin up a bare ``TestClient(app)`` directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app


def _assert_security_headers(headers) -> None:
    """Common header-shape check for both root and API responses."""
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    # M18.1: frame-ancestors must keep us out of hostile embeds but allow
    # the Telegram web clients so the Mini App iframe renders.
    assert "frame-ancestors 'self' https://web.telegram.org https://telegram.org" in csp
    # ``unsafe-inline`` is allowed on ``style-src`` only (M17.3): our SPA
    # sets ``element.style`` attributes from JavaScript, and CSP3 falls
    # back from ``style-src-attr`` to ``style-src`` for those. It must
    # NOT appear on ``script-src`` — that would defeat the whole point.
    assert "script-src 'self'" in csp
    # Narrow the assertion: unsafe-inline appears only within the
    # style-src directive.
    for directive in csp.split(";"):
        d = directive.strip()
        if d.startswith("style-src"):
            continue
        assert "unsafe-inline" not in d, f"unsafe-inline leaked into {d!r}"
    assert headers["X-Content-Type-Options"] == "nosniff"
    # M18.1: X-Frame-Options is dropped — it has no multi-origin mode and
    # would override the more permissive frame-ancestors in some browsers.
    assert "X-Frame-Options" not in headers
    assert headers["Referrer-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"]
    assert "microphone=()" in headers["Permissions-Policy"]
    assert "geolocation=()" in headers["Permissions-Policy"]


def test_security_headers_on_root() -> None:
    """GET / serves index.html with the full security-header suite."""
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    _assert_security_headers(r.headers)


def test_security_headers_on_api(client: TestClient) -> None:
    """API JSON responses carry the same headers as the SPA shell."""
    r = client.get("/api/books")
    assert r.status_code == 200
    _assert_security_headers(r.headers)


def test_csp_has_frame_ancestors_telegram() -> None:
    """Belt-and-suspenders: confirm the ``frame-ancestors`` directive.

    M18.1: we allow Telegram web clients to embed us so the Mini App
    iframe renders in Telegram Web/Desktop, but every other origin is
    still blocked by the 'self' anchor + the two explicit hosts.
    """
    c = TestClient(app)
    r = c.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self' https://web.telegram.org https://telegram.org" in csp


def test_origin_check_post_cross_origin_403(client: TestClient) -> None:
    """POST with a foreign Origin is rejected before reaching the route."""
    r = client.post(
        "/api/translate",
        json={"unit_text": "x", "sentence": "x", "lemma": "x"},
        headers={"Origin": "http://evil.com"},
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "forbidden origin"}


def test_origin_check_post_matching_origin_passes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST whose Origin matches ``base_url`` falls through to the handler.

    We stub ``translate_one`` so the test doesn't need a real Gemini key
    and so the assertion can pin a deterministic 200 body.
    """
    monkeypatch.setattr(
        "en_reader.app.translate_one",
        lambda *_a, **_k: ("ок", "llm"),
    )
    r = client.post(
        "/api/translate",
        json={"unit_text": "x", "sentence": "x", "lemma": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ru": "ок", "source": "llm"}


def test_origin_check_absent_origin_passes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Origin and no Referer → middleware lets the request through.

    ``sendBeacon`` in some browsers and curl without ``-H Origin`` both
    land here; they shouldn't be blanket-blocked.
    """
    monkeypatch.setattr(
        "en_reader.app.translate_one",
        lambda *_a, **_k: ("ок", "llm"),
    )
    # TestClient only sets Origin/Referer if the caller does — so
    # passing no ``headers`` kwarg gives us the "neither present" case.
    r = client.post(
        "/api/translate",
        json={"unit_text": "x", "sentence": "x", "lemma": "x"},
    )
    assert r.status_code == 200, r.text


def test_origin_check_referer_fallback_blocks(client: TestClient) -> None:
    """If Origin is absent but Referer is foreign, we still reject.

    Covers the branch in the middleware that falls back to ``Referer``
    when ``Origin`` is missing.
    """
    r = client.post(
        "/api/translate",
        json={"unit_text": "x", "sentence": "x", "lemma": "x"},
        headers={"Referer": "http://evil.com/x"},
    )
    assert r.status_code == 403


def test_get_is_not_origin_checked() -> None:
    """Safe methods (GET) skip the Origin check entirely.

    A bare unauthed ``TestClient`` with a foreign Origin should still
    reach ``/`` — the SPA shell is fine to serve regardless of who
    linked to us.
    """
    c = TestClient(app)
    r = c.get("/", headers={"Origin": "http://evil.com"})
    assert r.status_code == 200
    # And the response still carries the full security-header suite —
    # the Origin check being a no-op here doesn't short-circuit the
    # outer SecurityHeaders middleware.
    _assert_security_headers(r.headers)


def test_delete_cross_origin_403(client: TestClient) -> None:
    """DELETE is also a non-safe method — verify it gets the Origin check.

    Belt on top of the POST tests: the middleware keys off
    ``method not in SAFE_METHODS``, so an all-methods spot-check keeps
    a future refactor from accidentally narrowing the guard to POSTs.
    """
    r = client.delete(
        "/api/dictionary/foo",
        headers={"Origin": "http://evil.com"},
    )
    assert r.status_code == 403
