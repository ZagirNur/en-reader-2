"""Tests for :mod:`en_reader.parsers.epub`.

The fixture EPUB is built programmatically with :mod:`ebooklib` so the
inputs stay explicit in the diff (and we don't need a binary blob
checked into the repo).
"""

from __future__ import annotations

import base64
import re

import pytest
from ebooklib import epub

from en_reader.parsers import UnsupportedFormatError
from en_reader.parsers.epub import parse_epub

# A real 1x1 transparent PNG.
_COVER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBg"
    "AAAABQABh6FO1AAAAABJRU5ErkJggg=="
)
# A *different* tiny PNG (full red pixel) so we can tell inline images
# apart from the cover by bytes equality.
_INLINE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
)


def _build_epub() -> bytes:
    """Build a small, valid EPUB with 3 chapters, 2 inline images, 1 cover.

    Layout inside the archive::

        OEBPS/
          cover.xhtml       (uses cover.png — must NOT yield a marker)
          chap1.xhtml       (uses images/fig1.png)
          chap2.xhtml       (text only)
          chap3.xhtml       (uses ../OEBPS/images/fig2.png via a relative src)
          cover.png
          images/
            fig1.png
            fig2.png
    """
    book = epub.EpubBook()
    book.set_identifier("test-epub-id")
    book.set_title("Sample EPUB")
    book.set_language("en")
    book.add_author("Jane Doe")

    # --- Cover (image item with id="cover"). Using set_cover emits a
    # cover.xhtml too, which is convenient for asserting the cover isn't
    # duplicated in the body text.
    book.set_cover("cover.png", _COVER_PNG)

    # --- Inline images.
    fig1 = epub.EpubImage(
        uid="fig1",
        file_name="images/fig1.png",
        media_type="image/png",
        content=_INLINE_PNG,
    )
    fig2 = epub.EpubImage(
        uid="fig2",
        file_name="images/fig2.png",
        media_type="image/png",
        content=_INLINE_PNG,
    )
    book.add_item(fig1)
    book.add_item(fig2)

    # --- Chapters.
    chap1 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
    # src is relative to chap1.xhtml — which lives in the archive root of
    # whatever prefix ebooklib uses (EPUB/), so "images/fig1.png" resolves
    # in that same directory.
    chap1.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 1</title></head>"
        "<body>"
        "<h1>Chapter 1</h1>"
        "<p>First paragraph with <img src='images/fig1.png' alt='fig1'/> inline.</p>"
        "<p>A second paragraph with plain text.</p>"
        "</body></html>"
    )

    chap2 = epub.EpubHtml(title="Chapter 2", file_name="chap2.xhtml", lang="en")
    chap2.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 2</title></head>"
        "<body>"
        "<h2>Chapter 2</h2>"
        "<p>Chapter two is all words, no pictures.</p>"
        "</body></html>"
    )

    chap3 = epub.EpubHtml(title="Chapter 3", file_name="chap3.xhtml", lang="en")
    # Still relative, still resolves to images/fig2.png.
    chap3.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 3</title></head>"
        "<body>"
        "<h3>Chapter 3</h3>"
        "<p>Third chapter with <img src='images/fig2.png' alt='fig2'/> here.</p>"
        "</body></html>"
    )

    book.add_item(chap1)
    book.add_item(chap2)
    book.add_item(chap3)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = ["nav", chap1, chap2, chap3]
    book.toc = (chap1, chap2, chap3)

    import io as _io

    buf = _io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


@pytest.fixture(scope="module")
def sample_epub_bytes() -> bytes:
    """Build the sample EPUB exactly once per test module."""
    return _build_epub()


def test_parse_epub_basic(sample_epub_bytes: bytes) -> None:
    pb = parse_epub(sample_epub_bytes, "sample.epub")
    assert pb.title == "Sample EPUB"
    assert pb.author == "Jane Doe"
    assert pb.language == "en"
    assert pb.source_format == "epub"
    assert pb.source_bytes_size == len(sample_epub_bytes)


def test_cover_extracted(sample_epub_bytes: bytes) -> None:
    pb = parse_epub(sample_epub_bytes, "sample.epub")
    assert pb.cover is not None
    assert pb.cover.mime_type == "image/png"
    assert pb.cover.data == _COVER_PNG


def test_inline_images_have_two(sample_epub_bytes: bytes) -> None:
    pb = parse_epub(sample_epub_bytes, "sample.epub")
    assert len(pb.images) == 2
    for img in pb.images:
        assert img.mime_type == "image/png"
        assert img.data == _INLINE_PNG


def test_text_has_exactly_two_markers(sample_epub_bytes: bytes) -> None:
    pb = parse_epub(sample_epub_bytes, "sample.epub")
    markers = re.findall(r"IMG[0-9a-f]{12}", pb.text)
    assert len(markers) == 2
    assert len(set(markers)) == 2


def test_marker_no_duplication(sample_epub_bytes: bytes) -> None:
    """Regression guard for the ``replace_with(new_p)`` trap.

    If we wrapped each ``<img>`` in a new ``<p>`` and let BeautifulSoup
    nest it inside the surrounding ``<p>``, ``get_text()`` would emit
    each marker twice. With :class:`NavigableString` it must appear
    exactly once.
    """
    pb = parse_epub(sample_epub_bytes, "sample.epub")
    markers = re.findall(r"IMG[0-9a-f]{12}", pb.text)
    # The real invariant: each marker appears at most once.
    counts: dict[str, int] = {}
    for m in markers:
        counts[m] = counts.get(m, 0) + 1
    for marker, count in counts.items():
        assert count == 1, f"marker {marker} duplicated ({count}x)"


