"""M15.1 — additional MWE detection scenarios beyond the M1.3 base suite.

Adds:
* Two MWEs in one sentence with no overlap.
* MWE that begins at sentence start.
* Incomplete match (``in order`` without ``to``) — not a MWE.
* Lemma normalisation: ``makes sense`` should match the dictionary entry
  ``make sense``.
"""

from __future__ import annotations

from en_reader.models import Unit
from en_reader.nlp import analyze


def _mwe(units: list[Unit]) -> list[Unit]:
    return [u for u in units if u.kind == "mwe"]


def test_two_mwes_one_sentence_no_overlap() -> None:
    """Two disjoint MWEs fire in a single sentence."""
    tokens, units = analyze("In fact, she came in front of the crowd.")
    mwe = _mwe(units)
    lemmas = sorted(u.lemma for u in mwe)
    assert lemmas == ["in fact", "in front of"], lemmas
    # Disjointness.
    all_ids = [tid for u in mwe for tid in u.token_ids]
    assert len(all_ids) == len(set(all_ids))
    # Every covered token back-references its unit.
    for u in mwe:
        for i in u.token_ids:
            assert tokens[i].unit_id == u.id


def test_mwe_at_sentence_start() -> None:
    """MWE starting at position 0 (right after ``is_sent_start=True``)."""
    tokens, units = analyze("In order to win, she trained daily.")
    mwe = _mwe(units)
    assert len(mwe) == 1
    unit = mwe[0]
    assert unit.lemma == "in order to"
    assert unit.token_ids[0] == 0
    assert tokens[0].is_sent_start is True


def test_incomplete_match_in_order_without_to_is_not_mwe() -> None:
    """``in order`` (without ``to``) must NOT be matched — no prefix fallback."""
    _tokens, units = analyze("The items are in order today.")
    mwe = _mwe(units)
    # No MWE whose lemma starts with "in order" should fire here.
    lemmas = [u.lemma for u in mwe]
    assert not any(lm.startswith("in order") for lm in lemmas), lemmas


def test_lemma_normalisation_makes_sense() -> None:
    """``makes sense`` (inflected surface) should match dictionary ``make sense``."""
    tokens, units = analyze("That makes sense.")
    mwe = _mwe(units)
    assert len(mwe) == 1, [u.lemma for u in mwe]
    unit = mwe[0]
    assert unit.lemma == "make sense"
    # token_ids should cover both surface tokens of the MWE.
    texts = [tokens[i].text for i in unit.token_ids]
    assert texts == ["makes", "sense"]


def test_lemma_normalisation_took_care() -> None:
    """``took care`` (past) — matches ``take care``."""
    tokens, units = analyze("She took care of the details.")
    mwe = _mwe(units)
    # Both "take care" and "take care of" are in the dictionary — greedy-longest
    # should prefer the 3-token variant.
    assert len(mwe) >= 1
    # The selected unit must cover "took" + "care" (+ optionally "of") and its
    # lemma must be the normalised form.
    lemmas = {u.lemma for u in mwe}
    assert lemmas & {"take care", "take care of"}, lemmas
    for u in mwe:
        texts = [tokens[i].text.lower() for i in u.token_ids]
        assert texts[0] == "took"
        assert texts[1] == "care"
