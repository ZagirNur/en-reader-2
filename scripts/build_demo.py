"""Seed demo pipeline: read .txt → analyze + chunk → write `demo.json`.

Temporary glue for M3-M4 so the frontend has a single static asset to load
without a DB. Will be replaced by a real books API in M8.

Usage::

    python scripts/build_demo.py tests/fixtures/golden/01-simple.txt
    python scripts/build_demo.py tests/fixtures/golden/01-simple.txt \\
        --images-dir tests/fixtures/demo-images

M7.1 extends the script with optional inline-image ingestion: every image
file in ``--images-dir`` gets a fresh id, is stored in ``book_images``, and
its ``IMG<id>`` marker is spliced into the raw text at a paragraph boundary
before analysis. After chunking, per-page ``PageImage`` records are computed
by scanning each page's ``text`` for marker matches.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from en_reader import storage
from en_reader.chunker import chunk
from en_reader.images import (
    DEMO_BOOK_ID,
    IMAGE_MARKER_RE,
    marker_for,
    new_image_id,
)
from en_reader.models import PageImage
from en_reader.nlp import analyze

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_PATH = _REPO_ROOT / "src" / "en_reader" / "static" / "demo.json"
_DEFAULT_IMAGES_DIR = _REPO_ROOT / "tests" / "fixtures" / "demo-images"

_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}


def _resolve_input(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def _collect_images(images_dir: Path) -> list[tuple[str, str, bytes]]:
    """Return ``[(image_id, mime_type, data), ...]`` for every file with a
    recognised image extension inside ``images_dir``.

    The list is sorted by filename so the marker-injection order is stable
    across runs — important for predictable tests and diff-friendly output.
    """
    entries: list[tuple[str, str, bytes]] = []
    if not images_dir.is_dir():
        return entries
    for path in sorted(images_dir.iterdir()):
        if not path.is_file():
            continue
        mime = _MIME_BY_EXT.get(path.suffix.lower())
        if mime is None:
            continue
        entries.append((new_image_id(), mime, path.read_bytes()))
    return entries


def _inject_markers(raw_text: str, image_ids: list[str]) -> str:
    """Splice ``IMG<id>`` markers into ``raw_text`` between paragraphs.

    We split on ``\\n\\n`` runs and interleave each image between adjacent
    non-empty segments. If the text has fewer paragraph boundaries than
    images, the surplus markers are appended at the end (still separated by
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
    # Any leftovers trail the text as their own paragraphs so they do not
    # split a sentence.
    while queue:
        out_parts.append(marker_for(queue.pop(0)))
    return "\n\n".join(out_parts)


def _mask_marker_tokens(tokens: list) -> None:
    """Clear ``translatable`` for any token that is part of an image marker.

    spaCy tokenizes ``IMGabcdef012345`` as a single alphanumeric token on
    its own line, so a pattern match on the token text is enough. We still
    keep the tokens in the stream so ``chunk()`` can see sentence
    boundaries; the frontend just skips rendering them as ``.word`` spans.
    """
    for tok in tokens:
        if IMAGE_MARKER_RE.fullmatch(tok.text):
            tok.translatable = False


def _compute_page_images(page_text: str, id_to_mime: dict[str, str]) -> list[PageImage]:
    """Scan ``page_text`` for marker occurrences and build ``PageImage``s.

    Returned list is sorted by ``position``. Any marker whose id isn't in
    ``id_to_mime`` is skipped — this would only happen if text somehow
    contained a marker-shaped string unrelated to a stored image.
    """
    out: list[PageImage] = []
    for match in IMAGE_MARKER_RE.finditer(page_text):
        image_id = match.group(0)[3:]  # strip "IMG" prefix
        mime = id_to_mime.get(image_id)
        if mime is None:
            continue
        out.append(PageImage(image_id=image_id, mime_type=mime, position=match.start()))
    return out


def main(path: str, images_dir: str | Path | None = None) -> Path:
    """Build `demo.json` from the given text file and return the output path.

    When ``images_dir`` is provided (or an empty string / the default CLI
    value resolves to it), any supported images inside are stored in the DB
    under ``DEMO_BOOK_ID`` and injected as markers. Passing ``None``
    (programmatic default) skips image handling entirely — this preserves
    the pre-M7 output shape for tests that don't exercise images and keeps
    the seed callable without a migrated DB.
    """
    input_path = _resolve_input(path)
    raw_text = input_path.read_text(encoding="utf-8")

    images: list[tuple[str, str, bytes]] = []
    if images_dir is not None:
        images_root = Path(images_dir)
        if not images_root.is_absolute():
            images_root = _REPO_ROOT / images_root
        images = _collect_images(images_root)
    id_to_mime: dict[str, str] = {img_id: mime for img_id, mime, _ in images}
    if images:
        # Fresh DB state for the demo book: drop any stale image rows before
        # writing the freshly-generated ids. This keeps the seed script
        # idempotent across reruns.
        storage.image_clear_book(DEMO_BOOK_ID)
        for image_id, mime, data in images:
            storage.image_save(DEMO_BOOK_ID, image_id, mime, data)

    text = _inject_markers(raw_text, list(id_to_mime.keys()))

    tokens, units = analyze(text)
    _mask_marker_tokens(tokens)
    pages = chunk(tokens, units, text)

    # Rebuild each Page with its per-page images list — `chunk` is
    # image-agnostic (M7.1 constraint), so we patch the field post-hoc.
    for page in pages:
        page.images = _compute_page_images(page.text, id_to_mime)

    payload = {
        "total_pages": len(pages),
        "pages": [asdict(page) for page in pages],
    }

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return _OUTPUT_PATH


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build demo.json for the reader.")
    parser.add_argument("path", help="Path to the source .txt file.")
    parser.add_argument(
        "--images-dir",
        default=str(_DEFAULT_IMAGES_DIR),
        help="Directory containing demo images (default: tests/fixtures/demo-images/).",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip image ingestion even if --images-dir exists.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/build_demo.py <path-to-txt> [--images-dir DIR]",
            file=sys.stderr,
        )
        sys.exit(2)
    # CLI invocations run against the real DB; apply migrations before we
    # attempt to write image rows. Unit tests call `main()` directly and own
    # their DB lifecycle via the `tmp_db` autouse fixture.
    storage.migrate()
    args = _parse_args(sys.argv[1:])
    out = main(args.path, images_dir=None if args.no_images else args.images_dir)
    print(f"wrote {out}")
