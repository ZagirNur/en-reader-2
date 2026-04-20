"""Parsed-book payload dataclasses shared by seed and (future) upload parsers.

On M8.1 the actual parsers (fb2/epub) don't exist yet — they land in M12. The
dataclasses live here so the seed script and ``storage.book_save`` can speak
in terms of a single shape regardless of source format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
