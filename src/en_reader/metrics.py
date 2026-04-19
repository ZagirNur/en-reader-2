"""Lightweight in-memory counters for observability (M6.2, expanded in M14.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Counters:
    translate_hit: int = 0
    translate_miss: int = 0


counters = Counters()
