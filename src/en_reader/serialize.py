"""JSON-ready serialization of `(tokens, units)` for golden fixtures.

Kept deliberately small: one helper used by both the golden-test runner and
any one-off script that wants to dump a stable, diff-friendly snapshot. Units
are sorted by ``(token_ids[0], id)`` so the output order is independent of
the pipeline's internal production order.
"""

from __future__ import annotations

from dataclasses import asdict

from .models import Token, Unit


def tokens_units_to_dict(tokens: list[Token], units: list[Unit]) -> dict:
    """Return a JSON-ready dict with `tokens` and (sorted) `units` lists."""
    sorted_units = sorted(units, key=lambda u: (u.token_ids[0] if u.token_ids else -1, u.id))
    return {
        "tokens": [asdict(tok) for tok in tokens],
        "units": [asdict(u) for u in sorted_units],
    }
