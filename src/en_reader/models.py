"""Core dataclasses for the NLP pipeline.

These types are intentionally minimal at this stage: task M1.1 only populates
`Token`, while `Unit` is declared here so that follow-up tasks (1.3 MWE and
1.4 phrasal verbs) can start building and referencing it without a schema
change.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Token:
    """A single surface token produced by the spaCy pipeline.

    Fields after `idx_in_text` are placeholders for follow-up tasks and stay at
    their defaults in M1.1 (see the task spec's "что НЕ нужно делать").
    """

    text: str
    lemma: str
    pos: str
    is_sent_start: bool
    idx_in_text: int
    translatable: bool = False
    unit_id: int | None = None
    pair_id: int | None = None


@dataclass
class Unit:
    """A lexical unit spanning one or more tokens.

    Created by later tasks (1.3 MWE, 1.4 phrasal verbs). M1.1 only declares the
    type so downstream code can import it.
    """

    id: int
    token_ids: list[int]
    lemma: str
    kind: str
    is_split_pv: bool = False
    pair_id: int | None = None


@dataclass
class PageImage:
    """An inline image placed at a character offset inside ``Page.text``.

    ``position`` is the char index at which the ``IMG<12-hex>`` marker starts
    inside ``Page.text``. The frontend uses this to splice an ``<img>`` into
    the rendered DOM between tokens; the marker itself is not rendered as
    text.
    """

    image_id: str
    mime_type: str
    position: int


@dataclass
class Page:
    """A sentence-bounded slice of the book, sized for the reader frontend.

    Produced by `en_reader.chunker.chunk`. `tokens` and `units` are
    self-contained: `idx_in_text` is relative to `text`, and `Unit.token_ids`
    index into this page's `tokens` list, not the global token stream.
    `images` is populated by the seed pipeline (M7.1) after chunking; the
    chunker itself is image-agnostic.
    """

    page_index: int
    text: str
    tokens: list[Token] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    images: list[PageImage] = field(default_factory=list)


@dataclass
class User:
    """A row from the ``users`` table (M11.1 / M11.2 / M18.1).

    ``email`` is always set (synthetic ``tg-<id>@telegram.local`` for
    Telegram-only accounts so we can keep the NOT NULL UNIQUE constraint).
    ``password_hash`` is bcrypt for password users and the
    ``__tg_no_password__`` sentinel for Telegram-only accounts — the login
    handler rejects that sentinel so a Telegram-only user can never be
    logged in via /auth/login. ``telegram_id`` (M18.1) holds the Telegram
    user id for accounts created or linked through the Mini App.
    """

    id: int
    email: str
    password_hash: str
    created_at: str
    current_book_id: int | None
    telegram_id: int | None = None


@dataclass
class BookMeta:
    """Library-level book metadata, mirroring the ``books`` table row (M8.1).

    Returned by :func:`en_reader.storage.book_meta` /
    :func:`en_reader.storage.book_list` without any page payload — the
    per-page tokens/units/images are fetched separately via
    :func:`en_reader.storage.pages_load_slice`.
    """

    id: int
    title: str
    author: Optional[str]
    language: str
    source_format: str
    source_bytes_size: int
    total_pages: int
    cover_path: Optional[str]
    created_at: str
