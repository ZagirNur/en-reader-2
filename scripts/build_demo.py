"""Seed demo pipeline: read .txt → analyze + chunk → write `demo.json`.

Temporary glue for M3-M4 so the frontend has a single static asset to load
without a DB. Will be replaced by a real books API in M8.

Usage::

    python scripts/build_demo.py tests/fixtures/golden/01-simple.txt
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from en_reader.chunker import chunk
from en_reader.nlp import analyze

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_PATH = _REPO_ROOT / "src" / "en_reader" / "static" / "demo.json"


def _resolve_input(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def main(path: str) -> Path:
    """Build `demo.json` from the given text file and return the output path."""
    input_path = _resolve_input(path)
    text = input_path.read_text(encoding="utf-8")

    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)

    payload = {
        "total_pages": len(pages),
        "pages": [asdict(page) for page in pages],
    }

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return _OUTPUT_PATH


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_demo.py <path-to-txt>", file=sys.stderr)
        sys.exit(2)
    out = main(sys.argv[1])
    print(f"wrote {out}")
