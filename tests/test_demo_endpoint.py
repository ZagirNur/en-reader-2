"""Smoke tests for the M3.1 FastAPI skeleton + `/api/demo` endpoint.

Builds `src/en_reader/static/demo.json` once per module from
`tests/fixtures/golden/01-simple.txt`, exercises the routes via
`fastapi.testclient.TestClient`, and removes the generated file on teardown
so the working tree stays clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from scripts.build_demo import main as build_demo_main

_FIXTURE = "tests/fixtures/golden/01-simple.txt"


@pytest.fixture(scope="module")
def client() -> TestClient:
    out_path: Path = build_demo_main(_FIXTURE)
    try:
        yield TestClient(app)
    finally:
        if out_path.exists():
            out_path.unlink()


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
