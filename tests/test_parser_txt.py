"""Tests for :mod:`en_reader.parsers.txt`."""

from __future__ import annotations

from pathlib import Path

import pytest

from en_reader.parsers import UnsupportedFormatError
from en_reader.parsers.txt import parse_txt

FIXTURES = Path(__file__).parent / "fixtures" / "parsers"


def test_parses_utf8() -> None:
    data = (FIXTURES / "sample_utf8.txt").read_bytes()
    pb = parse_txt(data, "sample_utf8.txt")
    assert pb.text == "Hello world\nSecond line\n"
    assert pb.source_format == "txt"
    assert pb.author is None
    assert pb.images == []
    assert pb.cover is None


def test_strips_bom() -> None:
    data = (FIXTURES / "sample_utf8_bom.txt").read_bytes()
    pb = parse_txt(data, "sample_utf8_bom.txt")
    assert not pb.text.startswith("\ufeff")
    assert pb.text == "Hello with BOM\n"


def test_handles_cp1252() -> None:
    data = (FIXTURES / "sample_cp1252.txt").read_bytes()
    pb = parse_txt(data, "sample_cp1252.txt")
    # Smart quotes + em-dash should decode to their real Unicode code points,
    # not mojibake. Exact characters: U+201C, U+201D, U+2014.
    assert "\u201c" in pb.text  # left double quote
    assert "\u201d" in pb.text  # right double quote
    assert "\u2014" in pb.text  # em-dash
    # Sanity: no Latin-1 mojibake artifacts.
    assert "\x93" not in pb.text
    assert "\x94" not in pb.text
    assert "\x97" not in pb.text


def test_handles_win1251() -> None:
    data = (FIXTURES / "sample_win1251.txt").read_bytes()
    pb = parse_txt(data, "sample_win1251.txt")
    # Fixture starts with "Привет мир" — must appear verbatim, not mojibake.
    assert pb.text.startswith("Привет мир")
    # Sanity: full Cyrillic phrase from later line also roundtrips.
    assert "зелёные деревья" in pb.text
    # CRLFs in the fixture must be normalized.
    assert "\r" not in pb.text


def test_empty_bytes_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_txt(b"", "foo.txt")


def test_normalizes_crlf() -> None:
    pb = parse_txt(b"a\r\nb\rc\nd", "mixed.txt")
    assert pb.text == "a\nb\nc\nd"


def test_title_from_filename() -> None:
    pb = parse_txt(b"x", "war_and_peace.txt")
    assert pb.title == "war_and_peace"


def test_source_bytes_size_is_raw() -> None:
    # Two é (U+00E9) in UTF-8 is 4 bytes, 2 characters. We must report the
    # raw byte count (4), not the decoded character count (2) — regardless
    # of which encoding the detector ultimately settles on for such a
    # vanishingly small sample.
    pb = parse_txt(b"\xc3\xa9\xc3\xa9", "f.txt")
    assert pb.source_bytes_size == 4
