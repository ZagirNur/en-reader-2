"""Structured logging + in-memory ring buffer (M14.1).

Goals:

* **JSON logs in prod**, pretty text in dev — so systemd-journald captures
  one-line structured records while local development stays readable.
* **RingBufferHandler** keeps the last 1000 formatted lines in memory so
  ``GET /debug/logs`` can return a tail without touching disk.
* **stdout only** — journald collects stdout on the server; writing to a
  file would create a second source of truth and needs rotation.

The module exposes a module-level singleton handler (``_ring``) so the
debug endpoint can look up the same buffer instance that :func:`install`
attached to the root logger, without threading it through FastAPI.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import deque
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Format a :class:`logging.LogRecord` as a single JSON line.

    Fields: ``ts`` (ISO-8601 UTC), ``level``, ``logger``, ``msg`` (already
    expanded via ``record.getMessage()``), and ``exc`` for the traceback
    when ``record.exc_info`` is set. ``ensure_ascii=False`` keeps
    non-ASCII messages human-readable in journalctl.
    """

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, str] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class RingBufferHandler(logging.Handler):
    """Bounded in-memory log sink, last ``maxlen`` formatted records.

    ``deque`` with ``maxlen`` gives us O(1) append and automatic eviction
    of the oldest line — perfect for a "show me the tail" debug endpoint
    without any manual size management.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:  # pragma: no cover - defensive
            self.handleError(record)

    def tail(self, n: int = 200) -> list[str]:
        """Return up to the last ``n`` formatted log lines."""
        if n <= 0:
            return []
        return list(self.buffer)[-n:]


# Module-level singleton so :func:`get_ring` can hand out the same
# instance the debug endpoint inspects — the logger stack only sees one
# handler, and we never re-instantiate it on repeat ``install()`` calls.
_ring = RingBufferHandler()


def install() -> None:
    """Wire stdout + ring-buffer handlers onto the root logger.

    Idempotent: clears any handlers previously attached by this function
    so repeated calls (test suites re-importing ``app``) don't stack
    duplicates. Picks JSON formatting when ``ENV=prod``, pretty text
    otherwise. Also disowns the uvicorn/fastapi loggers' own handlers so
    their records propagate to root and pick up our formatting.
    """
    is_prod = os.getenv("ENV") == "prod"
    fmt: logging.Formatter = (
        JsonFormatter()
        if is_prod
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Drop any previous install() handlers so a re-import in tests (or a
    # second call in the same process) doesn't double-emit every record.
    for h in list(root.handlers):
        if getattr(h, "_en_reader_installed", False):
            root.removeHandler(h)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    stream._en_reader_installed = True  # type: ignore[attr-defined]
    root.addHandler(stream)

    _ring.setFormatter(fmt)
    _ring._en_reader_installed = True  # type: ignore[attr-defined]
    # Guard against double-adding _ring on repeated install() — the
    # buffer itself survives across calls by design.
    if _ring not in root.handlers:
        root.addHandler(_ring)

    # uvicorn/fastapi ship their own handlers by default; clear them so
    # their records flow up to root and get our formatting (and land in
    # the ring buffer). ``propagate = True`` is the Python default, but
    # set explicitly in case a prior config flipped it off.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True


def get_ring() -> RingBufferHandler:
    """Return the process-wide :class:`RingBufferHandler` singleton."""
    return _ring
