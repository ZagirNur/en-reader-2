"""Seed ``catalog_books`` with the bundled public-domain source texts (M16.5).

The real deployment ships ~20 Gutenberg titles; this MVP script seeds
whatever ``.txt`` files are present under ``data/catalog/sources/``.
Idempotent — re-runs are a no-op thanks to the ``UNIQUE(title, author)``
constraint in the v7 schema.

For each source file we:

1. Parse it with :func:`parse_txt` (any extension/format quirks handled).
2. Run :mod:`en_reader.nlp` + :mod:`en_reader.chunker` over the text
   to get the real page count — the catalog UI shows ``N стр.`` and
   we want it to match what the user will actually see after import.
3. Upsert a row via :func:`storage.catalog_upsert`.

Run from the repo root::

    .venv/bin/python scripts/seed_catalog.py

No output on success except a final ``seeded: <count>`` line.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from en_reader import storage  # noqa: E402
from en_reader.parsers.txt import parse_txt  # noqa: E402


@dataclass(frozen=True)
class CatalogSource:
    """Curated metadata for a source file on disk.

    The title/author pair doubles as the idempotency key in
    ``catalog_books``, so these must exactly match what the operator
    wants the user to see in the UI — ``parse_txt`` also sniffs a title
    from the first line, but the catalog row takes precedence.
    """

    filename: str
    title: str
    author: str
    level: str  # one of storage.CATALOG_LEVELS
    tags: tuple[str, ...]
    cover_preset: str  # 'c-olive' / 'c-rose' / …
    source_url: str | None = None


# Minimal MVP catalog. Add more entries as additional source files land in
# ``data/catalog/sources/``. The production seed list (~20 titles) is maintained
# out-of-band; deploy-time a richer ``sources/`` directory is rsynced in and
# this script gets re-run.
CATALOG: tuple[CatalogSource, ...] = (
    CatalogSource(
        filename="peter-rabbit.txt",
        title="The Tale of Peter Rabbit",
        author="Beatrix Potter",
        level="A1",
        tags=("short", "classic", "beginner"),
        cover_preset="c-sage",
        source_url="https://www.gutenberg.org/ebooks/14838",
    ),
    CatalogSource(
        filename="happy-prince.txt",
        title="The Happy Prince",
        author="Oscar Wilde",
        level="A2",
        tags=("short", "classic"),
        cover_preset="c-mauve",
        source_url="https://www.gutenberg.org/ebooks/30120",
    ),
    CatalogSource(
        filename="selfish-giant.txt",
        title="The Selfish Giant",
        author="Oscar Wilde",
        level="A2",
        tags=("short", "classic"),
        cover_preset="c-olive",
        source_url="https://www.gutenberg.org/ebooks/30120",
    ),
    CatalogSource(
        filename="yellow-wallpaper.txt",
        title="The Yellow Wallpaper",
        author="Charlotte Perkins Gilman",
        level="B2",
        tags=("short", "classic"),
        cover_preset="c-rose",
        source_url="https://www.gutenberg.org/ebooks/1952",
    ),
)


def _count_pages(text: str) -> int:
    """Return the chunker's page count for ``text``.

    Uses the full NLP pipeline so the catalog's ``pages`` number matches
    what the user sees after import. Imports are lazy because loading
    spaCy for an unrelated DB op would make the ``/api/catalog`` handler
    slow on cold start.
    """
    from en_reader.chunker import chunk
    from en_reader.nlp import analyze

    tokens, units = analyze(text)
    pages = chunk(tokens, units, text)
    return max(1, len(pages))


def seed(sources_dir: Path | None = None) -> int:
    """Upsert every ``CATALOG`` entry whose source file exists.

    Returns the number of rows touched (either inserted or already there
    — the DAO is idempotent so we don't try to distinguish). Silently
    skips entries whose source file is missing so the script can be run
    on partial checkouts.
    """
    root = sources_dir or (_REPO_ROOT / "data" / "catalog" / "sources")
    touched = 0
    for entry in CATALOG:
        path = root / entry.filename
        if not path.exists():
            continue
        data = path.read_bytes()
        parsed = parse_txt(data, entry.filename)
        pages = _count_pages(parsed.text)
        storage.catalog_upsert(
            title=entry.title,
            author=entry.author,
            level=entry.level,
            pages=pages,
            tags=list(entry.tags),
            cover_preset=entry.cover_preset,
            source_url=entry.source_url,
            source_path=str(path),
        )
        touched += 1
    return touched


def main() -> None:
    storage.migrate()
    n = seed()
    print(f"seeded: {n}")


if __name__ == "__main__":
    main()
