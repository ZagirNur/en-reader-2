"""Greedy sentence-boundary page chunker for the reader frontend.

Exposes:
* `chunk(tokens, units, full_text)` — pack tokens into `Page`s sized 100-1000
  English words, never splitting a sentence. Returns a list of self-contained
  `Page`s whose `idx_in_text` and `unit.token_ids` are rebased to the page.

The algorithm is a simple greedy packer: walk sentence by sentence (delimited
by `is_sent_start=True`), accumulate into a buffer, and close the page at the
first sentence boundary past 100 words, or just before a sentence that would
push the buffer over 1000 words. A lone sentence longer than 1000 words
becomes its own (oversized) page with a warning. The final buffer is flushed
as the last page regardless of size.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from .models import Page, Token, Unit

logger = logging.getLogger(__name__)

_MIN_WORDS: int = 100
_MAX_WORDS: int = 1000

_WORD_POS: frozenset[str] = frozenset(
    {"VERB", "NOUN", "ADJ", "ADV", "PROPN", "PRON", "DET", "ADP", "AUX", "NUM", "INTJ"}
)


def _sentences(tokens: list[Token]) -> list[tuple[int, int, int, bool]]:
    """Split `tokens` into sentence spans.

    Returns a list of ``(start_idx, end_idx_exclusive, word_count, para_end)``
    tuples where each span starts on an `is_sent_start=True` token and ends
    just before the next one (or at the end of `tokens`). ``word_count`` counts
    tokens whose `pos` is in `_WORD_POS`. ``para_end`` is ``True`` when the
    sentence's trailing whitespace includes a blank line (``\\n\\n``) — spaCy
    absorbs such runs into a trailing ``SPACE`` token, so we check the last
    token's text. Paragraph-terminal sentences are preferred page-break
    points; closing a page there preserves the ``"\\n\\n".join`` reconstruction
    invariant for well-formatted multi-paragraph input.
    """
    spans: list[tuple[int, int, int, bool]] = []
    if not tokens:
        return spans
    start = 0
    # Defensive: the first token should be a sentence start, but if spaCy
    # didn't mark it we still treat position 0 as the opening boundary.
    for i in range(1, len(tokens)):
        if tokens[i].is_sent_start:
            wc = sum(1 for t in tokens[start:i] if t.pos in _WORD_POS)
            para_end = "\n\n" in tokens[i - 1].text
            spans.append((start, i, wc, para_end))
            start = i
    wc = sum(1 for t in tokens[start:] if t.pos in _WORD_POS)
    para_end = "\n\n" in tokens[-1].text
    spans.append((start, len(tokens), wc, para_end))
    return spans


def _pack(sentences: list[tuple[int, int, int, bool]]) -> list[tuple[int, int]]:
    """Greedy-pack sentences into page token ranges ``(start, end_exclusive)``.

    Accumulates sentences while the buffer has < `_MIN_WORDS`; once at or
    above the floor, prefers to close at a paragraph-terminal sentence so
    that page gaps in the original text contain the ``\\n\\n`` we later
    rejoin on. If no paragraph break arrives before the buffer would exceed
    `_MAX_WORDS`, closes mid-paragraph to stay within the ceiling. A lone
    sentence longer than `_MAX_WORDS` is emitted as its own page with a
    warning.
    """
    pages: list[tuple[int, int]] = []
    if not sentences:
        return pages

    buf_start: int | None = None
    buf_end: int = 0
    buf_words: int = 0

    for sent_start, sent_end, sent_words, para_end in sentences:
        if buf_start is None:
            # Empty buffer — take the sentence. If it's oversized on its own,
            # flush immediately as a standalone page with a warning.
            buf_start, buf_end, buf_words = sent_start, sent_end, sent_words
            if buf_words > _MAX_WORDS:
                logger.warning("Oversized page: %d words", buf_words)
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0
            elif buf_words >= _MIN_WORDS and para_end:
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0
            continue

        if buf_words < _MIN_WORDS:
            # Below floor — keep growing regardless of overshoot risk.
            buf_end = sent_end
            buf_words += sent_words
            if buf_words > _MAX_WORDS:
                # A huge sentence dragged us past the ceiling before we hit
                # the floor; flush the oversized page so ≤1000 stays the
                # invariant everywhere else.
                logger.warning("Oversized page: %d words", buf_words)
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0
            elif buf_words >= _MIN_WORDS and para_end:
                # Flush on paragraph end if we crossed the floor by adding
                # this sentence; otherwise we'd never close small-paragraph
                # pages.
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0
            continue

        # At or above floor: decide whether to admit the next sentence.
        if buf_words + sent_words > _MAX_WORDS:
            # Close before the sentence that would overflow.
            pages.append((buf_start, buf_end))
            buf_start, buf_end, buf_words = sent_start, sent_end, sent_words
            if buf_words > _MAX_WORDS:
                logger.warning("Oversized page: %d words", buf_words)
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0
            elif buf_words >= _MIN_WORDS and para_end:
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0
        else:
            buf_end = sent_end
            buf_words += sent_words
            # Prefer paragraph-terminal break once we've cleared the floor.
            if para_end:
                pages.append((buf_start, buf_end))
                buf_start, buf_end, buf_words = None, 0, 0

    if buf_start is not None:
        pages.append((buf_start, buf_end))

    return pages


def chunk(tokens: list[Token], units: list[Unit], full_text: str) -> list[Page]:
    """Slice an analyzed text into sentence-bounded `Page`s of 100-1000 words.

    Walks sentences (runs of tokens opened by `is_sent_start=True`) and packs
    them greedily: accumulate until the buffer hits 100 "words" (tokens whose
    `pos` is content-bearing per `_WORD_POS`), then close the page before any
    sentence that would push it past 1000. A standalone sentence over 1000
    words becomes its own oversized page with a warning. The final buffer is
    always emitted even if it's under the minimum.

    `Page.text` is `full_text` sliced from the first token's `idx_in_text` to
    the last token's end, rstripped. `Page.tokens` are deep copies with
    `idx_in_text` rebased to the page start. `Page.units` keep only units
    whose tokens all fell into the page; their `token_ids` are remapped to
    local positions. A unit whose tokens span a page boundary is dropped with
    a warning, and its referencing tokens get `unit_id`/`pair_id` cleared so
    the page is self-consistent.
    """
    if not tokens:
        return []

    sentences = _sentences(tokens)
    ranges = _pack(sentences)
    if not ranges:
        return []

    # Map each global token index to the page index it ended up in, so we can
    # decide per-Unit whether all its tokens landed in the same page.
    global_to_page: dict[int, int] = {}
    for p_idx, (g_start, g_end) in enumerate(ranges):
        for g in range(g_start, g_end):
            global_to_page[g] = p_idx

    pages: list[Page] = []
    for p_idx, (g_start, g_end) in enumerate(ranges):
        first_tok = tokens[g_start]
        last_tok = tokens[g_end - 1]
        page_start_char = first_tok.idx_in_text
        page_end_char = last_tok.idx_in_text + len(last_tok.text)
        page_text = full_text[page_start_char:page_end_char].rstrip()
        # Any trailing whitespace-only tokens (spaCy's `SPACE` with "\n\n" etc.)
        # now sit past the rstripped boundary; filter them out so every kept
        # token's rebased `idx_in_text + len(text)` fits within `page_text`.
        effective_end_char = page_start_char + len(page_text)
        kept_globals = [
            g
            for g in range(g_start, g_end)
            if tokens[g].idx_in_text + len(tokens[g].text) <= effective_end_char
        ]

        # Deep-copy tokens with rebased idx_in_text.
        page_tokens: list[Token] = [
            replace(tokens[g], idx_in_text=tokens[g].idx_in_text - page_start_char)
            for g in kept_globals
        ]
        # Global -> local token index map for Unit remapping.
        g_to_local: dict[int, int] = {g: local for local, g in enumerate(kept_globals)}

        # Partition units by whether all their token_ids live in this page.
        page_units: list[Unit] = []
        for u in units:
            if not u.token_ids:
                continue
            pages_touched = {global_to_page.get(t) for t in u.token_ids}
            all_kept = all(t in g_to_local for t in u.token_ids)
            if len(pages_touched) == 1 and p_idx in pages_touched and all_kept:
                local_ids = [g_to_local[t] for t in u.token_ids]
                page_units.append(replace(u, token_ids=local_ids))
            elif p_idx in pages_touched and len(pages_touched) > 1:
                # Unit straddles a page boundary — drop it, but only log once
                # (we'll hit this same unit from each page it touches; logging
                # once per page it touched is acceptable but noisy, so gate on
                # the first page we see it from).
                first_page_touched = min(gp for gp in pages_touched if gp is not None)
                if first_page_touched == p_idx:
                    logger.warning("Dropped split PV across page boundary")
                # Clear dangling references on this page's tokens.
                for t_global in u.token_ids:
                    if t_global in g_to_local:
                        local = g_to_local[t_global]
                        page_tokens[local] = replace(page_tokens[local], unit_id=None, pair_id=None)

        pages.append(
            Page(
                page_index=p_idx,
                text=page_text,
                tokens=page_tokens,
                units=page_units,
            )
        )

    return pages
