"""Tests for ``POST /api/books/upload`` (M12.4).

Covers happy paths for all three supported formats (txt / fb2 / epub),
the handler's rejection path (unsupported / empty / too-large / corrupt),
and the auth gate. We reuse the ``_build_fb2`` / ``_build_epub`` fixture
helpers from the format-specific parser tests so the inputs remain
explicit in the diff without binary blobs in the repo.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app
from tests.test_parser_epub import _build_epub
from tests.test_parser_fb2 import _build_fb2


def test_upload_txt_200(client: TestClient) -> None:
    """A small UTF-8 ``.txt`` uploads cleanly and returns book metadata."""
    resp = client.post(
        "/api/books/upload",
        files={
            "file": (
                "hello.txt",
                b"Hello world. This is a tiny book with a handful of sentences.",
                "text/plain",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["book_id"], int) and body["book_id"] > 0
    assert body["title"] == "hello"
    assert body["total_pages"] >= 1


def test_upload_fb2_200(client: TestClient) -> None:
    """A valid FB2 round-trips through the parser + persist pipeline."""
    resp = client.post(
        "/api/books/upload",
        files={"file": ("sample.fb2", _build_fb2(), "application/xml")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Sample Book"
    assert body["total_pages"] >= 1
    assert isinstance(body["book_id"], int)


def test_upload_epub_200(client: TestClient) -> None:
    """A valid EPUB round-trips through the parser + persist pipeline."""
    resp = client.post(
        "/api/books/upload",
        files={"file": ("sample.epub", _build_epub(), "application/epub+zip")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Sample EPUB"
    assert body["total_pages"] >= 1


def test_upload_pdf_400(client: TestClient) -> None:
    """``.pdf`` bytes (unsupported extension, no magic-byte rescue) → 400."""
    resp = client.post(
        "/api/books/upload",
        files={
            "file": (
                "doc.pdf",
                b"%PDF-1.4\n%mock pdf content that we never parse",
                "application/pdf",
            )
        },
    )
    assert resp.status_code == 400
    # The dispatcher's error message includes the literal word "unsupported".
    assert "unsupported" in resp.json()["detail"].lower()


def test_upload_empty_400(client: TestClient) -> None:
    """An empty file body is rejected with 400 before we touch a parser."""
    resp = client.post(
        "/api/books/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_upload_too_large_413(client: TestClient, monkeypatch) -> None:
    """Monkeypatch the size cap tiny so we can exercise 413 without 200 MB.

    Actually uploading 201 MB through ``TestClient`` is prohibitively slow
    and memory-heavy; the handler's size check is a straightforward
    ``len(data) > MAX_UPLOAD_BYTES`` compare, so a cap of 100 with a 200-byte
    payload drives the same branch.
    """
    import en_reader.app as app_module

    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 100)
    payload = b"a" * 200
    resp = client.post(
        "/api/books/upload",
        files={"file": ("big.txt", payload, "text/plain")},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


def test_upload_malformed_fb2_400(client: TestClient) -> None:
    """A corrupt ``.fb2`` surfaces as 400 and leaves no trace in the DB."""
    before = client.get("/api/books").json()
    resp = client.post(
        "/api/books/upload",
        files={"file": ("broken.fb2", b"<not xml", "application/xml")},
    )
    assert resp.status_code == 400
    # Atomicity: the failed parse must not have half-written a books row.
    after = client.get("/api/books").json()
    assert before == after


def test_upload_unauthenticated_401() -> None:
    """A bare ``TestClient`` (no session) gets 401 on the upload route."""
    c = TestClient(app)
    resp = c.post(
        "/api/books/upload",
        files={"file": ("hello.txt", b"anything", "text/plain")},
    )
    assert resp.status_code == 401


def test_upload_returns_metadata(client: TestClient) -> None:
    """The 200 response envelope carries exactly the fields the UI needs."""
    resp = client.post(
        "/api/books/upload",
        files={
            "file": (
                "meta.txt",
                b"Some text for the metadata test. Another sentence here.",
                "text/plain",
            )
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"book_id", "title", "total_pages"}
    # And the row is actually persisted under the fixture user.
    meta = storage.book_meta(body["book_id"])
    assert meta is not None
    assert meta.title == body["title"]
    assert meta.total_pages == body["total_pages"]
