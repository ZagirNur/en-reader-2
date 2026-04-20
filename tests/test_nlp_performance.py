"""M15.1 — performance baseline for the NLP pipeline.

Runs ``analyze()`` on the long-form fixture (~5.9k words, built in M1.5 from
five golden passages concatenated 12 times) and asserts the whole pipeline
finishes well under a coarse wall-clock ceiling. The bound is loose on
purpose — the goal is to catch accidental algorithmic regressions (O(n²) in
a newly-added pass, model reload in a hot loop, …), not to enforce micro-
benchmark stability.
"""

from __future__ import annotations

import time
from pathlib import Path

from en_reader.nlp import analyze, get_nlp

FIXTURES = Path(__file__).parent / "fixtures"


def test_analyze_long_fixture_under_10s() -> None:
    # Preload the spaCy model so the measured window excludes first-load cost.
    get_nlp()

    text = (FIXTURES / "long.txt").read_text(encoding="utf-8")
    # Sanity-check the fixture didn't shrink under us.
    assert len(text.split()) >= 1000, len(text.split())

    start = time.perf_counter()
    tokens, units = analyze(text)
    duration = time.perf_counter() - start

    assert duration < 10.0, f"analyze({len(text)} chars) took {duration:.2f}s"
    assert tokens, "expected non-empty token list"
    # Smoke-check: every token's idx_in_text is monotonically non-decreasing.
    last = -1
    for t in tokens:
        assert t.idx_in_text >= last
        last = t.idx_in_text
    # We produced at least a few units from a 5000-word text.
    assert units, "expected at least one Unit on long fixture"
