"""Tests for the M1.2 `translatable` rule.

Mirrors the five cases from the spec section "4. Тесты" in
`tasks/M01-2-stop-words-translatable.md`.
"""

from __future__ import annotations

from en_reader.nlp import tokenize


def _by_text(tokens: list, text: str):
    """Return the first token whose surface form equals `text` (case-sensitive)."""
    for tok in tokens:
        if tok.text == text:
            return tok
    raise AssertionError(f"token with text {text!r} not found in {[t.text for t in tokens]}")


def test_the_cat_sat_on_the_mat() -> None:
    """Only `cat`, `sat`, `mat` are translatable; every other token must be False."""
    tokens = tokenize("The cat sat on the mat.")
    translatable_texts = [t.text for t in tokens if t.translatable]
    assert translatable_texts == ["cat", "sat", "mat"]

    # Explicitly assert the rest are False, as required by the spec.
    for word in ["The", "on", "the", "."]:
        assert _by_text(tokens, word).translatable is False, f"{word!r} should not be translatable"


def test_she_whispered_an_ominous_warning() -> None:
    """`whispered`, `ominous`, `warning` are translatable; `she` and `an` are not."""
    tokens = tokenize("She whispered an ominous warning.")
    assert _by_text(tokens, "whispered").translatable is True
    assert _by_text(tokens, "ominous").translatable is True
    assert _by_text(tokens, "warning").translatable is True
    assert _by_text(tokens, "She").translatable is False
    assert _by_text(tokens, "an").translatable is False


def test_i_have_eaten_aux_is_not_translatable() -> None:
    """AUX-dedup: in `I have eaten.`, `have` is AUX (False); `eaten` is True."""
    tokens = tokenize("I have eaten.")
    have = _by_text(tokens, "have")
    eaten = _by_text(tokens, "eaten")
    # `have` should be False both because it's in STOP_WORDS and because it's AUX.
    assert have.translatable is False
    assert eaten.translatable is True


def test_i_have_a_book_have_still_not_translatable() -> None:
    """`have` is always False: it lives in STOP_WORDS regardless of its role.

    Per the spec this is a deliberate MVP simplification — we keep `have` in
    STOP_WORDS so it never gets underlined, even when spaCy tags it VERB
    (as here, where it means "to possess").
    """
    tokens = tokenize("I have a book.")
    have = _by_text(tokens, "have")
    assert have.translatable is False  # in STOP_WORDS, regardless of POS=VERB vs AUX


def test_was_walking() -> None:
    """`was` (AUX / lemma `be`) is False; `walking` (VERB) is True."""
    tokens = tokenize("was walking")
    was = _by_text(tokens, "was")
    walking = _by_text(tokens, "walking")
    assert was.translatable is False
    assert walking.translatable is True
