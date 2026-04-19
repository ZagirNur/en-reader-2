"""In-memory user dictionary for the en-reader dev server (M5.1).

A single-process, global ``lemma -> translation`` map. Lemmas are normalized
to lowercase before use as a key, so ``"Ominous"``, ``"ominous"``, and
``"OMINOUS"`` all collapse to the single entry ``"ominous"``.

Scope is deliberately minimal:

* No persistence — the dict is reset on every server restart. M6.1 replaces
  this with SQLite-backed storage using the same call shape.
* No ``user_id`` — there is one shared dictionary per process. M11.1 will
  introduce per-user scoping.
* No thread-safety primitives — uvicorn runs a single worker in dev, and
  Python's GIL makes dict mutations effectively atomic for our use.

Public API mirrors what a future DAO will expose so the FastAPI routes do
not need to change when storage moves: :func:`add`, :func:`remove`,
:func:`get`, :func:`all_items`, :func:`clear`.
"""

from __future__ import annotations

_dict: dict[str, str] = {}


def add(lemma: str, translation: str) -> None:
    """Upsert ``translation`` under the lowercased ``lemma`` key."""
    _dict[lemma.lower()] = translation


def remove(lemma: str) -> bool:
    """Remove the entry for ``lemma`` (case-insensitive). Return True if present."""
    return _dict.pop(lemma.lower(), None) is not None


def get(lemma: str) -> str | None:
    """Return the translation for ``lemma`` (case-insensitive), or None."""
    return _dict.get(lemma.lower())


def all_items() -> dict[str, str]:
    """Return a shallow copy of the dictionary so callers can't mutate state."""
    return dict(_dict)


def clear() -> None:
    """Drop every entry. Primarily for tests."""
    _dict.clear()
