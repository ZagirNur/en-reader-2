"""Smoke tests for the FastAPI skeleton + the M8.2 content endpoint.

Seeds ``tests/fixtures/golden/01-simple.txt`` into the per-test SQLite DB
(autouse ``tmp_db`` fixture in ``conftest.py``) and exercises the routes
via ``fastapi.testclient.TestClient``. M8.1 dropped the static
``demo.json`` handoff and M8.2 introduced
``GET /api/books/{id}/content`` as the paginated reader feed. M11.3
attached auth to every ``/api/*`` route, so tests here reuse the shared
``client`` fixture + ``seed_main(..., email=FIXTURE_EMAIL)`` pairing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/01-simple.txt"


@pytest.fixture()
def seeded_client(client: TestClient) -> TestClient:
    seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    return client


def test_api_content_returns_valid_payload(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/api/books/1/content?offset=0&limit=20")
    assert resp.status_code == 200
    body = resp.json()

    assert body["book_id"] == 1
    assert isinstance(body["total_pages"], int)
    assert body["total_pages"] > 0
    assert isinstance(body["pages"], list)
    assert len(body["pages"]) > 0
    assert len(body["pages"]) <= body["total_pages"]


def test_root_returns_html_stub(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_content_pages_have_required_keys(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/api/books/1/content?offset=0&limit=20")
    assert resp.status_code == 200
    pages = resp.json()["pages"]

    required = {"page_index", "text", "tokens", "units"}
    for page in pages:
        assert required.issubset(page.keys()), f"missing keys: {required - page.keys()}"


def test_api_content_404_when_book_missing(client: TestClient) -> None:
    # No seeding in this test — the autouse tmp_db gives a fresh empty DB,
    # and the shared ``client`` fixture already carries an authenticated
    # session so we exercise the 404 path (not the 401 guard).
    resp = client.get("/api/books/1/content")
    assert resp.status_code == 404
