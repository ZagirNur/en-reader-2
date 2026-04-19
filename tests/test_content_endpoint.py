"""Smoke tests for the FastAPI skeleton + the M8.2 content endpoint.

Seeds ``tests/fixtures/golden/01-simple.txt`` into the per-test SQLite DB
(autouse ``tmp_db`` fixture in ``conftest.py``) and exercises the routes
via ``fastapi.testclient.TestClient``. M8.1 dropped the static
``demo.json`` handoff and M8.2 introduced
``GET /api/books/{id}/content`` as the paginated reader feed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/01-simple.txt"


@pytest.fixture()
def client() -> TestClient:
    seed_main(_FIXTURE)
    return TestClient(app)


def test_api_content_returns_valid_payload(client: TestClient) -> None:
    resp = client.get("/api/books/1/content?offset=0&limit=20")
    assert resp.status_code == 200
    body = resp.json()

    assert body["book_id"] == 1
    assert isinstance(body["total_pages"], int)
    assert body["total_pages"] > 0
    assert isinstance(body["pages"], list)
    assert len(body["pages"]) > 0
    assert len(body["pages"]) <= body["total_pages"]


def test_root_returns_html_stub(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_content_pages_have_required_keys(client: TestClient) -> None:
    resp = client.get("/api/books/1/content?offset=0&limit=20")
    assert resp.status_code == 200
    pages = resp.json()["pages"]

    required = {"page_index", "text", "tokens", "units"}
    for page in pages:
        assert required.issubset(page.keys()), f"missing keys: {required - page.keys()}"


def test_api_content_404_when_book_missing() -> None:
    # No seeding in this test — the autouse tmp_db gives a fresh empty DB.
    c = TestClient(app)
    resp = c.get("/api/books/1/content")
    assert resp.status_code == 404
