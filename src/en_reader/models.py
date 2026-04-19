"""Core dataclasses for the NLP pipeline.

These types are intentionally minimal at this stage: task M1.1 only populates
`Token`, while `Unit` is declared here so that follow-up tasks (1.3 MWE and
1.4 phrasal verbs) can start building and referencing it without a schema
change.
"""

from dataclasses import dataclass, field


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
