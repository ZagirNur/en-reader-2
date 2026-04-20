"""Tests for :mod:`en_reader.parsers.fb2`."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from en_reader.parsers import UnsupportedFormatError
from en_reader.parsers.fb2 import parse_fb2

# A real 1x1 transparent PNG — valid enough that MIME sniffing would agree.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBg"
    "AAAABQABh6FO1AAAAABJRU5ErkJggg=="
)


def _build_fb2(
    *,
    include_title: bool = True,
    include_author: bool = True,
) -> bytes:
    """Construct a small, valid FB2 book in-memory for the tests.

    The fixture is generated per-test (not checked in) so we don't have a
    binary blob in the repo, and so the inputs stay obvious in the diff.
    """
    png_b64 = base64.b64encode(_PNG_BYTES).decode("ascii")

    title_xml = "<book-title>Sample Book</book-title>" if include_title else ""
    author_xml = (
        "<author><first-name>John</first-name><last-name>Doe</last-name></author>"
        if include_author
        else ""
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"'
        ' xmlns:l="http://www.w3.org/1999/xlink">'
        "<description><title-info>"
        + title_xml
        + author_xml
        + '<coverpage><image l:href="#cover.png"/></coverpage>'
        "<lang>en</lang>"
        "</title-info></description>"
        "<body><section>"
        '<p>Para 1 with <image l:href="#img1"/> inline.</p>'
        "<p>Para 2 has <emphasis>emphasis</emphasis> only.</p>"
        '<p>Para 3 with <image l:href="#img2"/> again.</p>'
        "</section></body>"
        f'<binary id="cover.png" content-type="image/png">{png_b64}</binary>'
        f'<binary id="img1" content-type="image/png">{png_b64}</binary>'
        f'<binary id="img2" content-type="image/png">{png_b64}</binary>'
        "</FictionBook>"
    )
    return xml.encode("utf-8")


def test_parse_fb2_returns_parsed_book() -> None:
    pb = parse_fb2(_build_fb2(), "sample.fb2")
    assert pb.title == "Sample Book"
    assert pb.author == "John Doe"
    assert pb.language == "en"
    assert pb.source_format == "fb2"
    assert pb.source_bytes_size > 0


def test_cover_extracted_separately() -> None:
    pb = parse_fb2(_build_fb2(), "sample.fb2")
    assert pb.cover is not None
    assert pb.cover.mime_type == "image/png"
    assert pb.cover.data == _PNG_BYTES
    # The cover marker must not leak into the body text.
    assert f"IMG{pb.cover.image_id}" not in pb.text


def test_inline_images_have_two() -> None:
    pb = parse_fb2(_build_fb2(), "sample.fb2")
    assert len(pb.images) == 2
    for img in pb.images:
        assert img.mime_type == "image/png"
        assert img.data == _PNG_BYTES


def test_text_has_exactly_two_markers() -> None:
    pb = parse_fb2(_build_fb2(), "sample.fb2")
    markers = re.findall(r"IMG[0-9a-f]{12}", pb.text)
    assert len(markers) == 2
    # One per inline image — distinct ids.
    assert len(set(markers)) == 2


def test_marker_image_ids_are_in_images() -> None:
    pb = parse_fb2(_build_fb2(), "sample.fb2")
    markers = re.findall(r"IMG([0-9a-f]{12})", pb.text)
    image_ids = {img.image_id for img in pb.images}
    assert set(markers) == image_ids


def test_invalid_xml_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_fb2(b"<not xml", "x.fb2")


def test_missing_title_falls_back_to_filename() -> None:
    pb = parse_fb2(_build_fb2(include_title=False), "war_and_peace.fb2")
    assert pb.title == Path("war_and_peace.fb2").stem


def test_empty_author_is_none() -> None:
    pb = parse_fb2(_build_fb2(include_author=False), "sample.fb2")
    assert pb.author is None
