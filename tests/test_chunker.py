"""Tests for the M2.1 page chunker."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from en_reader.chunker import chunk
from en_reader.nlp import analyze

FIXTURES = Path(__file__).parent / "fixtures"

# Mirror the chunker's "word" proxy so tests can do the same rough counting.
_WORD_POS = {
    "VERB",
    "NOUN",
    "ADJ",
    "ADV",
    "PROPN",
    "PRON",
    "DET",
    "ADP",
    "AUX",
    "NUM",
    "INTJ",
}


def _word_count(tokens) -> int:
    return sum(1 for t in tokens if t.pos in _WORD_POS)


def test_small_text_one_page() -> None:
    text = (
        "The quiet village sat between two hills and a slow river. "
        "Every morning the baker opened his window to smell the bread. "
        "Children walked to school along the narrow gravel road. "
        "In the evening the old men gathered by the fountain to talk. "
        "Nothing unusual ever happened there, and everyone seemed glad about it."
    )
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)

    assert len(pages) == 1
    # 50-ish content words from the narrative above.
    wc = _word_count(pages[0].tokens)
    assert 40 <= wc <= 70


def test_100_word_boundary() -> None:
    # Five short sentences, each ~24 words, totaling ~120 words. The buffer
    # should hit the 100-word floor and close on a sentence boundary.
    sentence = (
        "The curious traveler walked through the bustling market and watched "
        "vendors arrange their brightly colored fruits while bargaining loudly "
        "with the early morning customers passing by."
    )
    text = " ".join([sentence] * 5)
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)

    assert len(pages) >= 1
    # First page must end at a sentence-final punctuation token.
    assert pages[0].tokens[-1].text in {".", "!", "?"}

    total = sum(_word_count(p.tokens) for p in pages)
    assert total == _word_count(tokens)


def test_multiple_pages() -> None:
    # ~2500 words: repeat a ~25-word sentence 100 times.
    sentence = (
        "The curious traveler walked through the bustling market and watched "
        "vendors arrange their brightly colored fruits while bargaining loudly "
        "with the early morning customers passing by."
    )
    text = " ".join([sentence] * 100)
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)

    assert 3 <= len(pages) <= 4
    for p in pages[:-1]:
        wc = _word_count(p.tokens)
        assert 100 <= wc <= 1000, f"page {p.page_index} has {wc} words"
    # Last page may dip below 100 but still respects the ceiling.
    assert _word_count(pages[-1].tokens) <= 1000

    for p in pages:
        assert p.tokens[0].is_sent_start is True


def test_oversized_single_sentence(caplog: pytest.LogCaptureFixture) -> None:
    # Build a single sentence of 1200 "word" tokens (each "word" is a content
    # NOUN per spaCy). No intermediate period means spaCy sees a lone sentence.
    text = ("word " * 1200).rstrip() + "."
    tokens, units = analyze(text)

    with caplog.at_level(logging.WARNING, logger="en_reader.chunker"):
        pages = chunk(tokens, units, text)

    assert len(pages) == 1
    assert any("Oversized page" in rec.message for rec in caplog.records)


def test_concat_invariant() -> None:
    text = (
        "The quiet village sat between two hills and a slow river. "
        "Every morning the baker opened his window to smell the bread. "
        "Children walked to school along the narrow gravel road. "
        "In the evening the old men gathered by the fountain to talk. "
        "Nothing unusual ever happened there, and everyone seemed glad about it."
    )
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)

    assert "\n\n".join(p.text for p in pages) == text.rstrip()


def test_sentence_boundary_invariant() -> None:
    sentence = (
        "The curious traveler walked through the bustling market and watched "
        "vendors arrange their brightly colored fruits while bargaining loudly "
        "with the early morning customers passing by."
    )
    text = " ".join([sentence] * 100)
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)

    assert pages
    for p in pages:
        assert p.tokens[0].is_sent_start is True


def test_no_sentence_split() -> None:
    # Use the same 100-sentence synthetic text to guarantee >= 2 pages.
    sentence = (
        "The curious traveler walked through the bustling market and watched "
        "vendors arrange their brightly colored fruits while bargaining loudly "
        "with the early morning customers passing by."
    )
    text = " ".join([sentence] * 100)
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)
    assert len(pages) >= 2

    # Walk the original tokens sentence by sentence and match each sentence's
    # first+last token text against exactly one page's token stream.
    def sentences_of(toks):
        if not toks:
            return
        start = 0
        for i in range(1, len(toks)):
            if toks[i].is_sent_start:
                yield toks[start:i]
                start = i
        yield toks[start:]

    # Build a cheap signature for each page: list of (text, idx_in_text)
    # isn't globally unique, so fall back to sequence of token texts plus a
    # running "page membership" check by looking for consecutive match.
    page_signatures = [[t.text for t in p.tokens] for p in pages]

    def find_in_single_page(sent_texts: list[str]) -> int:
        for idx, sig in enumerate(page_signatures):
            # Look for sent_texts as a contiguous subsequence of sig.
            n = len(sent_texts)
            for i in range(len(sig) - n + 1):
                if sig[i : i + n] == sent_texts:
                    return idx
        return -1

    for sent in sentences_of(tokens):
        sent_texts = [t.text for t in sent]
        page_idx = find_in_single_page(sent_texts)
        assert page_idx != -1, "sentence was split across pages or missing"


def test_long_fixture() -> None:
    text = (FIXTURES / "long.txt").read_text(encoding="utf-8")
    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)
    assert pages
    assert "\n\n".join(p.text for p in pages) == text.rstrip()
