"""M15.1 — extra tokenizer coverage on top of the M1.1 base suite.

* ``is_sent_start`` fires correctly after ``!`` and ``?``.
* Concat invariant on the long fixture (``tests/fixtures/long.txt``).
* Tabs and mixed whitespace preserve ``idx_in_text`` such that the
  original text can be rebuilt byte-perfectly.
"""

from __future__ import annotations

from pathlib import Path

from en_reader.nlp import tokenize

FIXTURES = Path(__file__).parent / "fixtures"


def _rebuild(text: str, tokens: list) -> str:
    """Rebuild the input text from token surface forms + inter-token gaps."""
    if not tokens:
        return text
    rebuilt = text[: tokens[0].idx_in_text]
    for prev, curr in zip(tokens, tokens[1:]):
        rebuilt += prev.text
        rebuilt += text[prev.idx_in_text + len(prev.text) : curr.idx_in_text]
    last = tokens[-1]
    rebuilt += last.text
    rebuilt += text[last.idx_in_text + len(last.text) :]
    return rebuilt


def test_sentence_start_after_exclamation() -> None:
    """After ``!`` the next word opens a new sentence."""
    tokens = tokenize('"Hello!" He said.')
    starts = [t.text for t in tokens if t.is_sent_start]
    # We accept the common spaCy grouping for this input, but the guarantee
    # we care about is: ``He`` is marked as a sentence start.
    assert "He" in starts, starts


def test_sentence_start_after_question_mark() -> None:
    """After ``?`` the next word opens a new sentence."""
    tokens = tokenize("Are you here? She smiled.")
    starts = [t.text for t in tokens if t.is_sent_start]
    assert "Are" in starts
    assert "She" in starts


def test_concat_invariant_on_long_fixture() -> None:
    """``long.txt`` rebuilds byte-perfectly from tokens + inter-token gaps."""
    text = (FIXTURES / "long.txt").read_text(encoding="utf-8")
    tokens = tokenize(text)
    assert tokens, "tokenize returned no tokens"
    assert _rebuild(text, tokens) == text


def test_idx_in_text_with_tabs_and_mixed_whitespace() -> None:
    """Tabs, mixed spaces and line breaks must preserve idx_in_text exactly."""
    text = "Hello\tworld.\n\n  Second\tline  here.\n\tThird line."
    tokens = tokenize(text)
    # Rebuild — the strongest invariant.
    assert _rebuild(text, tokens) == text
    # Spot-check: every token's idx_in_text + len(text) boundary exactly
    # matches its slice into the source string.
    for tok in tokens:
        assert text[tok.idx_in_text : tok.idx_in_text + len(tok.text)] == tok.text, tok
