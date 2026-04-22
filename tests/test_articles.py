"""Tests for the extension-facing /api/articles endpoints.

Covers the three new routes: import, list, delete. Articles reuse the
full books pipeline (NLP + chunker + persist) but carry ``kind='article'``
so they stay out of ``/api/books`` and the library view.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL


_ARTICLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "She had never seen a more curious sight in her life. "
    "They kept walking until the sun finally set."
)


def test_import_article_creates_hidden_book(client: TestClient) -> None:
    resp = client.post(
        "/api/articles/import",
        json={
            "url": "https://example.com/some-article",
            "title": "A Test Article",
            "text": _ARTICLE_TEXT,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "A Test Article"
    assert body["source_url"] == "https://example.com/some-article"
    assert body["total_pages"] >= 1
    assert body["article_id"] == body["book_id"]
    assert len(body["pages"]) >= 1

    page = body["pages"][0]
    # Content shape must match /api/books/{id}/content for extension reuse.
    assert "text" in page and "tokens" in page and "units" in page
    assert "auto_unit_ids" in page


def test_imported_article_not_in_books_list(client: TestClient) -> None:
    # Seed one real book to make sure articles are filtered from it.
    book_id = seed_main(
        "tests/fixtures/golden/05-complex.txt", email=FIXTURE_EMAIL
    )

    resp = client.post(
        "/api/articles/import",
        json={"url": "https://x.test/a", "title": "T", "text": _ARTICLE_TEXT},
    )
    assert resp.status_code == 200
    article_id = resp.json()["article_id"]
    assert article_id != book_id

    # Library listing only shows kind='book' rows.
    books = client.get("/api/books").json()
    ids = [b["id"] for b in books]
    assert book_id in ids
    assert article_id not in ids


def test_list_articles_returns_imports(client: TestClient) -> None:
    a1 = client.post(
        "/api/articles/import",
        json={"url": "https://x.test/1", "title": "First", "text": _ARTICLE_TEXT},
    ).json()["article_id"]
    a2 = client.post(
        "/api/articles/import",
        json={"url": "https://x.test/2", "title": "Second", "text": _ARTICLE_TEXT},
    ).json()["article_id"]

    resp = client.get("/api/articles")
    assert resp.status_code == 200
    items = resp.json()
    assert [it["id"] for it in items] == [a2, a1]
    assert items[0]["source_url"] == "https://x.test/2"
    assert items[1]["title"] == "First"
    assert set(items[0].keys()) == {
        "id", "title", "author", "source_url", "total_pages", "created_at",
    }


def test_article_content_endpoint_works(client: TestClient) -> None:
    resp = client.post(
        "/api/articles/import",
        json={"url": "https://x.test/c", "title": "C", "text": _ARTICLE_TEXT},
    )
    article_id = resp.json()["article_id"]

    # Reuse the existing /api/books/{id}/content endpoint — articles are
    # books with kind='article', and _ensure_book_owner doesn't filter.
    content = client.get(
        f"/api/books/{article_id}/content?offset=0&limit=5"
    ).json()
    assert content["book_id"] == article_id
    assert content["total_pages"] >= 1
    assert len(content["pages"]) >= 1


def test_delete_article_removes_row(client: TestClient) -> None:
    resp = client.post(
        "/api/articles/import",
        json={"url": "https://x.test/d", "title": "D", "text": _ARTICLE_TEXT},
    )
    article_id = resp.json()["article_id"]

    del_resp = client.delete(f"/api/articles/{article_id}")
    assert del_resp.status_code == 204
    assert del_resp.content == b""

    # Gone from list.
    assert client.get("/api/articles").json() == []

    # Content endpoint 404s.
    assert client.get(f"/api/books/{article_id}/content").status_code == 404


def test_delete_regular_book_via_articles_404s(client: TestClient) -> None:
    book_id = seed_main(
        "tests/fixtures/golden/05-complex.txt", email=FIXTURE_EMAIL
    )
    # Using the articles endpoint on a real book must 404 — we don't want
    # a client bug to silently wipe library books.
    assert client.delete(f"/api/articles/{book_id}").status_code == 404
    # Book still exists.
    assert any(b["id"] == book_id for b in client.get("/api/books").json())


def test_article_import_requires_auth() -> None:
    from en_reader.app import app

    anon = TestClient(app)
    resp = anon.post(
        "/api/articles/import",
        json={"url": "https://x.test/a", "title": "T", "text": _ARTICLE_TEXT},
    )
    assert resp.status_code in (401, 403)


def test_article_import_via_v1_alias(client: TestClient) -> None:
    # /api/v1/* must remain a transparent alias for /api/* per M21 contract.
    resp = client.post(
        "/api/v1/articles/import",
        json={"url": "https://x.test/v1", "title": "V1", "text": _ARTICLE_TEXT},
    )
    assert resp.status_code == 200, resp.text
    article_id = resp.json()["article_id"]
    assert client.get("/api/v1/articles").json()[0]["id"] == article_id


def test_storage_book_list_kind_filter() -> None:
    """Direct storage check: book_list(kind=...) filters correctly."""
    from en_reader.parsers import ParsedBook

    # Create a user directly so we don't need the client fixture.
    storage.user_create("solo@example.com", "x")
    user = storage.user_by_email("solo@example.com")
    assert user is not None

    book = ParsedBook(
        title="Book", author=None, language="en", source_format="txt",
        source_bytes_size=10, text="Hello world. Good day.", kind="book",
    )
    article = ParsedBook(
        title="Article", author=None, language="en", source_format="txt",
        source_bytes_size=10, text="Hello world. Good day.",
        kind="article", source_url="https://x.test/solo",
    )
    bid = storage.book_save(book, user_id=user.id)
    aid = storage.book_save(article, user_id=user.id)

    # Default filter keeps only books.
    books_only = storage.book_list(user_id=user.id)
    assert [m.id for m in books_only] == [bid]

    articles_only = storage.book_list(user_id=user.id, kind="article")
    assert [m.id for m in articles_only] == [aid]
    assert articles_only[0].source_url == "https://x.test/solo"

    both = storage.book_list(user_id=user.id, kind=None)
    assert {m.id for m in both} == {bid, aid}
