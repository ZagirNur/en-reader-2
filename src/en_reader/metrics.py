"""Lightweight in-memory counters for observability (M6.2, expanded in M14.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Counters:
    # M6.2: per-user-dictionary outcomes of /api/translate. ``hit`` is an
    # existing dict row, ``miss`` is a fresh insert.
    translate_hit: int = 0
    translate_miss: int = 0
    # M19.7: prompt-hash ``llm_cache`` outcomes inside ``translate_one``.
    # ``llm_cache_hit`` means we skipped the Gemini round-trip entirely;
    # ``llm_cache_miss`` means we actually called Gemini. Useful to
    # observe how much budget the cache is saving — watching
    # /debug/health while reading a book shows these climbing in lock-
    # step with reader activity.
    llm_cache_hit: int = 0
    llm_cache_miss: int = 0


counters = Counters()