def test_invalid_zip_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_epub(b"not-a-zip", "x.epub")


def test_cover_not_in_text(sample_epub_bytes: bytes) -> None:
    pb = parse_epub(sample_epub_bytes, "sample.epub")
    assert pb.cover is not None
    assert f"IMG{pb.cover.image_id}" not in pb.text
    # And the cover id is not on any inline image either.
    assert pb.cover.image_id not in {img.image_id for img in pb.images}


def test_relative_parent_src_resolves() -> None:
    """Chapter under ``text/`` referencing ``../images/fig.png`` must resolve
    to the canonical ``images/fig.png`` so the marker lands in text.

    Regression for the ``_resolve_src`` bug that left ``..`` segments
    uncollapsed and silently dropped any image referenced this way.
    """
    book = epub.EpubBook()
    book.set_identifier("parent-src")
    book.set_title("Parent-Src")
    book.set_language("en")
    book.add_author("Jane Doe")

    img = epub.EpubImage(
        uid="fig1",
        file_name="images/fig1.png",
        media_type="image/png",
        content=_INLINE_PNG,
    )
    book.add_item(img)

    chap = epub.EpubHtml(title="Chapter 1", file_name="text/chap1.xhtml", lang="en")
    chap.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 1</title></head>"
        "<body><p>Before <img src='../images/fig1.png' alt='x'/> after.</p></body>"
        "</html>"
    )
    book.add_item(chap)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chap]
    book.toc = (chap,)

    import io as _io

    buf = _io.BytesIO()
    epub.write_epub(buf, book)
    pb = parse_epub(buf.getvalue(), "parent.epub")
    markers = re.findall(r"IMG[0-9a-f]{12}", pb.text)
    assert len(markers) == 1, f"expected one marker, got text={pb.text!r}"
    assert len(pb.images) == 1


def test_epub_without_cover() -> None:
    """EPUB with no cover set → ``parsed.cover is None``."""
    book = epub.EpubBook()
    book.set_identifier("no-cover")
    book.set_title("No Cover")
    book.set_language("en")
    book.add_author("Jane Doe")

    chap = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
    chap.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 1</title></head>"
        "<body><p>Just text, no cover.</p></body></html>"
    )
    book.add_item(chap)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chap]
    book.toc = (chap,)

    import io as _io

    buf = _io.BytesIO()
    epub.write_epub(buf, book)

    pb = parse_epub(buf.getvalue(), "nocover.epub")
    assert pb.cover is None
    assert pb.images == []
    assert "Just text" in pb.text


def test_nested_img_yields_single_marker() -> None:
    """<p><em><span><img/></span></em></p> → exactly one marker for that image.

    The resolver descends into inline wrappers; the regression we're
    guarding against is a duplicate marker (once from the wrapper's text
    content, once from the re-inserted NavigableString).
    """
    book = epub.EpubBook()
    book.set_identifier("nested-img")
    book.set_title("Nested Img")
    book.set_language("en")
    book.add_author("Jane Doe")

    img = epub.EpubImage(
        uid="fig1",
        file_name="images/fig1.png",
        media_type="image/png",
        content=_INLINE_PNG,
    )
    book.add_item(img)

    chap = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
    chap.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 1</title></head>"
        "<body>"
        "<p>Before "
        "<em><span><img src='images/fig1.png' alt='x'/></span></em>"
        " after.</p>"
        "</body></html>"
    )
    book.add_item(chap)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chap]
    book.toc = (chap,)

    import io as _io

    buf = _io.BytesIO()
    epub.write_epub(buf, book)

    pb = parse_epub(buf.getvalue(), "nested.epub")
    markers = re.findall(r"IMG[0-9a-f]{12}", pb.text)
    assert len(markers) == 1, f"expected one marker, got text={pb.text!r}"
    assert len(pb.images) == 1


def test_manifest_image_not_in_text_is_not_in_inline_images() -> None:
    """Manifest image never referenced in any chapter → not in ``parsed.images``.

    Only images that actually appear inline (as ``<img>`` in a spine-linked
    chapter) are emitted; orphan manifest items must be ignored.
    """
    book = epub.EpubBook()
    book.set_identifier("orphan")
    book.set_title("Orphan Image")
    book.set_language("en")
    book.add_author("Jane Doe")

    used = epub.EpubImage(
        uid="used",
        file_name="images/used.png",
        media_type="image/png",
        content=_INLINE_PNG,
    )
    orphan = epub.EpubImage(
        uid="orphan",
        file_name="images/orphan.png",
        media_type="image/png",
        content=_INLINE_PNG,
    )
    book.add_item(used)
    book.add_item(orphan)

    chap = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
    chap.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'>"
        "<head><title>Chapter 1</title></head>"
        "<body><p>See <img src='images/used.png' alt='u'/> here.</p></body>"
        "</html>"
    )
    book.add_item(chap)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chap]
    book.toc = (chap,)

    import io as _io

    buf = _io.BytesIO()
    epub.write_epub(buf, book)

    pb = parse_epub(buf.getvalue(), "orphan.epub")
    # Exactly one inline image, and it's the "used" one (bytes match, but
    # more precisely: exactly one entry, not two).
    assert len(pb.images) == 1
    # Exactly one marker in text.
    markers = re.findall(r"IMG[0-9a-f]{12}", pb.text)
    assert len(markers) == 1
    # The orphan image's id must not appear anywhere on the emitted
    # inline-images list (structural invariant, not a byte check since
    # both images share _INLINE_PNG content).
    assert len({img.image_id for img in pb.images}) == 1
