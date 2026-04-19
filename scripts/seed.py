"""Seed a .txt (+ optional image directory) into the books/pages DB.

Replaces the older ``scripts/build_demo.py`` — instead of emitting a static
``demo.json`` the seed now writes a real ``books`` row plus a gzip-compressed
``pages`` row per page. The ``/api/demo`` shim serves the most-recently-seeded
book until M8.2 ships a proper library API.

Usage::

    python scripts/seed.py tests/fixtures/golden/05-complex.txt
    python scripts/seed.py tests/fixtures/golden/05-complex.txt \\
        --images-dir tests/fixtures/demo-images
    python scripts/seed.py tests/fixtures/golden/05-complex.txt \\
        --title "Complex Demo"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from en_reader import storage
from en_reader.images import marker_for, new_image_id
from en_reader.parsers import ParsedBook, ParsedImage

_REPO_ROOT = Path(__file__).resolve().parent.parent

_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}


def _resolve_input(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def _collect_images(images_dir: Path) -> list[ParsedImage]:
    """Return a stable-ordered list of :class:`ParsedImage` for ``images_dir``.

    Sorted by filename so marker injection order is deterministic across
    runs — predictable tests, diff-friendly seeds.
    """
    out: list[ParsedImage] = []
    if not images_dir.is_dir():
        return out
    for path in sorted(images_dir.iterdir()):
        if not path.is_file():
            continue
        mime = _MIME_BY_EXT.get(path.suffix.lower())
        if mime is None:
            continue
        out.append(
            ParsedImage(
                image_id=new_image_id(),
                mime_type=mime,
                data=path.read_bytes(),
            )
        )
    return out


def _inject_markers(raw_text: str, image_ids: list[str]) -> str:
    """Splice ``IMG<id>`` markers into ``raw_text`` between paragraphs.

    Splits on runs of ``\\n\\n`` and interleaves each image between adjacent
    non-empty segments. If there are fewer paragraph boundaries than images,
    the surplus markers are appended at the end (still separated by
    ``\\n\\n`` so spaCy treats them as their own paragraph and the chunker
    sees a clean sentence boundary). Empty inputs and empty image lists
    short-circuit.
    """
    if not image_ids:
        return raw_text
    segments = [s for s in raw_text.split("\n\n") if s != ""]
    if not segments:
        return "\n\n".join(marker_for(i) for i in image_ids)

    out_parts: list[str] = []
    queue = list(image_ids)
    for i, seg in enumerate(segments):
        out_parts.append(seg)
        if i < len(segments) - 1 and queue:
            out_parts.append(marker_for(queue.pop(0)))
    while queue:
        out_parts.append(marker_for(queue.pop(0)))
    return "\n\n".join(out_parts)


def main(
    txt_path: str | Path,
    images_dir: Optional[str | Path] = None,
    title: Optional[str] = None,
) -> int:
    """Seed one book from a .txt fixture and return its ``book_id``.

    Programmatic entrypoint for tests. Ensures migrations are applied before
    the insert, so callers don't need to remember to call ``storage.migrate``
    first.
    """
    storage.migrate()

    input_path = _resolve_input(txt_path)
    raw_bytes = input_path.read_bytes()
    raw_text = raw_bytes.decode("utf-8")

    images: list[ParsedImage] = []
    if images_dir is not None:
        images_root = Path(images_dir)
        if not images_root.is_absolute():
            images_root = _REPO_ROOT / images_root
        images = _collect_images(images_root)

    text_with_markers = _inject_markers(raw_text, [img.image_id for img in images])

    parsed = ParsedBook(
        title=title if title is not None else input_path.stem.title(),
        author=None,
        language="en",
        source_format="txt",
        source_bytes_size=len(raw_bytes),
        text=text_with_markers,
        images=images,
        cover=None,
    )

    return storage.book_save(parsed)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a .txt into the books/pages DB.")
    parser.add_argument("path", help="Path to the source .txt file.")
    parser.add_argument(
        "--images-dir",
        default=None,
        help="Directory containing inline images (optional).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Override the book title (defaults to the filename stem, title-cased).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/seed.py <path-to-txt> [--images-dir DIR] [--title T]",
            file=sys.stderr,
        )
        sys.exit(2)
    args = _parse_args(sys.argv[1:])
    book_id = main(args.path, images_dir=args.images_dir, title=args.title)
    meta = storage.book_meta(book_id)
    total_pages = meta.total_pages if meta else 0
    print(f"book_id={book_id} total_pages={total_pages}")
