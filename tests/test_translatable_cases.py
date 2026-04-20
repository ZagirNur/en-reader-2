"""M15.1 — parametrized expansion of the M1.2 `translatable` rule.

Exercises the full decision tree of `mark_translatable` through ~30 sentence
cases. Each case pairs a surface form with the explicit expectation on the
token's ``translatable`` flag (rather than the whole list of translatables),
so failures pinpoint the exact rule that regressed.

Covers:
* PROPN (proper nouns) — translatable.
* NUM (numbers) — not translatable (POS whitelist excludes NUM).
* AUX forms of ``be`` / ``have`` / ``do`` — skipped.
* STOP_WORDS (pronouns, determiners, modals, conjunctions, prepositions).
* PUNCT / SPACE / SYM — never translatable.
* INTJ (interjections) — not in POS whitelist.
"""

from __future__ import annotations

import pytest

from en_reader.nlp import tokenize


def _by_text(tokens: list, text: str):
    """Return the first token whose surface form equals ``text``."""
    for tok in tokens:
        if tok.text == text:
            return tok
    raise AssertionError(f"token {text!r} not found in {[t.text for t in tokens]}")


# (sentence, target_text, expected_translatable, human-readable reason)
CASES: list[tuple[str, str, bool, str]] = [
    # --- PROPN (proper nouns) ----------------------------------------------
    ("Harry whispered.", "Harry", True, "PROPN is in the whitelist"),
    ("Harry whispered.", "whispered", True, "VERB"),
    ("London is big.", "London", True, "PROPN (city name)"),
    ("I met Anna yesterday.", "Anna", True, "PROPN (given name)"),
    # --- NUM (numerals) ----------------------------------------------------
    ("He was 42.", "42", False, "NUM not in whitelist"),
    ("She bought three apples.", "three", False, "NUM not in whitelist"),
    ("Page 10 is missing.", "10", False, "NUM not in whitelist"),
    # --- AUX forms of be / have / do --------------------------------------
    ("I am happy.", "am", False, "AUX form of `be`"),
    ("She is reading.", "is", False, "AUX form of `be`"),
    ("They were silent.", "were", False, "AUX form of `be`"),
    ("He has arrived.", "has", False, "AUX form of `have`"),
    ("I do not know.", "do", False, "AUX form of `do`"),
    ("We were walking.", "walking", True, "VERB content word"),
    # --- Stop-word tokens (pronouns, dets, modals, conjs, preps) ---------
    ("She smiled.", "She", False, "pronoun — STOP_WORDS"),
    ("The cat purred.", "The", False, "determiner — STOP_WORDS"),
    ("A dog barked.", "A", False, "determiner — STOP_WORDS"),
    ("He can swim.", "can", False, "modal — STOP_WORDS"),
    ("I will go.", "will", False, "modal — STOP_WORDS"),
    ("He ran and jumped.", "and", False, "coordinating conj — STOP_WORDS"),
    ("She sat on the chair.", "on", False, "preposition — STOP_WORDS"),
    # --- POS mismatches (PUNCT, SPACE, SYM) -------------------------------
    ("Hello, world.", ",", False, "PUNCT"),
    ("Hello, world.", ".", False, "PUNCT"),
    ("He said: run!", ":", False, "PUNCT"),
    ("Price is $5 today.", "$", False, "SYM"),
    ("The cost: $100.", "$", False, "SYM"),
    # --- Interjections ----------------------------------------------------
    ("Oh, really?", "Oh", False, "INTJ not in whitelist"),
    ("Wow, that is big.", "Wow", False, "INTJ not in whitelist"),
    ("Hey, stop there.", "Hey", False, "INTJ not in whitelist"),
    # --- Content words (positive sanity) ---------------------------------
    ("The cat sat on the mat.", "cat", True, "NOUN"),
    ("The cat sat on the mat.", "sat", True, "VERB"),
    ("An ominous warning.", "ominous", True, "ADJ"),
    ("She ran quickly.", "quickly", True, "ADV"),
]


@pytest.mark.parametrize(
    "sentence,target,expected,reason",
    CASES,
    ids=[f"{s!r}::{t!r}" for s, t, _, _ in CASES],
)
def test_translatable_rule(sentence: str, target: str, expected: bool, reason: str) -> None:
    tokens = tokenize(sentence)
    tok = _by_text(tokens, target)
    assert tok.translatable is expected, (
        f"{target!r} in {sentence!r}: expected translatable={expected} "
        f"({reason}); got {tok.translatable} (POS={tok.pos}, lemma={tok.lemma!r})"
    )
