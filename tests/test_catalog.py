"""Tests for the M16.5 catalog (seed, DAO, and API endpoints).

The autouse ``tmp_db`` fixture hands us a freshly-migrated v7 DB. We
seed a couple of catalog rows directly via the DAO (not by invoking the
seed script — that would couple every test to the sample text files on
disk and slow the suite down with spaCy loads) and exercise the HTTP
surface from there.

``test_seed_script_idempotent`` is the one case that does drive
:func:`scripts.seed_catalog.seed`: it confirms the sources-directory
pipeline produces the expected number of rows and that a second run is
a no-op.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from en_reader import storage
from tests.conftest import FIXTURE_EMAIL


def _fixture_user_id() -> int:
    user = storage.user_by_email(FIXTURE_EMAIL)
    assert user is not None
    return user.id


def _seed_two_rows() -> tuple[int, int]:
    """Insert two catalog rows pointing at the bundled peter-rabbit fixture."""
    # Both entries point at the same on-disk file — import only needs the
    # bytes, not a genuinely-unique text per row — but the (title, author)
    # uniqueness keeps the catalog table tidy.
    src = Path("data/catalog/sources/peter-rabbit.txt").resolve()
    a = storage.catalog_upsert(
        title="Peter Rabbit",
        author="Beatrix Potter",
        level="A1",
        pages=1,
        tags=["short", "beginner"],
        cover_preset="c-sage",
        source_url=None,
        source_path=str(src),
    )
    b = storage.catalog_upsert(
        title="Selfish Giant",
        author="Oscar Wilde",
        level="A2",
        pages=1,
        tags=["short"],
        cover_preset="c-olive",
        source_url=None,
        source_path=str(src),
    )
    return a, b


def test_catalog_upsert_is_idempotent() -> None:
    a1, _ = _seed_two_rows()
    a2, _ = _seed_two_rows()
    assert a1 == a2
    # Total row count is still 2, not 4.
    rows = storage.catalog_list()
    assert len(rows) == 2


def test_catalog_sections_groups_by_level() -> None:
    _seed_two_rows()
    sections = storage.catalog_sections(user_level="A2")
    keys = [s["key"] for s in sections]
    assert "По твоему уровню" in keys
    assert "Короткое — за выходные" in keys
    by_level = next(s for s in sections if s["key"] == "По твоему уровню")
    # A2 neighbours = A1, A2, B1 → both our rows qualify.
    titles = {it["title"] for it in by_level["items"]}
    assert titles == {"Peter Rabbit", "Selfish Giant"}
    shorts = next(s for s in sections if s["key"].startswith("Короткое"))
    assert len(shorts["items"]) == 2


def test_api_catalog_returns_sections(client: TestClient) -> None:
    _seed_two_rows()
    resp = client.get("/api/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert "sections" in body
    assert len(body["sections"]) >= 1
    # Each item carries the UI-required fields.
    item = body["sections"][0]["items"][0]
    for key in ("id", "title", "author", "level", "pages", "cover_preset"):
        assert key in item


def test_api_catalog_level_filter_respected(client: TestClient) -> None:
    _seed_two_rows()
    # C1 neighbours = B2, C1 → neither A1 nor A2 row qualifies.
    resp = client.get("/api/catalog?level=C1")
    by_level = next(s for s in resp.json()["sections"] if s["key"] == "По твоему уровню")
    assert by_level["items"] == []


def test_api_catalog_import_creates_book(client: TestClient) -> None:
    cat_id, _ = _seed_two_rows()
    resp = client.post(f"/api/catalog/{cat_id}/import")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "book_id" in body
    assert body["already_imported"] is False

    # The book shows up in the caller's personal library.
    books = client.get("/api/books").json()
    assert any(b["id"] == body["book_id"] for b in books)
    assert any(b["title"] == "Peter Rabbit" for b in books)


def test_api_catalog_import_second_time_is_dedup(client: TestClient) -> None:
    cat_id, _ = _seed_two_rows()
    first = client.post(f"/api/catalog/{cat_id}/import").json()
    second = client.post(f"/api/catalog/{cat_id}/import").json()
    assert second["book_id"] == first["book_id"]
    assert second["already_imported"] is True
    # Still only one row in books.
    books = client.get("/api/books").json()
    assert sum(1 for b in books if b["title"] == "Peter Rabbit") == 1


def test_api_catalog_import_missing_row_404(client: TestClient) -> None:
    resp = client.post("/api/catalog/9999/import")
    assert resp.status_code == 404


def test_api_catalog_cover_returns_preset(client: TestClient) -> None:
    cat_id, _ = _seed_two_rows()
    resp = client.get(f"/api/catalog/{cat_id}/cover")
    assert resp.status_code == 200
    assert resp.json() == {"cover_preset": "c-sage"}


def test_api_catalog_requires_auth() -> None:
    from en_reader.app import app

    anon = TestClient(app)
    assert anon.get("/api/catalog").status_code == 401
    assert anon.post("/api/catalog/1/import").status_code == 401


def test_seed_script_idempotent(monkeypatch) -> None:
    """Re-running the seed script against the same sources is a no-op."""
    # The CATALOG tuple is small (4 entries), and not every test env
    # will have the full set of source files. We just assert that:
    # 1. The first seed() inserts N >= 1 row.
    # 2. A second seed() produces the same row count (no duplicates).
    from scripts import seed_catalog

    first = seed_catalog.seed()
    before = len(storage.catalog_list())
    second = seed_catalog.seed()
    after = len(storage.catalog_list())

    assert first >= 1
    assert second == first  # same files touched the second time
    assert after == before  # but no new rows inserted


def test_users_cannot_see_other_users_imports(client: TestClient) -> None:
    """An imported catalog book lives under the caller's user_id only.

    M11.3 made /api/books already user-scoped, so we just confirm the
    import pipeline hands the correct user_id to storage.book_save and
    doesn't, say, hardcode SEED_USER_ID.
    """
    cat_id, _ = _seed_two_rows()
    resp = client.post(f"/api/catalog/{cat_id}/import")
    book_id = resp.json()["book_id"]

    meta = storage.book_meta(book_id, user_id=_fixture_user_id())
    assert meta is not None
    # The seed user (id=1) should NOT own this book.
    from en_reader.storage import SEED_USER_ID

    seed_meta = storage.book_meta(book_id, user_id=SEED_USER_ID)
    assert seed_meta is None
