"""EPUB (.epub) parser.

EPUB is a zip archive: XHTML chapters, images, CSS, and an OPF manifest
with a ``spine`` ordering the chapters. We read it with :mod:`ebooklib`
(for archive/manifest/spine handling) and parse each chapter's XHTML
with :mod:`bs4` (BeautifulSoup).

Two subtleties drive the implementation:

1. **Marker injection without structural damage.** A naive
   ``img.replace_with(new_p)`` nests a ``<p>`` inside the surrounding
   ``<p>``; when we later call ``get_text()`` on both, the marker shows
   up twice. We replace each ``<img>`` with a bare
   :class:`bs4.NavigableString` ``"IMG<id>"`` which is a pure text node —
   exactly one marker lands in the parent paragraph.

2. **Relative image paths.** An ``<img src>`` in a chapter is relative
   to that chapter's location inside the archive (e.g. ``../images/x.png``
   from ``OEBPS/chap1.xhtml``), while :attr:`epub.EpubImage.file_name`
   is the full archive-relative path (``OEBPS/images/x.png``). We
   resolve via :class:`pathlib.PurePosixPath` before looking up in the
   image map.

No DRM, no CSS filtering, no TOC — per the spec.
"""

from __future__ import annotations

import io
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup, NavigableString
from ebooklib import ITEM_COVER, ITEM_DOCUMENT, ITEM_IMAGE, epub

from ..images import new_image_id
from . import ParsedBook, ParsedImage, UnsupportedFormatError

# ebooklib distinguishes "cover image" from ordinary images with a
# dedicated item type. For our purposes both are image blobs we want to
# look up by archive path.
_IMAGE_TYPES = {ITEM_IMAGE, ITEM_COVER}


def parse_epub(data: bytes, filename: str) -> ParsedBook:
    """Parse an EPUB into a :class:`ParsedBook`.

    Parameters
    ----------
    data:
        Raw ``.epub`` bytes (a zip archive).
    filename:
        Original filename — only used as a fallback when the OPF has no
        ``<dc:title>``.

    Raises
    ------
    UnsupportedFormatError
        If ``data`` is not a valid EPUB archive (bad zip, missing OPF,
        DRM, …). The inner exception is chained.
    """
    try:
        book = epub.read_epub(io.BytesIO(data))
    except Exception as exc:  # ebooklib raises a mix of zipfile + lxml errors
        raise UnsupportedFormatError(f"invalid EPUB: {exc}") from exc

    title = _get_metadata(book, "title") or Path(filename).stem
    author = _get_metadata(book, "creator")
    language = _get_metadata(book, "language") or "en"

    # {archive_path: (image_id, mime, bytes)} for every image item in the
    # manifest. image_id is pre-generated so the same image used twice
    # inline still produces the same marker.
    image_map: dict[str, tuple[str, str, bytes]] = {}
    for item in book.get_items():
        if item.get_type() in _IMAGE_TYPES:
            image_map[item.file_name] = (
                new_image_id(),
                item.media_type,
                item.content,
            )

    cover, cover_filename = _extract_cover(book, image_map)

    inline_images: list[ParsedImage] = []
    used_image_ids: set[str] = set()
    text_parts: list[str] = []

    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        chapter_text = _extract_chapter_text(
            item=item,
            image_map=image_map,
            inline_images=inline_images,
            used_image_ids=used_image_ids,
            cover_filename=cover_filename,
        )
        if chapter_text.strip():
            text_parts.append(chapter_text)

    return ParsedBook(
        title=title,
        author=author,
        language=language,
        source_format="epub",
        source_bytes_size=len(data),
        text="\n\n".join(text_parts),
        images=inline_images,
        cover=cover,
    )


def _get_metadata(book: epub.EpubBook, key: str) -> str | None:
    """Return the first value of a Dublin Core metadata key, or ``None``."""
    entries = book.get_metadata("DC", key)
    if not entries:
        return None
    value = entries[0][0]
    if not value:
        return None
    stripped = value.strip()
    return stripped or None


