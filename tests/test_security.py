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
    assert "frame-ancestors 'none'" in csp
    # No ``unsafe-inline`` anywhere — CSP must stay strict.
    assert "unsafe-inline" not in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
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


def test_csp_has_frame_ancestors_none() -> None:
    """Belt-and-suspenders: confirm the ``frame-ancestors`` directive.

    Modern clickjacking protection lives in CSP; XFO is a legacy fallback.
    """
    c = TestClient(app)
    r = c.get("/")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


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
        lambda unit_text, sentence: "ок",
    )
    r = client.post(
        "/api/translate",
        json={"unit_text": "x", "sentence": "x", "lemma": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ru": "ок"}


def test_origin_check_absent_origin_passes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Origin and no Referer → middleware lets the request through.

    ``sendBeacon`` in some browsers and curl without ``-H Origin`` both
    land here; they shouldn't be blanket-blocked.
    """
    monkeypatch.setattr(
        "en_reader.app.translate_one",
        lambda unit_text, sentence: "ок",
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
