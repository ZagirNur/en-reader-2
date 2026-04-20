"""Tests for the M8.2 content API: ``GET /api/books/{id}/content``.

Covers the response shape, pagination (``offset`` / ``limit``), the hard
limit cap at 20, the 404 path for missing books, and the
``auto_unit_ids`` enrichment tied to the user dictionary.

All tests rely on the autouse ``tmp_db`` fixture in ``conftest.py`` for a
fresh per-test SQLite file, plus the shared ``client`` fixture (M11.3)
which signs up the fixture user that ``scripts.seed.main(..., email=...)``
attaches the seeded books to.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

# Small fixture — 05-complex has 2 pages with real tokens; used for shape +
# 404 + cover assertions. The phrasal fixture is the one with real Units
# (phrasal verbs), so we use it for the auto_unit_ids test.
_SMALL_FIXTURE = "tests/fixtures/golden/05-complex.txt"
_UNITS_FIXTURE = "tests/fixtures/golden/02-phrasal.txt"
# Multi-page fixture — 36 pages at time of writing — used for
# offset/limit and limit-clamp assertions.
_BIG_FIXTURE = "tests/fixtures/long.txt"


@pytest.fixture()
def small_client(client: TestClient) -> TestClient:
    seed_main(_SMALL_FIXTURE, images_dir="tests/fixtures/demo-images", email=FIXTURE_EMAIL)
    return client


@pytest.fixture()
def units_client(client: TestClient) -> TestClient:
    seed_main(_UNITS_FIXTURE, email=FIXTURE_EMAIL)
    return client


@pytest.fixture()
def big_client(client: TestClient) -> TestClient:
    seed_main(_BIG_FIXTURE, email=FIXTURE_EMAIL)
    return client


# ---------- shape ----------


def test_content_returns_200_and_shape(small_client: TestClient) -> None:
    resp = small_client.get("/api/books/1/content")
    assert resp.status_code == 200
    body = resp.json()

    assert body["book_id"] == 1
    assert isinstance(body["total_pages"], int)
    assert body["total_pages"] >= 1
    assert body["last_page_index"] == 0
    assert body["last_page_offset"] == 0.0
    assert isinstance(body["pages"], list)
    assert isinstance(body["user_dict"], dict)

    # Default limit is 1 → exactly one page returned.
    assert len(body["pages"]) == 1
    page = body["pages"][0]
    assert page["page_index"] == 0
    assert "auto_unit_ids" in page
    assert isinstance(page["auto_unit_ids"], list)


# ---------- pagination ----------


def test_content_offset_and_limit(big_client: TestClient) -> None:
    body = big_client.get("/api/books/1/content?offset=0&limit=1").json()
    assert (
        body["total_pages"] > 3
    ), f"fixture must have >3 pages for this test; got {body['total_pages']}"

    resp = big_client.get("/api/books/1/content?offset=2&limit=3")
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    assert len(pages) == 3
    assert [p["page_index"] for p in pages] == [2, 3, 4]


def test_content_limit_clamped_at_20(big_client: TestClient) -> None:
    resp = big_client.get("/api/books/1/content?offset=0&limit=100")
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    # Our fixture has >20 pages, so the cap must bite.
    assert len(pages) == 20
    assert [p["page_index"] for p in pages] == list(range(20))


# ---------- 404 ----------


def test_content_missing_book_returns_404(small_client: TestClient) -> None:
    resp = small_client.get("/api/books/999/content")
    assert resp.status_code == 404


# ---------- auto_unit_ids ----------


def test_content_auto_unit_ids_from_dict(units_client: TestClient) -> None:
    base = units_client.get("/api/books/1/content").json()
    pages = base["pages"]
    assert pages, "fixture should produce at least one page"

    # Pick the first unit with a non-empty lemma on page 0.
    target_unit_id: int | None = None
    target_lemma: str | None = None
    for unit in pages[0].get("units", []):
        lemma = (unit.get("lemma") or "").strip()
        if lemma:
            target_unit_id = unit["id"]
            target_lemma = lemma.lower()
            break
    assert target_lemma is not None, "no units with a lemma on page 0"

    # Before the dict entry, auto_unit_ids is empty.
    assert pages[0]["auto_unit_ids"] == []

    # The seeded book belongs to the fixture user (id=2) since the
    # conftest signup is the second row after the migration placeholder.
    fixture_user = storage.user_by_email(FIXTURE_EMAIL)
    assert fixture_user is not None
    storage.dict_add(target_lemma, "тест-перевод", user_id=fixture_user.id)
    resp = units_client.get("/api/books/1/content")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_dict"] == {target_lemma: "тест-перевод"}
    assert target_unit_id in body["pages"][0]["auto_unit_ids"]
    for unit_id in body["pages"][0]["auto_unit_ids"]:
        unit = next(u for u in body["pages"][0]["units"] if u["id"] == unit_id)
        assert (unit["lemma"] or "").lower() == target_lemma
