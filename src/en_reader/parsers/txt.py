"""Plain-text (.txt) parser.

Converts arbitrary ``bytes`` into a :class:`ParsedBook` by auto-detecting the
encoding via :mod:`charset_normalizer`. Handles the usual messes:

* Windows-1251 / CP1252 legacy encodings (old Western / Russian files).
* UTF-8 BOM (``\\ufeff`` prefix) — stripped.
* Mixed line endings (``\\r\\n`` / ``\\r``) — normalized to ``\\n``.

Fallback: if detection genuinely fails we decode as UTF-8 with
``errors="replace"`` so the user still gets a readable (if slightly lossy)
book rather than a hard error.
"""

from __future__ import annotations

from pathlib import Path

import charset_normalizer

from . import ParsedBook, UnsupportedFormatError


def parse_txt(data: bytes, filename: str) -> ParsedBook:
    """Parse a plain-text book into a :class:`ParsedBook`.

    Parameters
    ----------
    data:
        Raw file bytes.
    filename:
        Original filename (used only to derive ``title`` from the stem).

    Raises
    ------
    UnsupportedFormatError
        If ``data`` is empty.
    """
    if not data:
        raise UnsupportedFormatError("empty file")

    result = charset_normalizer.from_bytes(data).best()
    if result is None:
        # Detection failed completely — fall back to UTF-8 with replacement
        # so the user still gets something readable.
        text = data.decode("utf-8", errors="replace")
    else:
        text = str(result)

    # Strip UTF-8 BOM if it survived decoding.
    if text.startswith("\ufeff"):
        text = text[1:]

    # Normalize line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    title = Path(filename).stem or "Untitled"

    return ParsedBook(
        title=title,
        author=None,
        language="en",
        source_format="txt",
        source_bytes_size=len(data),
        text=text,
        images=[],
        cover=None,
    )
