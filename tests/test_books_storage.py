"""Tests for the M8.1 books/pages persistence layer.

Exercises :func:`storage.book_save` + `_list` + `_meta` + `_delete` and the
page slice loaders, plus the text-reconstruction invariant
(``"\\n\\n".join(pages) == parsed.text``) that keeps the reader frontend
gap-aware. Uses the autouse ``tmp_db`` fixture from ``conftest.py`` so
every test runs against a freshly migrated SQLite file.
"""

from __future__ import annotations

import base64
from pathlib import Path

from en_reader import storage
from en_reader.images import IMAGE_MARKER_RE
from en_reader.parsers import ParsedBook, ParsedImage
from scripts.seed import main as seed_main

_FIXTURE = "tests/fixtures/golden/05-complex.txt"

# Tiny PNG for the cascade-delete test.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="
)


def _fixture_text() -> str:
    """Raw text of the 05-complex fixture (no markers)."""
    repo_root = Path(__file__).resolve().parent.parent
    return (repo_root / _FIXTURE).read_text(encoding="utf-8")


def test_book_save_creates_rows() -> None:
    book_id = seed_main(_FIXTURE)

    listed = storage.book_list()
    assert len(listed) == 1
    assert listed[0].id == book_id
    assert listed[0].total_pages > 0

    pages = storage.pages_load_slice(book_id, 0, 1000)
    assert len(pages) == listed[0].total_pages


def test_pages_load_slice_ordering() -> None:
    book_id = seed_main(_FIXTURE)

    pages = storage.pages_load_slice(book_id, 0, 6)
    assert len(pages) >= 1
    # page_index must be a strictly ascending run starting at 0.
    assert [p.page_index for p in pages] == list(range(len(pages)))


def test_pages_load_slice_offset() -> None:
    book_id = seed_main(_FIXTURE)
    meta = storage.book_meta(book_id)
    assert meta is not None

    tail = storage.pages_load_slice(book_id, meta.total_pages - 1, 10)
    assert len(tail) == 1
    assert tail[0].page_index == meta.total_pages - 1


def test_concat_invariant() -> None:
    raw_text = _fixture_text()
    book_id = seed_main(_FIXTURE)
    meta = storage.book_meta(book_id)
    assert meta is not None

    loaded = storage.pages_load_slice(book_id, 0, meta.total_pages)
    joined = "\n\n".join(p.text for p in loaded)
    # No images injected → marker-stripping is a no-op; we still run it so
    # the invariant stays readable when someone flips on images later.
    stripped = IMAGE_MARKER_RE.sub("", joined)
    assert stripped == raw_text.rstrip()


def test_book_delete_cascades() -> None:
    parsed = ParsedBook(
        title="tiny",
        author=None,
        language="en",
        source_format="txt",
        source_bytes_size=5,
        text="Hello world. Goodbye world.",
        images=[ParsedImage(image_id="abcdef012345", mime_type="image/png", data=_TINY_PNG)],
    )
    book_id = storage.book_save(parsed)

    # Sanity: rows exist pre-delete.
    assert storage.book_meta(book_id) is not None
    assert storage.image_get(book_id, "abcdef012345") is not None
    pre_pages = storage.pages_load_slice(book_id, 0, 1000)
    assert len(pre_pages) >= 1

    storage.book_delete(book_id)

    assert storage.book_meta(book_id) is None
    assert storage.image_get(book_id, "abcdef012345") is None
    assert storage.pages_load_slice(book_id, 0, 1000) == []


def test_save_twice_yields_distinct_ids() -> None:
    first = seed_main(_FIXTURE)
    second = seed_main(_FIXTURE)
    assert first != second
    assert len(storage.book_list()) == 2


def test_book_meta() -> None:
    book_id = seed_main(_FIXTURE, title="Custom Title")
    meta = storage.book_meta(book_id)
    assert meta is not None
    assert meta.id == book_id
    assert meta.title == "Custom Title"
    assert meta.author is None
    assert meta.language == "en"
    assert meta.source_format == "txt"
    assert meta.source_bytes_size > 0
    assert meta.total_pages >= 1
    assert meta.cover_path is None
    # ISO-8601 UTC timestamp.
    assert "T" in meta.created_at
