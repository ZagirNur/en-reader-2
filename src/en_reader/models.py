"""Core dataclasses for the NLP pipeline.

These types are intentionally minimal at this stage: task M1.1 only populates
`Token`, while `Unit` is declared here so that follow-up tasks (1.3 MWE and
1.4 phrasal verbs) can start building and referencing it without a schema
change.
"""

from dataclasses import dataclass


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
