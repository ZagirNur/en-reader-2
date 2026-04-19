"""Thin wrapper around spaCy for deterministic tokenization.

Exposes:
* `get_nlp()` — lazy singleton loader of `en_core_web_sm`.
* `tokenize(text)` — runs the pipeline once and returns a lossless `Token` list.
* `mark_translatable(tokens)` — sets `translatable` per the M1.2 rule.
* `mark_mwe(doc, tokens, units)` — detects multi-word expressions and groups
  their tokens into a `Unit(kind="mwe")` per the M1.3 rule.
* `analyze(text)` — orchestration entrypoint that returns `(tokens, units)`.

The model (and the MWE matcher built on top of its vocab) is loaded on first
access only; importing this module must not pay the 1-2 second model-load cost.
"""

from __future__ import annotations

from pathlib import Path

import spacy
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

from .models import Token, Unit

_nlp: spacy.Language | None = None
_stop_words: frozenset[str] | None = None
_mwe_patterns: list[list[str]] | None = None
_mwe_matcher: PhraseMatcher | None = None

_TRANSLATABLE_POS: frozenset[str] = frozenset({"VERB", "NOUN", "ADJ", "ADV", "PROPN"})
_AUX_LEMMAS: frozenset[str] = frozenset({"be", "have", "do"})


def get_nlp() -> spacy.Language:
    """Return the cached spaCy `en_core_web_sm` pipeline, loading it on demand."""
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def _data_dir() -> Path:
    """Locate the project `data/` directory whether installed editable or run from a checkout.

    The file lives at the project root under `data/`. From this module
    (`src/en_reader/nlp.py`) that's two parents up; from an installed-editable
    layout the same relative path holds because editable installs keep the
    source tree in place.
    """
    return Path(__file__).resolve().parent.parent.parent / "data"


def _stop_words_path() -> Path:
    """Path to the curated stop-word list (see M1.2)."""
    return _data_dir() / "stop_words.txt"


def _mwe_path() -> Path:
    """Path to the curated MWE dictionary (see M1.3)."""
    return _data_dir() / "mwe.txt"


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


def _load_mwe() -> list[list[str]]:
    """Load and memoize the curated MWE dictionary from `data/mwe.txt`.

    Each non-comment, non-blank line becomes a list of lowercase tokens split
    on whitespace. Empty tokens are filtered. The result is cached module-wide.
    """
    global _mwe_patterns
    if _mwe_patterns is None:
        path = _mwe_path()
        patterns: list[list[str]] = []
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                words = [w for w in line.lower().split() if w]
                if words:
                    patterns.append(words)
        _mwe_patterns = patterns
    return _mwe_patterns


def _get_mwe_matcher() -> PhraseMatcher:
    """Return the cached `PhraseMatcher` built from the MWE dictionary.

    The matcher keys on ``LEMMA`` so that `makes sense` matches `make sense`.
    Patterns are built by running phrases through the *full* pipeline (via
    ``nlp.pipe``) — ``make_doc`` would leave lemmas empty and defeat the
    matcher. All phrases are piped once in a single batch for efficiency.
    """
    global _mwe_matcher
    if _mwe_matcher is None:
        nlp = get_nlp()
        phrases = [" ".join(words) for words in _load_mwe()]
        matcher = PhraseMatcher(nlp.vocab, attr="LEMMA")
        pattern_docs = list(nlp.pipe(phrases))
        matcher.add("MWE", pattern_docs)
        _mwe_matcher = matcher
    return _mwe_matcher


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


def _tokens_from_doc(doc: Doc) -> list[Token]:
    """Project a spaCy `Doc` to the en-reader `Token` list (M1.1 shape)."""
    return [
        Token(
            text=tok.text,
            lemma=tok.lemma_,
            pos=tok.pos_,
            is_sent_start=bool(tok.is_sent_start) if tok.is_sent_start is not None else False,
            idx_in_text=tok.idx,
        )
        for tok in doc
    ]


def mark_mwe(doc: Doc, tokens: list[Token], units: list[Unit]) -> None:
    """Detect MWEs in `doc`, append `Unit(kind="mwe")` entries, and tag covered tokens.

    Overlap resolution is greedy-longest-first with a first-position tiebreak
    (spaCy's `PhraseMatcher` does not deduplicate overlapping hits for us).
    Per spec §4, tokens absorbed by an MWE keep their existing `translatable`
    flag — grouping happens on the frontend by `unit_id`.
    """
    matcher = _get_mwe_matcher()
    # Matches come back as (match_id, start, end) with end exclusive.
    raw_matches = matcher(doc)
    # Greedy-longest-first, first-position tiebreak.
    raw_matches.sort(key=lambda m: (-(m[2] - m[1]), m[1]))

    taken: set[int] = set()
    next_id = max((u.id for u in units), default=-1) + 1
    for _match_id, start, end in raw_matches:
        span_indices = range(start, end)
        if any(i in taken for i in span_indices):
            continue
        token_ids = list(span_indices)
        lemma = " ".join(doc[i].lemma_.lower() for i in token_ids)
        unit = Unit(id=next_id, token_ids=token_ids, lemma=lemma, kind="mwe")
        units.append(unit)
        for i in token_ids:
            tokens[i].unit_id = unit.id
            taken.add(i)
        next_id += 1


def analyze(text: str) -> tuple[list[Token], list[Unit]]:
    """Run the full M1.1 + M1.2 + M1.3 pipeline over `text`.

    Returns ``(tokens, units)``: a lossless `Token` list with `translatable`
    and `unit_id` populated, plus the list of `Unit(kind="mwe")` entries
    produced by the MWE matcher.
    """
    nlp = get_nlp()
    doc = nlp(text)
    tokens = _tokens_from_doc(doc)
    mark_translatable(tokens)
    units: list[Unit] = []
    mark_mwe(doc, tokens, units)
    return tokens, units


def tokenize(text: str) -> list[Token]:
    """Tokenize `text` losslessly, preserving punctuation and whitespace tokens.

    Returns one `Token` per spaCy token. `translatable` is set per the M1.2
    rule; `unit_id` and `pair_id` stay at their defaults — use `analyze()` to
    get MWE-aware `Unit`s alongside the tokens.
    """
    nlp = get_nlp()
    doc = nlp(text)
    tokens = _tokens_from_doc(doc)
    mark_translatable(tokens)
    return tokens
