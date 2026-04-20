"""FictionBook 2 (.fb2) parser.

FB2 is an XML ebook format popular in the Russian-speaking world. The
interesting bits for us:

* Metadata (title, author, language) lives in ``description/title-info``.
* Binary blobs (cover, inline illustrations) are base64-encoded in
  ``<binary>`` elements and referenced by id from ``<image l:href="#id"/>``.
* Body text is marked up with ``<section>``/``<p>`` and light inline tags
  (``<emphasis>``, ``<strong>``).

This parser extracts the visible text in document order, converts each
inline ``<image>`` into an ``IMG<hex>`` marker (collecting its bytes into
``ParsedBook.images``), and returns the cover separately so the frontend
doesn't render it twice.
"""

from __future__ import annotations

import base64
from pathlib import Path

from lxml import etree

from ..images import new_image_id
from . import ParsedBook, ParsedImage, UnsupportedFormatError

_FB_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_NS = {"fb": _FB_NS, "l": _XLINK_NS}
_HREF_ATTR = f"{{{_XLINK_NS}}}href"


def parse_fb2(data: bytes, filename: str) -> ParsedBook:
    """Parse an FB2 book into a :class:`ParsedBook`.

    Parameters
    ----------
    data:
        Raw file bytes.
    filename:
        Original filename (used only as a fallback for ``title``).

    Raises
    ------
    UnsupportedFormatError
        If ``data`` is not well-formed XML.
    """
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise UnsupportedFormatError(f"invalid FB2 XML: {exc}") from exc

    title = _extract_title(root, filename)
    author = _extract_author(root)
    language = _extract_language(root)

    binaries = _collect_binaries(root)

    cover_href = _extract_cover_href(root)
    cover = None
    if cover_href and cover_href in binaries:
        mime, cover_bytes = binaries[cover_href]
        cover = ParsedImage(
            image_id=new_image_id(),
            mime_type=mime,
            data=cover_bytes,
        )

    text_parts: list[str] = []
    inline_images: list[ParsedImage] = []
    for body in root.findall(".//fb:body", _NS):
        _walk_body(body, text_parts, inline_images, binaries, cover_href)

    text = "\n\n".join(text_parts)

    return ParsedBook(
        title=title,
        author=author,
        language=language,
        source_format="fb2",
        source_bytes_size=len(data),
        text=text,
        images=inline_images,
        cover=cover,
    )


def _extract_title(root: etree._Element, filename: str) -> str:
    node = root.find(".//fb:description/fb:title-info/fb:book-title", _NS)
    if node is not None and node.text:
        stripped = node.text.strip()
        if stripped:
            return stripped
    return Path(filename).stem


def _extract_author(root: etree._Element) -> str | None:
    authors = root.findall(".//fb:description/fb:title-info/fb:author", _NS)
    names: list[str] = []
    for a in authors:
        fn = a.find("fb:first-name", _NS)
        ln = a.find("fb:last-name", _NS)
        parts = [
            (fn.text or "").strip() if fn is not None else "",
            (ln.text or "").strip() if ln is not None else "",
        ]
        name = " ".join(p for p in parts if p)
        if name:
            names.append(name)
    return ", ".join(names) if names else None


def _extract_language(root: etree._Element) -> str:
    node = root.find(".//fb:description/fb:title-info/fb:lang", _NS)
    if node is not None and node.text:
        stripped = node.text.strip()
        if stripped:
            return stripped
    return "en"


def _collect_binaries(root: etree._Element) -> dict[str, tuple[str, bytes]]:
    """Return ``{binary_id: (mime_type, decoded_bytes)}`` for every ``<binary>``."""
    out: dict[str, tuple[str, bytes]] = {}
    for b in root.findall(".//fb:binary", _NS):
        bid = b.get("id")
        if not bid:
            continue
        mime = b.get("content-type", "application/octet-stream")
        try:
            decoded = base64.b64decode(b.text or "")
        except (ValueError, TypeError):
            continue
        out[bid] = (mime, decoded)
    return out


def _extract_cover_href(root: etree._Element) -> str | None:
    node = root.find(".//fb:description/fb:title-info/fb:coverpage/fb:image", _NS)
    if node is None:
        return None
    href = node.get(_HREF_ATTR, "").lstrip("#")
    return href or None


def _walk_body(
    body: etree._Element,
    text_parts: list[str],
    inline_images: list[ParsedImage],
    binaries: dict[str, tuple[str, bytes]],
    cover_href: str | None,
) -> None:
    """Walk ``<p>`` elements inside ``body`` in document order."""
    for node in body.iter():
        if etree.QName(node).localname == "p":
            paragraph = _flatten_paragraph(node, inline_images, binaries, cover_href)
            if paragraph.strip():
                text_parts.append(paragraph)


def _flatten_paragraph(
    p: etree._Element,
    inline_images: list[ParsedImage],
    binaries: dict[str, tuple[str, bytes]],
    cover_href: str | None,
) -> str:
    """Flatten a single ``<p>`` into a string, rewriting ``<image>`` as markers."""
    buf: list[str] = []
    if p.text:
        buf.append(p.text)
    for child in p:
        tag = etree.QName(child).localname
        if tag == "image":
            href = child.get(_HREF_ATTR, "").lstrip("#")
            if href and href != cover_href and href in binaries:
                mime, data_bytes = binaries[href]
                img_id = new_image_id()
                inline_images.append(ParsedImage(image_id=img_id, mime_type=mime, data=data_bytes))
                buf.append(f"IMG{img_id}")
        elif tag in {"emphasis", "strong"}:
            buf.append(_flatten_paragraph(child, inline_images, binaries, cover_href))
        elif child.text:
            buf.append(child.text)
        if child.tail:
            buf.append(child.tail)
    return "".join(buf)
