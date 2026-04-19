"""Marker-based inline image utilities (M7.1).

The seed pipeline and (later) fb2/epub parsers embed image markers of the
form ``IMG<12-hex>`` directly into ``Page.text``. Each marker is paired with
a ``PageImage`` record on the same page that carries the character offset,
the generated id, and the MIME type. The frontend walks tokens and, for
every marker position it crosses, emits an ``<img>`` sourced from
``/api/books/{book_id}/images/{image_id}``.

``DEMO_BOOK_ID`` is a placeholder: there is no ``books`` table yet (arrives
in M8.1). Until then every image is stored under book id 1.
"""

from __future__ import annotations

import re
import secrets

# 15 chars total: 3-char "IMG" prefix + 12 lowercase hex digits.
IMAGE_MARKER_RE = re.compile(r"IMG[0-9a-f]{12}")


def new_image_id() -> str:
    """Return a fresh 12-char lowercase hex image id (48 bits of entropy)."""
    return secrets.token_hex(6)


def marker_for(image_id: str) -> str:
    """Build the in-text marker for ``image_id``."""
    return f"IMG{image_id}"


# Placeholder until M8.1 introduces a real `books` table.
DEMO_BOOK_ID = 1
