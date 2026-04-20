"""Tests for :func:`en_reader.parsers.parse_book` — the extension-first dispatcher.

The dispatcher routes by filename extension first, falling back to cheap
magic-byte sniffs (``PK`` → EPUB, ``<?xml`` → FB2) when the extension is
missing, wrong, or unknown. These tests exercise all four branches end
to end (txt / fb2 / epub / unknown) plus both magic-byte fallbacks.

The FB2 and EPUB byte-level fixtures are borrowed from the per-parser
test modules (imported as helpers) so the dispatcher tests don't grow
their own parallel generators.
"""

from __future__ import annotations

import pytest

from en_reader.parsers import UnsupportedFormatError, parse_book
from tests.test_parser_epub import _build_epub
from tests.test_parser_fb2 import _build_fb2


def test_parse_book_dispatches_by_extension() -> None:
    """Each of .txt / .fb2 / .epub lands on the right parser (checked via source_format)."""
    txt_bytes = b"Hello world\n"
    fb2_bytes = _build_fb2()
    epub_bytes = _build_epub()

    assert parse_book(txt_bytes, "x.txt").source_format == "txt"
    assert parse_book(fb2_bytes, "x.fb2").source_format == "fb2"
    assert parse_book(epub_bytes, "x.epub").source_format == "epub"


def test_parse_book_magic_bytes_fallback_fb2() -> None:
    """Well-formed FB2 body with a ``.pdf`` extension falls back via the ``<?xml`` magic."""
    fb2_bytes = _build_fb2()
    # ``.pdf`` is an unknown extension for the dispatcher, so it must hit
    # the magic-byte branch. The body starts with ``<?xml``, so the FB2
    # parser is tried and succeeds.
    pb = parse_book(fb2_bytes, "mislabeled.pdf")
    assert pb.source_format == "fb2"


def test_parse_book_magic_bytes_fallback_epub() -> None:
    """Valid EPUB bytes with a ``.dat`` extension fall back via the ``PK`` magic."""
    epub_bytes = _build_epub()
    pb = parse_book(epub_bytes, "mystery.dat")
    assert pb.source_format == "epub"


def test_parse_book_unknown_extension_unknown_magic_raises() -> None:
    """Neither XML nor ZIP, with an unknown extension → ``UnsupportedFormatError``."""
    # Arbitrary non-XML, non-ZIP bytes. First byte isn't ``P`` (so no PK
    # sniff) and leading content isn't ``<?xml``.
    with pytest.raises(UnsupportedFormatError):
        parse_book(b"\x00\x01\x02not a real format", "weird.bin")
