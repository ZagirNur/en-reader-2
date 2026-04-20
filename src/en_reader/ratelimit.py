"""Generic in-memory sliding-window rate limiter (M14.3).

Used to cap the two expensive POST routes:

* ``/api/translate`` — 60 hits / user / 60 s (a wedged "Enter held down"
  translation key can otherwise burn the Gemini budget in seconds).
* ``/api/books/upload`` — 5 hits / user / 3600 s (each upload triggers
  a parse + NLP pipeline + disk write; a misbehaving client shouldn't
  be allowed to run that loop hundreds of times per hour).

The auth rate limit (10 hits / IP / 60 s) lives on
:class:`en_reader.auth.AuthRateLimit` and is intentionally *not*
re-implemented here — the spec (§1) says "don't duplicate".

Design is deliberately minimal:

* One ``dict[key, list[float]]`` per limiter, pruned on every ``check``.
* ``threading.Lock`` around the read-modify-write so the limiter behaves
  correctly under a multi-threaded ASGI worker. CPython's GIL already
  makes single-statement dict mutations atomic, but the prune/append
  sequence isn't one statement, so we take the lock explicitly.
* No Redis, no periodic GC — single process, single worker. ``_hits``
  grows with the number of distinct keys seen, which is bounded by
  user count in practice; acceptable for MVP.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock


class RateLimit:
    """Sliding-window limiter: ``max_hits`` per ``window_seconds`` per key.

    Call :meth:`check` with a stable bucket key (user id, IP, etc.); it
    returns ``True`` if the request is allowed (and records the hit) or
    ``False`` once the bucket is full. Rejected hits are **not** recorded
    so the window naturally empties out after a quiet period.
    """

    def __init__(self, max_hits: int, window_seconds: int) -> None:
        self.max = max_hits
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    @property
    def window(self) -> int:
        """Window length in seconds — used to fill the ``Retry-After`` header."""
        return self._window

    def check(self, key: str) -> bool:
        """Record a hit for ``key`` and return whether it's within the limit.

        Prunes stale timestamps (older than the window) on every call.
        Returns ``False`` once the bucket already holds ``max`` fresh
        hits; the caller is responsible for translating that into a 429.
        """
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            fresh = [t for t in self._hits[key] if t >= cutoff]
            if len(fresh) >= self.max:
                self._hits[key] = fresh
                return False
            fresh.append(now)
            self._hits[key] = fresh
            return True

    def reset(self) -> None:
        """Drop all buckets — test helper, not meant for production use."""
        with self._lock:
            self._hits.clear()


# Module-level singletons wired into app.py. Tests reset these between
# cases via an autouse fixture in conftest so a flood in one test doesn't
# leak hits into the next.
rl_translate = RateLimit(max_hits=60, window_seconds=60)  # per user
rl_upload = RateLimit(max_hits=5, window_seconds=3600)  # per user
