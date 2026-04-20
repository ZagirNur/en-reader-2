"""Tests for the M1.3 MWE detector.

Covers the four cases from the spec section "6. Тесты" in
`tasks/M01-3-mwe-detection.md`: two positive matches, one overlap case, and
the invariants (disjoint Units, valid `token.unit_id` back-refs).
"""

from __future__ import annotations

from en_reader.models import Token, Unit
from en_reader.nlp import analyze


def _mwe_units(units: list[Unit]) -> list[Unit]:
    return [u for u in units if u.kind == "mwe"]


def _token_index(tokens: list[Token], text: str, occurrence: int = 0) -> int:
    """Return the index of the n-th token whose surface form matches `text`."""
    seen = 0
    for i, tok in enumerate(tokens):
        if tok.text == text:
            if seen == occurrence:
                return i
            seen += 1
    raise AssertionError(
        f"token {text!r} (occurrence {occurrence}) not found in {[t.text for t in tokens]}"
    )


def test_as_well_as_single_unit() -> None:
    """`as well as` becomes exactly one MWE Unit with token_ids=[1, 2, 3]."""
    tokens, units = analyze("She spoke as well as anyone.")
    mwe_units = _mwe_units(units)
    assert len(mwe_units) == 1, [u.lemma for u in mwe_units]
    unit = mwe_units[0]
    # `She` = 0, `spoke` = 1 — but MWE is `as well as`, starting at index 2 of
    # the spaCy doc (`She`, `spoke`, `as`, `well`, `as`, `anyone`, `.`).
    as1 = _token_index(tokens, "as", 0)
    well = _token_index(tokens, "well")
    as2 = _token_index(tokens, "as", 1)
    assert unit.token_ids == [as1, well, as2]
    # Spec formulates the assertion on the raw positions; make sure they are
    # indeed 2, 3, 4 in the canonical tokenization of this sentence.
    assert [as1, well, as2] == [2, 3, 4]
    assert unit.lemma == "as well as"
    # Covered tokens carry the unit back-reference.
    for i in unit.token_ids:
        assert tokens[i].unit_id == unit.id


def test_in_order_to_case_insensitive() -> None:
    """`In order to` (title-cased, sentence-initial) is matched via LEMMA."""
    tokens, units = analyze("In order to win, he worked hard.")
    mwe_units = _mwe_units(units)
    assert len(mwe_units) == 1
    unit = mwe_units[0]
    assert unit.token_ids == [0, 1, 2]
    assert unit.lemma == "in order to"
    assert tokens[0].unit_id == unit.id
    assert tokens[1].unit_id == unit.id
    assert tokens[2].unit_id == unit.id


def test_non_overlapping_adjacent_mwes() -> None:
    """`in fact in order to` should yield two disjoint Units."""
    tokens, units = analyze("in fact in order to")
    mwe_units = _mwe_units(units)
    assert len(mwe_units) == 2

    all_ids = [tid for u in mwe_units for tid in u.token_ids]
    assert len(all_ids) == len(set(all_ids)), "Unit token_ids must be disjoint"

    lemmas = sorted(u.lemma for u in mwe_units)
    assert lemmas == ["in fact", "in order to"]


def test_invariants_no_double_coverage_and_valid_back_refs() -> None:
    """No token belongs to two Units; every `unit_id` points at a real Unit."""
    text = "In order to succeed, she worked hard; in fact, as well as anyone."
    tokens, units = analyze(text)

    # (1) Disjointness: no token id appears in two Units.
    seen: set[int] = set()
    for unit in units:
        overlap = seen.intersection(unit.token_ids)
        assert not overlap, f"token(s) {overlap} claimed by multiple Units"
        seen.update(unit.token_ids)

    # (2) Back-ref validity: every `token.unit_id` points at a real Unit.id.
    unit_ids = {u.id for u in units}
    assert len(unit_ids) == len(units), "Unit.id values must be unique"
    for tok in tokens:
        if tok.unit_id is not None:
            assert tok.unit_id in unit_ids, f"dangling unit_id={tok.unit_id}"

    # (3) Symmetry: if a token's unit_id is set, that token must be listed in
    # the referenced Unit's token_ids — and vice versa.
    by_id = {u.id: u for u in units}
    for i, tok in enumerate(tokens):
        if tok.unit_id is not None:
            assert i in by_id[tok.unit_id].token_ids
    for unit in units:
        for i in unit.token_ids:
            assert tokens[i].unit_id == unit.id
