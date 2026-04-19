"""Tests for the M1.1 tokenizer."""

from pathlib import Path

from en_reader.nlp import tokenize

FIXTURES = Path(__file__).parent / "fixtures"


def test_basic_tokenization() -> None:
    tokens = tokenize("The cat sat on the mat.")
    assert [t.text for t in tokens] == ["The", "cat", "sat", "on", "the", "mat", "."]
    assert len(tokens) == 7
    assert tokens[0].is_sent_start is True


def test_sentence_boundaries() -> None:
    tokens = tokenize("First sentence. Second sentence.")
    starts = [t for t in tokens if t.is_sent_start]
    assert len(starts) == 2
    assert [t.text for t in starts] == ["First", "Second"]


def test_concat_invariant() -> None:
    text = (FIXTURES / "demo.txt").read_text(encoding="utf-8")
    # Sanity-check the fixture is at least 200 words as required by the spec.
    assert len(text.split()) >= 200

    tokens = tokenize(text)
    assert tokens, "tokenize returned no tokens"

    rebuilt = text[: tokens[0].idx_in_text]
    for prev, curr in zip(tokens, tokens[1:]):
        rebuilt += prev.text
        rebuilt += text[prev.idx_in_text + len(prev.text) : curr.idx_in_text]
    last = tokens[-1]
    rebuilt += last.text
    rebuilt += text[last.idx_in_text + len(last.text) :]

    assert rebuilt == text
