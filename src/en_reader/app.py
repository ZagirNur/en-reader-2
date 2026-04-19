"""FastAPI skeleton for the en-reader dev server.

Serves the SPA shell plus a paginated book content API. ``POST /api/translate``
(M4.1) wraps the Gemini-backed :func:`en_reader.translate.translate_one`. M5.1
added an in-memory user dictionary exposed at ``/api/dictionary`` and enriched
the reader payload with ``user_dict`` plus per-page ``auto_unit_ids``. M6.1
moved dictionary storage to SQLite (see :mod:`en_reader.storage`) so it
survives restarts; M8.1 extended the schema with ``books`` and ``pages``; M8.2
replaced the legacy ``/api/demo`` shim with ``GET /api/books/{id}/content``
(paginated via ``offset`` / ``limit``) plus a ``/cover`` stub.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from en_reader import storage
from en_reader.metrics import counters
from en_reader.translate import TranslateError, translate_one

load_dotenv()

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Run DB migrations on startup. No teardown work needed."""
    storage.migrate()
    yield


app = FastAPI(title="en-reader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class TranslateRequest(BaseModel):
    unit_text: str = Field(min_length=1, max_length=100)
    sentence: str = Field(min_length=1, max_length=2000)
    lemma: str = Field(min_length=1, max_length=100)


class TranslateResponse(BaseModel):
    ru: str


class BookListItem(BaseModel):
    id: int
    title: str
    author: str | None
    total_pages: int
    has_cover: bool


class ProgressIn(BaseModel):
    last_page_index: int = Field(ge=0)
    last_page_offset: float = Field(ge=0.0, le=1.0)


class CurrentBookIn(BaseModel):
    # Default to None so clients can POST an empty body to clear the pointer
    # — POSTing {"book_id": null} and {} behave identically. The handler
    # validates the book id against storage before persisting.
    book_id: int | None = None


@app.get("/")
def root() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


_CONTENT_MAX_LIMIT = 20


@app.get("/api/books", response_model=list[BookListItem])
def api_books_list() -> list[BookListItem]:
    """Return every book in the library, newest first.

    Ordering comes straight from :func:`storage.book_list` (``created_at
    DESC``). ``has_cover`` is a convenience flag for the library UI so it
    can decide between the real cover route and a generated placeholder
    tile without a separate HEAD request. Pre-M12 no parser sets
    ``cover_path``, so the flag is ``False`` in practice — we still
    compute it defensively so M12 doesn't have to touch this handler.
    """
    metas = storage.book_list()
    return [
        BookListItem(
            id=m.id,
            title=m.title,
            author=m.author,
            total_pages=m.total_pages,
            has_cover=bool(m.cover_path),
        )
        for m in metas
    ]


@app.delete("/api/books/{book_id}")
def api_book_delete(book_id: int) -> Response:
    """Delete a book plus its pages / images. 404 if the book is unknown.

    The row-level cascade (pages + book_images) lives in
    :func:`storage.book_delete`. If a cover file exists on disk (it
    won't pre-M12 since parsers don't populate ``cover_path`` yet) we
    remove it here and swallow ``FileNotFoundError`` / ``OSError`` so a
    missing or already-gone file doesn't surface as a 500.
    """
    meta = storage.book_meta(book_id)
    if meta is None:
        raise HTTPException(status_code=404)
    if meta.cover_path:
        try:
            Path(meta.cover_path).unlink()
        except (FileNotFoundError, OSError):
            pass
    storage.book_delete(book_id)
    return Response(status_code=204)


@app.get("/api/books/{book_id}/content")
def api_book_content(book_id: int, offset: int = 0, limit: int = 1) -> dict:
    """Return a slice of a book's pages plus the server-side dictionary.

    ``offset`` / ``limit`` are zero-based; ``limit`` is hard-capped at
    :data:`_CONTENT_MAX_LIMIT` (20) to keep Safari happy on big books. The
    response shape is future-compatible with M10.1 reading-progress save:
    ``last_page_index`` / ``last_page_offset`` ship as zeros today and will
    carry real values once that task lands.

    ``auto_unit_ids`` on each page lists the ids of units whose lemma is
    present in the user dictionary — the frontend uses this to auto-highlight
    already-translated words on first render.
    """
    meta = storage.book_meta(book_id)
    if meta is None:
        raise HTTPException(status_code=404)

    if limit > _CONTENT_MAX_LIMIT:
        limit = _CONTENT_MAX_LIMIT

    pages = storage.pages_load_slice(book_id, offset, limit)
    user_dict = storage.dict_all()
    user_dict_keys = set(user_dict.keys())

    page_payloads: list[dict] = []
    for page in pages:
        page_dict = asdict(page)
        auto_ids: list[int] = []
        for unit in page.units:
            lemma = (unit.lemma or "").lower()
            if lemma and lemma in user_dict_keys:
                auto_ids.append(unit.id)
        page_dict["auto_unit_ids"] = auto_ids
        page_payloads.append(page_dict)

    last_page_index, last_page_offset = storage.progress_get(book_id)
    return {
        "book_id": book_id,
        "total_pages": meta.total_pages,
        "last_page_index": last_page_index,
        "last_page_offset": last_page_offset,
        "pages": page_payloads,
        "user_dict": user_dict,
    }


@app.post("/api/books/{book_id}/progress", status_code=204)
def api_book_progress_save(book_id: int, p: ProgressIn) -> Response:
    """Persist the reader's position for ``book_id``.

    Validation order is intentional: 404 for unknown book first (so we
    don't accept progress for phantom ids), then 400 if the page index
    is past the book's ``total_pages``. Pydantic already rejects
    out-of-range offsets (422) before this handler runs, so we don't
    re-check ``last_page_offset`` ourselves.
    """
    meta = storage.book_meta(book_id)
    if meta is None:
        raise HTTPException(status_code=404)
    if p.last_page_index >= meta.total_pages:
        raise HTTPException(status_code=400, detail="page_index out of range")
    storage.progress_set(book_id, p.last_page_index, p.last_page_offset)
    return Response(status_code=204)


@app.get("/api/books/{book_id}/cover")
def api_book_cover(book_id: int) -> FileResponse:
    """Serve a book's cover image, if one was captured by the parser.

    Until M12 adds real parsers, ``cover_path`` is always ``NULL`` and this
    endpoint 404s — that's fine; the frontend falls back to a generated
    placeholder tile.
    """
    meta = storage.book_meta(book_id)
    if meta is None or not meta.cover_path:
        raise HTTPException(status_code=404)
    return FileResponse(
        meta.cover_path,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    cached = storage.dict_get(req.lemma)
    if cached:
        counters.translate_hit += 1
        logger.info("translate HIT: lemma=%r", req.lemma)
        return TranslateResponse(ru=cached)
    counters.translate_miss += 1
    logger.info("translate MISS: lemma=%r", req.lemma)
    try:
        ru = translate_one(req.unit_text, req.sentence)
    except TranslateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    storage.dict_add(req.lemma, ru)
    return TranslateResponse(ru=ru)


@app.get("/api/dictionary")
def api_dictionary_list() -> dict[str, str]:
    return storage.dict_all()


@app.delete("/api/dictionary/{lemma}")
def api_dictionary_delete(lemma: str) -> Response:
    # Idempotent: 204 whether or not the key existed.
    storage.dict_remove(lemma)
    return Response(status_code=204)


@app.get("/api/books/{book_id}/images/{image_id}")
def api_get_image(book_id: int, image_id: str) -> Response:
    """Serve an inline illustration blob (M7.1).

    Images are immutable once written (the id is random); cache
    aggressively so browsers hit the network at most once per image.
    """
    result = storage.image_get(book_id, image_id)
    if result is None:
        raise HTTPException(status_code=404)
    mime, data = result
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/api/me/current-book")
def api_get_current_book() -> dict:
    """Return the user's current-book pointer (M10.5).

    ``{"book_id": null}`` means "no current book — land on the library".
    Storage lives in the ``meta`` table keyed by ``current_book_id``;
    M11.1 will migrate this to ``users.current_book_id``.
    """
    return {"book_id": storage.current_book_get()}


@app.post("/api/me/current-book", status_code=204)
def api_set_current_book(p: CurrentBookIn) -> Response:
    """Set or clear the current-book pointer (M10.5).

    ``{"book_id": <id>}`` sets it (404 if the book is unknown), and
    ``{"book_id": null}`` or an empty body clears it. We validate the
    book id with ``storage.book_meta`` before writing so a stale client
    can't park a pointer at a phantom row.
    """
    if p.book_id is not None:
        if not storage.book_meta(p.book_id):
            raise HTTPException(status_code=404)
    storage.current_book_set(p.book_id)
    return Response(status_code=204)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for SPA deep links; let /api/* and /static/* 404 normally."""
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    return FileResponse(_STATIC_DIR / "index.html")
