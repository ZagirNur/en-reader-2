"""Golden-fixture tests for the NLP pipeline (M1.5).

Every ``NN-name.txt`` under ``tests/fixtures/golden/`` is paired with an
``NN-name.golden.json`` snapshot. The test runs `analyze(text)` through the
current pipeline, serializes the result via
`en_reader.serialize.tokens_units_to_dict`, and compares to the snapshot.

Pass ``--update-golden`` to rewrite the ``.golden.json`` files from the live
output (used after an intentional pipeline change; inspect the git diff
before committing).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from en_reader.nlp import analyze
from en_reader.serialize import tokens_units_to_dict

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


def _discover_text_paths() -> list[Path]:
    """Return every ``NN-*.txt`` fixture in deterministic order."""
    return sorted(GOLDEN_DIR.glob("*.txt"))


def _serialize(text: str) -> str:
    """Render the pipeline output for `text` as the canonical golden string."""
    tokens, units = analyze(text)
    data = tokens_units_to_dict(tokens, units)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize(
    "text_path",
    _discover_text_paths(),
    ids=lambda p: p.stem,
)
def test_golden(text_path: Path, update_golden: bool) -> None:
    """Pipeline output for `text_path` matches the on-disk golden snapshot."""
    text = text_path.read_text(encoding="utf-8")
    actual_str = _serialize(text)
    golden_path = text_path.with_suffix(".golden.json")

    if update_golden:
        golden_path.write_text(actual_str, encoding="utf-8")
        pytest.skip(f"golden updated: {golden_path.name}")

    assert golden_path.exists(), f"missing golden fixture: {golden_path}"
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    actual = json.loads(actual_str)
    assert actual == expected
