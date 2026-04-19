"""FastAPI skeleton for the en-reader dev server.

Serves the most-recently-seeded book via ``/api/demo`` (read directly from
SQLite — the static ``demo.json`` handoff was retired in M8.1) plus the
static ``index.html`` stub. ``POST /api/translate`` (M4.1) wraps the
Gemini-backed :func:`en_reader.translate.translate_one`. M5.1 added an
in-memory user dictionary exposed at ``/api/dictionary`` and enriched the
``/api/demo`` payload with ``user_dict`` plus per-page ``auto_unit_ids``.
M6.1 moved dictionary storage to SQLite (see :mod:`en_reader.storage`) so it
survives restarts; M8.1 extended the schema with ``books`` and ``pages`` and
pointed ``/api/demo`` at the newest book.
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


@app.get("/")
def root() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/demo")
def api_demo() -> dict:
    """Return the newest seeded book, enriched with ``user_dict``/``auto_unit_ids``.

    Thin shim over the books/pages tables until M8.2 introduces a real
    library-scoped content API. 404s with a helpful message when the DB has
    no books (fresh checkout, tests that forgot to seed, etc.).
    """
    books = storage.book_list()
    if not books:
        raise HTTPException(
            status_code=404,
            detail="no books seeded; run `python scripts/seed.py <path-to-txt>` first",
        )
    # book_list() orders newest first; take the head.
    newest = books[0]
    pages = storage.pages_load_slice(newest.id, 0, newest.total_pages)

    user_dict = storage.dict_all()
    user_dict_keys = set(user_dict.keys())

    page_payloads: list[dict] = []
    for page in pages:
        page_dict = asdict(page)
        auto_ids: list[int] = []
        for unit in page_dict.get("units", []):
            lemma = (unit.get("lemma") or "").lower()
            if lemma and lemma in user_dict_keys:
                auto_ids.append(unit["id"])
        page_dict["auto_unit_ids"] = auto_ids
        page_payloads.append(page_dict)

    return {
        "total_pages": newest.total_pages,
        "book_id": newest.id,
        "pages": page_payloads,
        "user_dict": user_dict,
    }


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


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for SPA deep links; let /api/* and /static/* 404 normally."""
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    return FileResponse(_STATIC_DIR / "index.html")
