"""Thin wrapper around spaCy for deterministic tokenization.

Exposes:
* `get_nlp()` — lazy singleton loader of `en_core_web_sm`.
* `tokenize(text)` — runs the pipeline once and returns lossless `Token` list.
* `mark_translatable(tokens)` — sets `translatable` per the M1.2 rule.

The model is loaded on first access only; importing this module must not pay
the 1-2 second model-load cost (see acceptance: `nlp._nlp is None` right after
import).
"""

from __future__ import annotations

from pathlib import Path

import spacy

from .models import Token

_nlp: spacy.Language | None = None
_stop_words: frozenset[str] | None = None

_TRANSLATABLE_POS: frozenset[str] = frozenset({"VERB", "NOUN", "ADJ", "ADV", "PROPN"})
_AUX_LEMMAS: frozenset[str] = frozenset({"be", "have", "do"})


def get_nlp() -> spacy.Language:
    """Return the cached spaCy `en_core_web_sm` pipeline, loading it on demand."""
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def _stop_words_path() -> Path:
    """Locate `data/stop_words.txt` whether installed editable or run from a checkout.

    The file lives at the project root under `data/`. From this module
    (`src/en_reader/nlp.py`) that's two parents up; from an installed-editable
    layout the same relative path holds because editable installs keep the
    source tree in place.
    """
    return Path(__file__).resolve().parent.parent.parent / "data" / "stop_words.txt"


def _load_stop_words() -> frozenset[str]:
    """Load and memoize the curated STOP_WORDS set from `data/stop_words.txt`.

    Lines are stripped and lowercased; blank lines and `#...` comments are
    dropped. The result is cached in module-level `_stop_words` so subsequent
    calls are O(1).
    """
    global _stop_words
    if _stop_words is None:
        path = _stop_words_path()
        words: set[str] = set()
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                words.add(line.lower())
        _stop_words = frozenset(words)
    return _stop_words


def mark_translatable(tokens: list[Token]) -> None:
    """Set `translatable` on each token in place per the M1.2 rule.

    A token is translatable iff ALL of:
      a) `pos` is one of VERB / NOUN / ADJ / ADV / PROPN;
      b) `lemma.lower()` is not in STOP_WORDS;
      c) not an AUX form of `be` / `have` / `do` (explicit guard — redundant
         with STOP_WORDS today, but spaCy occasionally mislabels these as VERB
         and the spec asks for the belt-and-braces check).
    """
    stop_words = _load_stop_words()
    for token in tokens:
        lemma_lc = token.lemma.lower()
        if token.pos not in _TRANSLATABLE_POS:
            token.translatable = False
            continue
        if lemma_lc in stop_words:
            token.translatable = False
            continue
        if lemma_lc in _AUX_LEMMAS and token.pos == "AUX":
            token.translatable = False
            continue
        token.translatable = True


def tokenize(text: str) -> list[Token]:
    """Tokenize `text` losslessly, preserving punctuation and whitespace tokens.

    Returns one `Token` per spaCy token. `translatable` is set per the M1.2
    rule; `unit_id` and `pair_id` stay at their defaults for later milestones.
    """
    nlp = get_nlp()
    doc = nlp(text)
    tokens: list[Token] = []
    for tok in doc:
        tokens.append(
            Token(
                text=tok.text,
                lemma=tok.lemma_,
                pos=tok.pos_,
                is_sent_start=bool(tok.is_sent_start) if tok.is_sent_start is not None else False,
                idx_in_text=tok.idx,
            )
        )
    mark_translatable(tokens)
    return tokens
