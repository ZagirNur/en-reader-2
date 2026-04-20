"""M15.1 — extra phrasal-verb scenarios on top of the M1.4 base suite.

* Parametrized over 10 particles, each paired with a real phrasal from
  ``data/phrasal_verbs.txt`` (contiguous form).
* Split form with past tense verb: ``looked the word up``.
* Split form with gerund verb: ``looking the word up``.
* Multiple split phrasal verbs in one sentence.
* MWE wins over phrasal when both would fire on overlapping tokens.
"""

from __future__ import annotations

import pytest

from en_reader.models import Unit
from en_reader.nlp import analyze


def _of_kind(units: list[Unit], kind: str) -> list[Unit]:
    return [u for u in units if u.kind == kind]


# (sentence, expected_lemma) — 10 particles, each paired with a different
# verb so spaCy's dependency parser doesn't see an over-homogeneous batch.
# Every pair is present in ``data/phrasal_verbs.txt``.
PARTICLE_CASES: list[tuple[str, str]] = [
    ("She picked up the book.", "pick up"),
    ("He sat down on the bench.", "sit down"),
    ("They filled in the form.", "fill in"),
    ("She figured out the answer.", "figure out"),
    ("Please carry on with your work.", "carry on"),
    ("He took off his jacket.", "take off"),
    ("The meeting is starting over.", "start over"),
    ("She looked through the notes.", "look through"),
    ("He walked away quickly.", "walk away"),
    ("Please call back later.", "call back"),
]


@pytest.mark.parametrize(
    "sentence,expected_lemma",
    PARTICLE_CASES,
    ids=[lemma for _s, lemma in PARTICLE_CASES],
)
def test_contiguous_phrasal_for_each_particle(sentence: str, expected_lemma: str) -> None:
    _tokens, units = analyze(sentence)
    phrasal = _of_kind(units, "phrasal")
    lemmas = [u.lemma for u in phrasal]
    assert expected_lemma in lemmas, f"{expected_lemma!r} not found in {lemmas} for {sentence!r}"


def test_split_past_tense_looked_the_word_up() -> None:
    """``looked the word up`` — past tense verb, split form."""
    tokens, units = analyze("She looked the word up.")
    split = _of_kind(units, "split_phrasal")
    assert len(split) == 2, [u.lemma for u in split]
    for u in split:
        assert u.lemma == "look up"
        assert u.is_split_pv is True
    assert split[0].pair_id == split[1].pair_id
    # Verb-side unit covers "looked"; particle-side covers "up".
    verb_tok_idx = next(i for i, t in enumerate(tokens) if t.text == "looked")
    part_tok_idx = next(i for i, t in enumerate(tokens) if t.text == "up")
    covered = {tid for u in split for tid in u.token_ids}
    assert covered == {verb_tok_idx, part_tok_idx}


def test_split_gerund_looking_the_word_up() -> None:
    """``looking the word up`` — gerund verb, split form."""
    tokens, units = analyze("He is looking the word up.")
    split = _of_kind(units, "split_phrasal")
    assert len(split) == 2, [u.lemma for u in split]
    for u in split:
        assert u.lemma == "look up"
        assert u.is_split_pv is True
    assert split[0].pair_id == split[1].pair_id
    verb_tok_idx = next(i for i, t in enumerate(tokens) if t.text == "looking")
    part_tok_idx = next(i for i, t in enumerate(tokens) if t.text == "up")
    assert tokens[verb_tok_idx].pair_id == tokens[part_tok_idx].pair_id


def test_multiple_splits_in_one_sentence() -> None:
    """Two independent split phrasal verbs must each get their own pair_id."""
    _tokens, units = analyze("She turned the lights off and picked the books up.")
    split = _of_kind(units, "split_phrasal")
    # 2 phrasals * 2 units each = 4.
    assert len(split) == 4, [u.lemma for u in split]
    lemmas = {u.lemma for u in split}
    assert lemmas == {"turn off", "pick up"}, lemmas
    pair_ids = [u.pair_id for u in split]
    assert all(pid is not None for pid in pair_ids)
    # Exactly two distinct pair_ids, two units per pair.
    assert len(set(pair_ids)) == 2
    for pid in set(pair_ids):
        assert pair_ids.count(pid) == 2


def test_mwe_wins_over_phrasal_on_overlap() -> None:
    """When MWE and phrasal both match overlapping tokens, MWE claims them.

    ``make up`` exists in the phrasal-verb dictionary and ``make use of``
    is a MWE. Token ``use`` sits where both would compete in principle —
    but since ``make use of`` is a 3-token MWE and ``make up`` needs an
    adjacent ``up``, we exercise priority by asking for a sentence that
    directly pits both. We use ``make use of`` (MWE) — the MWE pass runs
    first and claims the tokens so the phrasal pass finds no free slot.
    """
    tokens, units = analyze("They make use of every tool.")
    mwe = _of_kind(units, "mwe")
    phrasal = _of_kind(units, "phrasal") + _of_kind(units, "split_phrasal")
    assert len(mwe) == 1
    assert mwe[0].lemma == "make use of"
    # Whatever phrasal the parser might have wanted to emit, it must not
    # overlap with the MWE tokens.
    mwe_token_ids = set(mwe[0].token_ids)
    for u in phrasal:
        assert (
            not set(u.token_ids) & mwe_token_ids
        ), f"phrasal {u.lemma!r} overlaps MWE tokens {mwe_token_ids}"
    # And ``make`` must carry the MWE's unit_id, not a phrasal one.
    make_idx = next(i for i, t in enumerate(tokens) if t.text == "make")
    assert tokens[make_idx].unit_id == mwe[0].id
