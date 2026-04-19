"""Smoke tests for the M3.1 FastAPI skeleton + `/api/demo` endpoint.

Seeds ``tests/fixtures/golden/01-simple.txt`` into the per-test SQLite DB
(autouse ``tmp_db`` fixture in ``conftest.py``) and exercises the routes
via ``fastapi.testclient.TestClient``. M8.1 dropped the static
``demo.json`` handoff — ``/api/demo`` now reads from the books/pages
tables.
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


def test_api_demo_returns_valid_payload(client: TestClient) -> None:
    resp = client.get("/api/demo")
    assert resp.status_code == 200
    body = resp.json()

    assert isinstance(body["total_pages"], int)
    assert body["total_pages"] > 0
    assert isinstance(body["pages"], list)
    assert len(body["pages"]) > 0
    assert body["total_pages"] == len(body["pages"])


def test_root_returns_html_stub(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_demo_pages_have_required_keys(client: TestClient) -> None:
    resp = client.get("/api/demo")
    assert resp.status_code == 200
    pages = resp.json()["pages"]

    required = {"page_index", "text", "tokens", "units"}
    for page in pages:
        assert required.issubset(page.keys()), f"missing keys: {required - page.keys()}"


def test_api_demo_404_when_no_books() -> None:
    # No seeding in this test — the autouse tmp_db gives a fresh empty DB.
    c = TestClient(app)
    resp = c.get("/api/demo")
    assert resp.status_code == 404
    assert "seed.py" in resp.json()["detail"]
