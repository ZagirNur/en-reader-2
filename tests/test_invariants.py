"""Structural invariants checked against a long real-world-shaped text (M1.5).

Unlike the golden tests, this file does not pin the exact markup — it asserts
the four properties that must hold for any input the pipeline is asked to
analyze: lossless concatenation, Unit disjointness, sentence-start counts,
and split-phrasal pair_id pairing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from en_reader.models import Token, Unit
from en_reader.nlp import analyze, get_nlp

LONG_FIXTURE = Path(__file__).parent / "fixtures" / "long.txt"


@pytest.fixture(scope="module")
def long_text() -> str:
    return LONG_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def analyzed(long_text: str) -> tuple[list[Token], list[Unit]]:
    return analyze(long_text)


def test_lossless_concat(long_text: str, analyzed: tuple[list[Token], list[Unit]]) -> None:
    tokens, _units = analyzed
    assert tokens, "pipeline produced no tokens for the long fixture"

    parts: list[str] = [long_text[: tokens[0].idx_in_text], tokens[0].text]
    for prev, curr in zip(tokens, tokens[1:]):
        gap_start = prev.idx_in_text + len(prev.text)
        parts.append(long_text[gap_start : curr.idx_in_text])
        parts.append(curr.text)
    last = tokens[-1]
    parts.append(long_text[last.idx_in_text + len(last.text) :])

    assert "".join(parts) == long_text


def test_units_are_disjoint(analyzed: tuple[list[Token], list[Unit]]) -> None:
    _tokens, units = analyzed
    seen: set[int] = set()
    for u in units:
        overlap = seen.intersection(u.token_ids)
        assert not overlap, f"Unit {u.id} ({u.kind}) overlaps on tokens {sorted(overlap)}"
        seen.update(u.token_ids)


def test_sentence_starts_match_spacy(
    long_text: str, analyzed: tuple[list[Token], list[Unit]]
) -> None:
    tokens, _units = analyzed
    starts = sum(1 for t in tokens if t.is_sent_start)
    expected = sum(1 for _ in get_nlp()(long_text).sents)
    assert starts == expected


def test_pair_ids_are_split_phrasal_pairs(analyzed: tuple[list[Token], list[Unit]]) -> None:
    _tokens, units = analyzed
    by_pair: dict[int, list[Unit]] = {}
    for u in units:
        if u.pair_id is not None:
            by_pair.setdefault(u.pair_id, []).append(u)

    for pair_id, group in by_pair.items():
        assert len(group) == 2, f"pair_id {pair_id} covered {len(group)} Units, expected 2"
        for u in group:
            assert u.kind == "split_phrasal", f"pair_id {pair_id} on non-split Unit: {u}"
            assert u.is_split_pv is True, f"pair_id {pair_id} Unit missing is_split_pv: {u}"