def _extract_cover(
    book: epub.EpubBook,
    image_map: dict[str, tuple[str, str, bytes]],
) -> tuple[ParsedImage | None, str | None]:
    """Locate the cover image and return ``(ParsedImage, archive_path)``.

    Strategy:
    1. ``book.get_item_with_id("cover")`` — the convention ebooklib uses.
    2. Fallback: any image item whose manifest id contains ``"cover"``
       (case-insensitive). ebooklib's :class:`EpubCover` items are
       reported with :data:`ITEM_COVER` rather than :data:`ITEM_IMAGE`,
       so we accept both.

    The returned ``archive_path`` lets the caller skip the cover when it
    appears as an ``<img>`` inside a chapter (so the cover isn't also
    rendered inline).
    """
    cover_item = book.get_item_with_id("cover")
    if cover_item is not None and cover_item.get_type() in _IMAGE_TYPES:
        return (
            ParsedImage(
                image_id=new_image_id(),
                mime_type=cover_item.media_type,
                data=cover_item.content,
            ),
            cover_item.file_name,
        )

    for item in book.get_items():
        if item.get_type() not in _IMAGE_TYPES:
            continue
        if "cover" in (item.id or "").lower():
            return (
                ParsedImage(
                    image_id=new_image_id(),
                    mime_type=item.media_type,
                    data=item.content,
                ),
                item.file_name,
            )

    return None, None


def _extract_chapter_text(
    *,
    item: epub.EpubItem,
    image_map: dict[str, tuple[str, str, bytes]],
    inline_images: list[ParsedImage],
    used_image_ids: set[str],
    cover_filename: str | None,
) -> str:
    """Extract visible text + inline-image markers from one XHTML chapter.

    Mutates ``inline_images`` and ``used_image_ids`` so the caller can
    collect everything across chapters.
    """
    soup = BeautifulSoup(item.get_content(), "lxml-xml")

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            img.decompose()
            continue
        resolved = _resolve_src(item.file_name, src)

        # Cover: drop the tag so it doesn't emit a marker. The cover is
        # returned separately on ParsedBook.cover.
        if cover_filename is not None and resolved == cover_filename:
            img.decompose()
            continue

        mapped = image_map.get(resolved)
        if mapped is None:
            img.decompose()
            continue

        img_id, mime, content = mapped
        if img_id not in used_image_ids:
            used_image_ids.add(img_id)
            inline_images.append(ParsedImage(image_id=img_id, mime_type=mime, data=content))
        # NavigableString, *not* a new tag — see module docstring.
        img.replace_with(NavigableString(f"IMG{img_id}"))

    parts: list[str] = []
    for node in soup.find_all(["p", "div", "h1", "h2", "h3"]):
        txt = node.get_text(" ", strip=True)
        if txt:
            parts.append(txt)
    return "\n\n".join(parts)


def _resolve_src(chapter_filename: str, src: str) -> str:
    """Resolve an ``<img src>`` against the chapter's archive path.

    ``posixpath.normpath`` collapses ``..`` segments so the result matches
    the canonical archive key (``OEBPS/images/x.png``), which is what
    ebooklib reports as ``EpubImage.file_name``. Without normalization
    ``text/../images/x.png`` would never match and the image would be
    silently dropped.

    Examples
    --------
    >>> _resolve_src("OEBPS/chap1.xhtml", "images/x.png")
    'OEBPS/images/x.png'
    >>> _resolve_src("OEBPS/text/chap1.xhtml", "../images/x.png")
    'OEBPS/images/x.png'
    >>> _resolve_src("chap1.xhtml", "x.png")
    'x.png'
    """
    import posixpath

    chapter_dir = PurePosixPath(chapter_filename).parent
    joined = posixpath.join(str(chapter_dir), src) if src else str(chapter_dir)
    resolved = posixpath.normpath(joined)
    # ``normpath('')`` is ``'.'``; drop leading ``./`` or ``/``.
    if resolved.startswith("./"):
        resolved = resolved[2:]
    return resolved.lstrip("/")
