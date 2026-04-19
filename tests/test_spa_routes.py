"""Server-side plumbing tests for the M3.2 SPA skeleton.

We can't run the JS here, but we verify the catch-all serves `index.html` for
deep-linked SPA paths while leaving `/api/*` and `/static/*` 404s intact.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader.app import app

client = TestClient(app)


def test_root_serves_spa_shell() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_reader_path_served_by_catch_all() -> None:
    resp = client.get("/reader")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_deep_path_served_by_catch_all() -> None:
    resp = client.get("/some/deep/path")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_api_demo_still_404_without_demo_file() -> None:
    # demo.json is gitignored and not built here, so /api/demo must still 404
    # (not be masked by the SPA fallback).
    resp = client.get("/api/demo")
    assert resp.status_code == 404


def test_unknown_api_path_returns_404() -> None:
    resp = client.get("/api/bogus")
    assert resp.status_code == 404


def test_static_app_js_is_served() -> None:
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert "setState" in resp.text


def test_static_missing_file_returns_404() -> None:
    resp = client.get("/static/missing.js")
    assert resp.status_code == 404
