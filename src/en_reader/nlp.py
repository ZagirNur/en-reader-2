"""Thin wrapper around spaCy for deterministic tokenization.

Exposes:
* `get_nlp()` — lazy singleton loader of `en_core_web_sm`.
* `tokenize(text)` — runs the pipeline once and returns lossless `Token` list.

The model is loaded on first access only; importing this module must not pay
the 1-2 second model-load cost (see acceptance: `nlp._nlp is None` right after
import).
"""

from __future__ import annotations

import spacy

from .models import Token

_nlp: spacy.Language | None = None


def get_nlp() -> spacy.Language:
    """Return the cached spaCy `en_core_web_sm` pipeline, loading it on demand."""
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def tokenize(text: str) -> list[Token]:
    """Tokenize `text` losslessly, preserving punctuation and whitespace tokens.

    Returns one `Token` per spaCy token. `translatable`, `unit_id`, and
    `pair_id` stay at their defaults; later milestones fill them in.
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
    return tokens
