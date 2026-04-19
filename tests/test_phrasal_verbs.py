"""Tests for the M1.4 phrasal-verb detector.

Covers the cases from the spec section "7. Тесты" in
`tasks/M01-4-phrasal-verbs.md`: contiguous matches, split matches with shared
`pair_id`, the MWE-priority ordering, the prep-verb exclusion, and the global
invariants that no token is claimed by more than one Unit.
"""

from __future__ import annotations

from en_reader.models import Token, Unit
from en_reader.nlp import analyze


def _find(tokens: list[Token], text: str) -> int:
    """Return the index of the first token whose surface form matches `text`."""
    for i, tok in enumerate(tokens):
        if tok.text == text:
            return i
    raise AssertionError(f"token {text!r} not found in {[t.text for t in tokens]}")


def _of_kind(units: list[Unit], kind: str) -> list[Unit]:
    return [u for u in units if u.kind == kind]


def test_contiguous_look_up_the_word() -> None:
    tokens, units = analyze("He looked up the word.")
    phrasal = _of_kind(units, "phrasal")
    assert len(phrasal) == 1, [u.lemma for u in phrasal]
    unit = phrasal[0]
    texts = [tokens[i].text for i in unit.token_ids]
    assert texts == ["looked", "up"]
    assert unit.lemma == "look up"
    assert unit.is_split_pv is False
    assert unit.pair_id is None


def test_split_look_the_word_up() -> None:
    tokens, units = analyze("He looked the word up.")
    split = _of_kind(units, "split_phrasal")
    assert len(split) == 2, [u.lemma for u in split]
    for u in split:
        assert u.is_split_pv is True
        assert u.lemma == "look up"
    assert split[0].pair_id is not None
    assert split[0].pair_id == split[1].pair_id

    verb_idx = _find(tokens, "looked")
    particle_idx = _find(tokens, "up")
    # Identify verb vs particle unit by their single covered token.
    verb_units = [u for u in split if u.token_ids == [verb_idx]]
    particle_units = [u for u in split if u.token_ids == [particle_idx]]
    assert len(verb_units) == 1
    assert len(particle_units) == 1
    assert verb_units[0].lemma == "look up"
    assert particle_units[0].lemma == "look up"
    assert tokens[verb_idx].pair_id == tokens[particle_idx].pair_id
    assert tokens[verb_idx].pair_id is not None


def test_contiguous_give_up_smoking() -> None:
    _tokens, units = analyze("He gave up smoking.")
    phrasal = _of_kind(units, "phrasal")
    assert len(phrasal) == 1
    assert phrasal[0].lemma == "give up"


def test_split_gave_it_up() -> None:
    _tokens, units = analyze("He gave it up.")
    split = _of_kind(units, "split_phrasal")
    assert len(split) == 2
    assert split[0].pair_id is not None
    assert split[0].pair_id == split[1].pair_id
    for u in split:
        assert u.lemma == "give up"


def test_look_at_is_not_phrasal() -> None:
    _tokens, units = analyze("He looked at the book.")
    bad = [u for u in units if u.kind in {"phrasal", "split_phrasal"}]
    assert bad == [], [u.lemma for u in bad]


def test_mwe_and_phrasal_coexist() -> None:
    _tokens, units = analyze("In order to look up the word.")
    mwe = _of_kind(units, "mwe")
    phrasal = _of_kind(units, "phrasal")
    assert len(mwe) == 1, [u.lemma for u in mwe]
    assert len(phrasal) == 1, [u.lemma for u in phrasal]
    assert mwe[0].lemma == "in order to"
    assert phrasal[0].lemma == "look up"
    assert set(mwe[0].token_ids).isdisjoint(set(phrasal[0].token_ids))


def test_split_pair_ids_are_unique() -> None:
    _tokens, units = analyze("She turned the lights off and picked the books up.")
    split = _of_kind(units, "split_phrasal")
    assert len(split) == 4, [u.lemma for u in split]
    pair_ids = [u.pair_id for u in split]
    assert all(pid is not None for pid in pair_ids)
    assert len(set(pair_ids)) == 2
    for pid in set(pair_ids):
        assert pair_ids.count(pid) == 2


def test_no_token_in_two_units_invariant() -> None:
    tokens, units = analyze("In order to look up the word, he gave it up.")

    all_ids: list[int] = []
    for u in units:
        all_ids.extend(u.token_ids)
    assert len(all_ids) == len(set(all_ids)), f"token(s) claimed by multiple Units: {all_ids}"

    by_id = {u.id: u for u in units}
    for i, tok in enumerate(tokens):
        if tok.unit_id is not None:
            assert tok.unit_id in by_id, f"dangling unit_id={tok.unit_id}"
            assert i in by_id[tok.unit_id].token_ids
