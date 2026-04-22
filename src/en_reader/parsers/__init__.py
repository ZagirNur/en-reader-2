"""Parsed-book payload dataclasses shared by seed and (future) upload parsers.

On M8.1 the actual parsers (fb2/epub) don't exist yet — they land in M12. The
dataclasses live here so the seed script and ``storage.book_save`` can speak
in terms of a single shape regardless of source format.

M12.4 adds :func:`parse_book`, the extension-first dispatcher that feeds
``POST /api/books/upload`` and falls back to magic-byte sniffing when the
filename's extension is wrong or missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class UnsupportedFormatError(Exception):
    """Raised when a parser cannot make sense of the input bytes."""


@dataclass
class ParsedImage:
    """An image blob extracted (or injected) alongside the book text."""

    image_id: str
    mime_type: str
    data: bytes


@dataclass
class ParsedBook:
    """A format-agnostic book payload on its way to :func:`storage.book_save`.

    ``text`` already contains ``IMG<id>`` markers where images should appear;
    the seed script (and later the fb2/epub parsers) injects them before
    handing the object off.
    """

    title: str
    author: Optional[str]
    language: str
    source_format: str
    source_bytes_size: int
    text: str
    images: list[ParsedImage] = field(default_factory=list)
    cover: Optional[ParsedImage] = None
    kind: str = "book"
    source_url: Optional[str] = None


def parse_book(data: bytes, filename: str) -> ParsedBook:
    """Dispatch ``data`` to the right format parser.

    Primary routing is by filename extension (``.txt`` / ``.fb2`` /
    ``.epub``). If the extension is missing or unknown, we fall back to
    two cheap magic-byte sniffs: bytes starting with ``PK`` are probably a
    ZIP (and thus potentially an EPUB); bytes whose leading non-whitespace
    is ``<?xml`` are probably FB2. A failure on either fallback attempt is
    swallowed so we can still raise a clean :class:`UnsupportedFormatError`
    with the original extension in the message.
    """
    # Lazy imports so that importing the dataclasses doesn't pay the cost
    # of pulling in lxml / ebooklib / bs4 for callers that never parse.
    from .epub import parse_epub
    from .fb2 import parse_fb2
    from .txt import parse_txt

    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "txt":
        return parse_txt(data, filename)
    if ext == "fb2":
        return parse_fb2(data, filename)
    if ext == "epub":
        return parse_epub(data, filename)

    # Magic-byte fallback — only kicks in for wrong/missing extensions.
    if data.startswith(b"PK"):
        try:
            return parse_epub(data, filename)
        except UnsupportedFormatError:
            pass
    if data.lstrip()[:100].startswith(b"<?xml"):
        try:
            return parse_fb2(data, filename)
        except UnsupportedFormatError:
            pass

    raise UnsupportedFormatError(f"unsupported format: {ext or '(none)'}")
