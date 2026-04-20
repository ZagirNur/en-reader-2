"""FastAPI skeleton for the en-reader dev server.

Serves the SPA shell plus a paginated book content API. ``POST /api/translate``
(M4.1) wraps the Gemini-backed :func:`en_reader.translate.translate_one`. M5.1
added an in-memory user dictionary exposed at ``/api/dictionary`` and enriched
the reader payload with ``user_dict`` plus per-page ``auto_unit_ids``. M6.1
moved dictionary storage to SQLite (see :mod:`en_reader.storage`) so it
survives restarts; M8.1 extended the schema with ``books`` and ``pages``; M8.2
replaced the legacy ``/api/demo`` shim with ``GET /api/books/{id}/content``
(paginated via ``offset`` / ``limit``) plus a ``/cover`` stub. M11.3 attached
``get_current_user`` to every ``/api/*`` route so every DAO call runs under
the signed-in user's id, eliminating cross-account data bleed.
"""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from en_reader import storage
from en_reader.auth import (
    auth_ratelimit,
    check_password,
    hash_password,
    normalize_email,
)
from en_reader.logs import get_ring, install as install_logging
from en_reader.metrics import counters
from en_reader.models import BookMeta, User
from en_reader.parsers import UnsupportedFormatError, parse_book
from en_reader.ratelimit import rl_translate, rl_upload
from en_reader.translate import TranslateError, translate_one

# Uvicorn ships a ``ProxyHeadersMiddleware`` that rewrites ``request.client``
# from ``X-Forwarded-For`` / ``X-Real-IP`` when the request comes from a
# trusted upstream. Behind Caddy (M13.4) the raw TCP peer is 127.0.0.1,
# so without this middleware every auth rate-limit bucket would collapse
# onto a single IP. Starlette has no equivalent module — if the import
# ever fails (wheel slimmed, upstream rename) we fall back to not adding
# it rather than crashing the whole app.
try:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    _HAS_PROXY_HEADERS = True
except Exception:  # pragma: no cover - defensive fallback
    _HAS_PROXY_HEADERS = False

load_dotenv()

# Wire structured logging + RingBufferHandler onto the root logger before
# the FastAPI app is built, so even import-time module logs land in the
# ring buffer surfaced by /debug/logs.
install_logging()

logger = logging.getLogger("en_reader")


# ---------- process-wide metadata (M14.1) ----------

_startup_ts = datetime.now(timezone.utc)
_git_sha: str | None = None


def _get_git_sha() -> str:
    """Return the short git SHA of the running checkout, cached after first call.

    Falls back to ``"unknown"`` when ``.git`` is absent (e.g. container or
    source tarball install) or ``git`` itself isn't on PATH. The subprocess
    runs from this file's directory so a caller's cwd doesn't throw the
    lookup off.
    """
    global _git_sha
    if _git_sha is None:
        try:
            out = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(Path(__file__).resolve().parent),
                text=True,
                stderr=subprocess.DEVNULL,
            )
            _git_sha = out.strip() or "unknown"
        except Exception:
            _git_sha = "unknown"
    return _git_sha


# Log startup once at import time — the lifespan hook also runs, but
# logging here means the line shows up even if an import-time config
# error blows up before the server ever accepts a connection.
logger.info("en-reader starting, sha=%s", _get_git_sha())

_STATIC_DIR = Path(__file__).parent / "static"


def _secret_key() -> str:
    """Return a persistent SECRET_KEY, creating it on first call.

    Backed by ``data/.secret_key`` with mode 0o600 — we want the key to
    survive a restart (otherwise every deploy invalidates every live
    session) but never to land in source control or become world-readable.
    If the file exists we trust its contents verbatim; otherwise we mint
    a fresh 32-byte URL-safe token.
    """
    path = Path("data/.secret_key")
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    path.write_text(key)
    os.chmod(path, 0o600)
    return key


SECRET_KEY = _secret_key()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Run DB migrations on startup. No teardown work needed."""
    storage.migrate()
    yield


# ---------- security middlewares (M14.2) ----------

# Content-Security-Policy: lock every subresource to the same origin, with
# two narrow whitelists:
#   * ``img-src data:`` — we serve inline book illustrations as real
#     ``/api/.../images/...`` URLs today, but keep ``data:`` on the
#     allowlist defensively so a future embed (e.g. a 1x1 pixel) doesn't
#     break. No ``unsafe-inline`` anywhere.
#   * Google Fonts — ``index.html`` loads the Geist family from
#     ``fonts.googleapis.com`` (stylesheet) + ``fonts.gstatic.com`` (the
#     actual font files) since M3.3. If that CDN is ever dropped, trim
#     both entries back to ``'self'``.
# ``frame-ancestors 'none'`` is the modern replacement for XFO=DENY —
# we still send both because some corporate proxies strip one or the other.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "script-src 'self'; "
    "font-src 'self' https://fonts.gstatic.com; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers to every outgoing response.

    Set unconditionally — static assets, API JSON, SPA shell, error
    responses, everything. Caddy also emits HSTS in front of us (M13.4),
    which is why we don't set it here.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = _CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Cheap CSRF guard on top of ``SameSite=Lax`` session cookies.

    For any non-safe method (POST/PUT/PATCH/DELETE) we look at
    ``Origin`` first, then ``Referer``. If either is present and does
    **not** start with the request's own ``base_url``, we reject 403 with
    a JSON body. If neither header is present we allow the request
    through — a handful of legitimate clients (``navigator.sendBeacon``
    in some browsers, server-to-server curl) omit both, and blocking
    them would be more user-visible breakage than the attack surface it
    closes. The session cookie's ``SameSite=Lax`` flag still protects
    against the classic cross-site form-post case.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin") or request.headers.get("referer", "")
            if origin:
                expected = str(request.base_url).rstrip("/")
                if not origin.startswith(expected):
                    return JSONResponse(
                        {"detail": "forbidden origin"},
                        status_code=403,
                    )
        return await call_next(request)


app = FastAPI(title="en-reader", lifespan=lifespan)
# Middleware registration in Starlette wraps **around** previously-added
# middleware, so the last ``add_middleware`` call runs first on the way
# in. We want, inbound:
#     OriginCheck  →  SessionMiddleware  →  SecurityHeaders  →  route
# so we register in the reverse order: SecurityHeaders first (innermost,
# runs last inbound / first outbound → always stamps headers), then
# SessionMiddleware (so the Origin check sees session cookies if it ever
# needs them), then OriginCheck outermost (reject CSRF before we touch
# the session or any route handler).
app.add_middleware(SecurityHeadersMiddleware)
# SessionMiddleware goes on before any routes run — Starlette walks the
# middleware stack on every request, so position doesn't affect route
# resolution, only the visible order of request/response callbacks.
# ``https_only`` only flips on in prod because the dev server is plain HTTP.
# Starlette's SessionMiddleware always sets HttpOnly internally (the JS
# side has no business reading this cookie), so no ``http_only`` kwarg
# is needed or accepted on current Starlette versions.
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="sess",
    max_age=60 * 60 * 24 * 30,  # 30 days
    same_site="lax",
    https_only=os.getenv("ENV") == "prod",
)
app.add_middleware(OriginCheckMiddleware)
# ProxyHeadersMiddleware goes on *last* so, in the reverse-order inbound
# dance, it runs **first** and ``request.client.host`` is already the real
# client IP by the time OriginCheck / Session / routes see the request.
# ``trusted_hosts="127.0.0.1"`` matches the Caddy→uvicorn hop from M13.4;
# in test/dev with no upstream, the raw TCP peer is already 127.0.0.1 so
# rewriting is a no-op and nothing breaks.
if _HAS_PROXY_HEADERS:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class TranslateRequest(BaseModel):
    unit_text: str = Field(min_length=1, max_length=100)
    sentence: str = Field(min_length=1, max_length=2000)
    lemma: str = Field(min_length=1, max_length=100)
    # M16.3: frontend may tell the server which book the lemma was clicked
    # in, so the dictionary row can remember its origin (sheet UI shows a
    # "from: The Great Gatsby" chip). Optional — pre-M16.3 clients keep
    # working with no source attribution.
    source_book_id: int | None = None


class TranslateResponse(BaseModel):
    ru: str


class TrainingResultIn(BaseModel):
    lemma: str = Field(min_length=1, max_length=100)
    correct: bool


class BookListItem(BaseModel):
    id: int
    title: str
    author: str | None
    total_pages: int
    has_cover: bool
    # M12.4 (design spec): deterministic gradient-preset class name for
    # books without a real cover. Null when ``has_cover`` is True. The
    # mapping is ``hash(book_id) % 7`` so the same book always renders in
    # the same colour. Actual CSS for these presets lands with M16.5.
    cover_preset: str | None = None


# Seven cover presets from the design spec — keep in sync with the CSS
# tokens documented on the design-spec side.
_COVER_PRESETS = ("olive", "clay", "ink", "mauve", "mustard", "sage", "rose")


def _compute_cover_preset(book_id: int) -> str:
    """Return ``c-<preset>`` for a given book id (deterministic).

    Uses the raw id modulo the preset count so the same book always lands
    on the same colour across server restarts. Python's built-in
    ``hash(str(...))`` would salt per-process and shuffle the palette on
    every redeploy, which breaks the "book recognized by colour" UX.
    """
    return f"c-{_COVER_PRESETS[book_id % len(_COVER_PRESETS)]}"


# M12.4: hard cap on upload size. FastAPI / Starlette don't enforce a
# body-length ceiling on their own — the route reads everything into
# memory before we can inspect it, so the check lives next to the read.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


class ProgressIn(BaseModel):
    last_page_index: int = Field(ge=0)
    last_page_offset: float = Field(ge=0.0, le=1.0)


class Credentials(BaseModel):
    # Pydantic runs field validation before the route body, so ``password``
    # short-circuits to 422 at min_length=8; we keep email as plain ``str``
    # and normalize inside the handler so bad-email errors come out as 400
    # (our domain-level "invalid email" response) rather than 422.
    email: str
    password: str = Field(min_length=8)


class CurrentBookIn(BaseModel):
    # Default to None so clients can POST an empty body to clear the pointer
    # — POSTing {"book_id": null} and {} behave identically. The handler
    # validates the book id against storage before persisting.
    book_id: int | None = None


@app.get("/")
def root() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


_CONTENT_MAX_LIMIT = 20


# ---------- auth helpers (M11.2 / M11.3) ----------


def _client_ip(request: Request) -> str:
    """Return the client IP for rate limiting, falling back to ``"unknown"``.

    Starlette's ``TestClient`` populates ``request.client`` in most cases,
    but a few paths (ASGI lifespan, custom transports) can leave it
    ``None``. We don't want the rate limiter to blow up there, so we
    bucket all such requests under a single ``"unknown"`` key.
    """
    client = request.client
    if client is None or not client.host:
        return "unknown"
    return client.host


def get_current_user(request: Request) -> User:
    """FastAPI dependency: resolve the signed-in user or 401.

    Wired into every ``/api/*`` route in M11.3 so each DAO call runs under
    the owner's id; handlers just declare
    ``user: User = Depends(get_current_user)`` and pass ``user.id`` through.
    """
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = storage.user_by_id(uid)
    if user is None:
        # Session references a deleted user — clear it so the client
        # gets a clean 401 on the next call instead of a stale cookie.
        request.session.clear()
        raise HTTPException(status_code=401)
    return user


def _ensure_book_owner(book_id: int, user_id: int) -> BookMeta:
    """Return the :class:`BookMeta` if ``user_id`` owns ``book_id``, else 404.

    M11.3 spec §3 picks 404 (not 403) for private-ownership violations so
    attackers can't probe book-id existence — a book they don't own is
    indistinguishable from one that doesn't exist at all.
    """
    meta = storage.book_meta(book_id, user_id=user_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="book not found")
    return meta


# ---------- library / reader API (M8.2 → M11.3) ----------


@app.get("/api/books", response_model=list[BookListItem])
def api_books_list(user: User = Depends(get_current_user)) -> list[BookListItem]:
    """Return every book owned by the signed-in user, newest first.

    Ordering comes straight from :func:`storage.book_list` (``created_at
    DESC``). ``has_cover`` is a convenience flag for the library UI so it
    can decide between the real cover route and a generated placeholder
    tile without a separate HEAD request. Pre-M12 no parser sets
    ``cover_path``, so the flag is ``False`` in practice — we still
    compute it defensively so M12 doesn't have to touch this handler.
    """
    metas = storage.book_list(user_id=user.id)
    items: list[BookListItem] = []
    for m in metas:
        has_cover = bool(m.cover_path)
        items.append(
            BookListItem(
                id=m.id,
                title=m.title,
                author=m.author,
                total_pages=m.total_pages,
                has_cover=has_cover,
                # Only emit a preset when there isn't a real cover — the
                # frontend uses the preset as a gradient tile fallback.
                cover_preset=None if has_cover else _compute_cover_preset(m.id),
            )
        )
    return items


@app.delete("/api/books/{book_id}")
def api_book_delete(book_id: int, user: User = Depends(get_current_user)) -> Response:
    """Delete a book plus its pages / images. 404 if not owned by the caller.

    The row-level cascade (pages + book_images) lives in
    :func:`storage.book_delete`. If a cover file exists on disk (it
    won't pre-M12 since parsers don't populate ``cover_path`` yet) we
    remove it here and swallow ``FileNotFoundError`` / ``OSError`` so a
    missing or already-gone file doesn't surface as a 500.
    """
    meta = _ensure_book_owner(book_id, user.id)
    if meta.cover_path:
        try:
            Path(meta.cover_path).unlink()
        except (FileNotFoundError, OSError):
            pass
    storage.book_delete(book_id, user_id=user.id)
    return Response(status_code=204)


@app.get("/api/books/{book_id}/content")
def api_book_content(
    book_id: int,
    offset: int = 0,
    limit: int = 1,
    user: User = Depends(get_current_user),
) -> dict:
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
    meta = _ensure_book_owner(book_id, user.id)

    if limit > _CONTENT_MAX_LIMIT:
        limit = _CONTENT_MAX_LIMIT

    pages = storage.pages_load_slice(book_id, offset, limit)
    user_dict = storage.dict_all(user_id=user.id)
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

    last_page_index, last_page_offset = storage.progress_get(book_id, user_id=user.id)
    return {
        "book_id": book_id,
        "total_pages": meta.total_pages,
        "last_page_index": last_page_index,
        "last_page_offset": last_page_offset,
        "pages": page_payloads,
        "user_dict": user_dict,
    }


@app.post("/api/books/{book_id}/progress", status_code=204)
def api_book_progress_save(
    book_id: int,
    p: ProgressIn,
    user: User = Depends(get_current_user),
) -> Response:
    """Persist the reader's position for ``book_id``.

    Validation order is intentional: 404 for unknown/not-owned book first
    (so we don't accept progress for phantom ids), then 400 if the page
    index is past the book's ``total_pages``. Pydantic already rejects
    out-of-range offsets (422) before this handler runs, so we don't
    re-check ``last_page_offset`` ourselves.
    """
    meta = _ensure_book_owner(book_id, user.id)
    if p.last_page_index >= meta.total_pages:
        raise HTTPException(status_code=400, detail="page_index out of range")
    storage.progress_set(book_id, p.last_page_index, p.last_page_offset, user_id=user.id)
    return Response(status_code=204)


@app.get("/api/books/{book_id}/cover")
def api_book_cover(book_id: int, user: User = Depends(get_current_user)) -> FileResponse:
    """Serve a book's cover image, if one was captured by the parser.

    Until M12 adds real parsers, ``cover_path`` is always ``NULL`` and this
    endpoint 404s — that's fine; the frontend falls back to a generated
    placeholder tile.
    """
    meta = _ensure_book_owner(book_id, user.id)
    if not meta.cover_path:
        raise HTTPException(status_code=404)
    return FileResponse(
        meta.cover_path,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/translate", response_model=TranslateResponse)
def translate(
    req: TranslateRequest,
    user: User = Depends(get_current_user),
) -> TranslateResponse:
    # Rate-limit before any DB / Gemini work so a spamming client can't
    # warm up the cache or burn the translation budget.
    if not rl_translate.check(str(user.id)):
        raise HTTPException(
            status_code=429,
            detail="slow down",
            headers={"Retry-After": str(rl_translate.window)},
        )
    cached = storage.dict_get(req.lemma, user_id=user.id)
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
    # M16.3: persist the originating sentence + (optional) book so the
    # sheet UI can show "from: <book>" chips without a second lookup.
    # ``source_book_id`` is not ownership-checked here: the FK already
    # targets the caller's own books via the ON DELETE SET NULL constraint,
    # and a caller spoofing someone else's id only pollutes their own row.
    storage.dict_add(
        req.lemma,
        ru,
        user_id=user.id,
        example=req.sentence,
        source_book_id=req.source_book_id,
    )
    return TranslateResponse(ru=ru)


@app.get("/api/dictionary")
def api_dictionary_list(user: User = Depends(get_current_user)) -> dict[str, str]:
    """Legacy flat ``{lemma: translation}`` map used by pre-M16.3 clients.

    Kept as-is so the reader's auto-highlight path (which only needs the
    key set) and existing tests keep working. The richer list-of-objects
    shape lives at :func:`api_dictionary_words` below.
    """
    return storage.dict_all(user_id=user.id)


@app.get("/api/dictionary/words")
def api_dictionary_words(
    status: str = "all",
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Return the rich dictionary shape for the M16.4 Words screen.

    ``status`` filters to one of :data:`en_reader.storage.DICT_STATUSES`
    (``new`` / ``learning`` / ``review`` / ``mastered``) or ``all``.
    Unknown values 400 so a typo in the query string fails loudly rather
    than silently returning the full list.
    """
    if status != "all" and status not in storage.DICT_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    filter_status = None if status == "all" else status
    return storage.dict_list(status=filter_status, user_id=user.id)


@app.get("/api/dictionary/stats")
def api_dictionary_stats(user: User = Depends(get_current_user)) -> dict:
    """Return aggregate counts per progression status (spec §5)."""
    return storage.dict_stats(user_id=user.id)


@app.get("/api/dictionary/training")
def api_dictionary_training(
    limit: int = 10,
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Return the next ``limit`` training candidates, prioritised per spec §4."""
    # Clamp so a client can't ask for the whole dictionary in one shot.
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    return storage.pick_training_pool(limit=limit, user_id=user.id)


@app.post("/api/dictionary/training/result", status_code=204)
def api_dictionary_training_result(
    p: TrainingResultIn,
    user: User = Depends(get_current_user),
) -> Response:
    """Record one training answer and advance the word's progression.

    Idempotent on unknown lemma: ``record_training_result`` silently no-ops
    so a stale client replaying an answer after a deletion does not 404.
    """
    storage.record_training_result(p.lemma, p.correct, user_id=user.id)
    return Response(status_code=204)


@app.delete("/api/dictionary/{lemma}")
def api_dictionary_delete(
    lemma: str,
    user: User = Depends(get_current_user),
) -> Response:
    # Idempotent: 204 whether or not the key existed.
    storage.dict_remove(lemma, user_id=user.id)
    return Response(status_code=204)


@app.get("/api/books/{book_id}/images/{image_id}")
def api_get_image(
    book_id: int,
    image_id: str,
    user: User = Depends(get_current_user),
) -> Response:
    """Serve an inline illustration blob (M7.1).

    Images are immutable once written (the id is random); cache
    aggressively so browsers hit the network at most once per image.
    The image-scope is the book, so ownership is enforced by first
    resolving the owning book — a book the caller doesn't own 404s
    exactly like a missing row.
    """
    _ensure_book_owner(book_id, user.id)
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
def api_get_current_book(user: User = Depends(get_current_user)) -> dict:
    """Return the user's current-book pointer (M10.5).

    ``{"book_id": null}`` means "no current book — land on the library".
    Storage lives in ``users.current_book_id`` since M11.1.
    """
    return {"book_id": storage.current_book_get(user_id=user.id)}


@app.post("/api/me/current-book", status_code=204)
def api_set_current_book(
    p: CurrentBookIn,
    user: User = Depends(get_current_user),
) -> Response:
    """Set or clear the current-book pointer (M10.5).

    ``{"book_id": <id>}`` sets it (404 if the book is unknown or owned by
    someone else), and ``{"book_id": null}`` or an empty body clears it.
    We validate the book id with ``_ensure_book_owner`` before writing so
    a stale client can't park a pointer at a phantom or foreign row.
    """
    if p.book_id is not None:
        _ensure_book_owner(p.book_id, user.id)
    storage.current_book_set(p.book_id, user_id=user.id)
    return Response(status_code=204)


# ---------- catalog (M16.5) ----------


@app.get("/api/catalog")
def api_catalog(
    level: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """Return catalog books grouped into UI sections.

    ``level`` tunes the "По твоему уровню" section — no persistence, the
    frontend just sends whatever chip is selected. Defaults to B1 if the
    caller sends nothing or a value we don't recognise.
    """
    sections = storage.catalog_sections(user_level=level or "B1")
    return {"sections": sections}


@app.post("/api/catalog/{catalog_id}/import")
def api_catalog_import(
    catalog_id: int,
    user: User = Depends(get_current_user),
) -> dict:
    """Copy a catalog entry into the caller's personal library.

    Reads the source file referenced by the catalog row, runs it through
    the standard parse → analyze → chunk pipeline via ``storage.book_save``,
    and returns ``{"book_id": N}`` pointing at the freshly-created row in
    the caller's own ``books`` table.

    Dedup is on (title, author): if the user already has a book with the
    same title+author (from a prior import or an unrelated upload), we
    return the existing book_id with 200 rather than 409 so the UX is
    "tap → land on the book" regardless of whether this is the first
    time or not. The response includes ``already_imported=True`` so the
    client can surface a different toast.
    """
    entry = storage.catalog_get(catalog_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="catalog entry not found")

    existing_id = storage.catalog_already_imported(catalog_id, user_id=user.id)
    if existing_id is not None:
        return {"book_id": existing_id, "already_imported": True}

    source_path = Path(entry["source_path"])
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    try:
        data = source_path.read_bytes()
    except (FileNotFoundError, OSError) as e:
        logger.error("catalog source missing id=%d path=%s", catalog_id, source_path)
        raise HTTPException(status_code=500, detail="catalog source unavailable") from e

    try:
        parsed = parse_book(data, source_path.name)
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Prefer the human-curated title/author from the catalog row over whatever
    # the plain-text parser sniffed out of the first line.
    parsed.title = entry["title"]
    parsed.author = entry["author"]

    try:
        book_id = storage.book_save(parsed, user_id=user.id)
    except Exception:
        logger.exception("catalog import failed id=%d", catalog_id)
        raise HTTPException(status_code=500, detail="failed to import")
    return {"book_id": book_id, "already_imported": False}


@app.get("/api/catalog/{catalog_id}/cover")
def api_catalog_cover(
    catalog_id: int,
    user: User = Depends(get_current_user),  # noqa: ARG001
) -> dict:
    """Return the preset gradient class name for a catalog entry.

    No real cover files are stored for catalog books in this milestone —
    the frontend draws a gradient tile using the preset. Returned as JSON
    rather than a file response so the client can reuse the data from
    the list endpoint without a second round-trip.
    """
    entry = storage.catalog_get(catalog_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="catalog entry not found")
    return {"cover_preset": entry["cover_preset"]}


# ---------- auth routes (M11.2) ----------


@app.post("/auth/signup")
def auth_signup(cred: Credentials, request: Request) -> dict:
    """Create an account and log the user in.

    Rate-limit check runs *before* any DB work so a flood can't burn
    cycles on bcrypt. Email validation errors surface as 400 (invalid
    input); duplicate email returns 409 so the frontend can switch to a
    "already registered — sign in?" prompt. On success the session
    cookie is written by SessionMiddleware on response.
    """
    if not auth_ratelimit.check(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts")
    try:
        email = normalize_email(cred.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if storage.user_by_email(email):
        raise HTTPException(status_code=409, detail="email exists")
    user_id = storage.user_create(email, hash_password(cred.password))
    request.session["user_id"] = user_id
    logger.info("user signed up: email=%s", email)
    return {"email": email}


@app.post("/auth/login")
def auth_login(cred: Credentials, request: Request) -> dict:
    """Verify credentials and set the session.

    Rate-limit is the very first check so a brute-force attempt hits the
    429 ceiling before any bcrypt verify. We deliberately return the same
    401 for "user not found" and "wrong password" so attackers can't
    enumerate valid emails. ``check_password`` also rejects the
    ``__migration_placeholder__`` sentinel, which means the seed row can
    never be logged into.
    """
    if not auth_ratelimit.check(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts")
    try:
        email = normalize_email(cred.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    user = storage.user_by_email(email)
    if user is None or not check_password(cred.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    request.session["user_id"] = user.id
    logger.info("user logged in: email=%s", user.email)
    return {"email": user.email}


@app.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    """Clear the session cookie. Idempotent — 200 whether or not we had one."""
    request.session.clear()
    return Response(status_code=200)


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    """Return ``{"email": ...}`` for the signed-in user or 401."""
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = storage.user_by_id(uid)
    if user is None:
        # The DB row backing this session is gone — drop the cookie
        # value so subsequent requests get a clean 401.
        request.session.clear()
        raise HTTPException(status_code=401)
    return {"email": user.email}


# ---------- upload (M12.4) ----------


@app.post("/api/books/upload")
async def api_book_upload(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    """Accept a multipart upload and run it through the parser pipeline.

    Pipeline: ``UploadFile.read()`` → :func:`parse_book` (dispatches by
    filename extension with a magic-byte fallback) → :func:`storage.book_save`
    (NLP + chunker + persist, with cover-to-disk). Size is checked
    immediately after read: over :data:`MAX_UPLOAD_BYTES` → 413, empty
    → 400. ``UnsupportedFormatError`` surfaces as 400 with the parser's
    own message; any other parser exception logs the traceback and
    returns a generic 400. Persistence failures (disk full, DB locked)
    log and return 500. Declared **before** the ``/{full_path:path}``
    catch-all so FastAPI's router matches this route first.
    """
    # Rate-limit *before* the body read so a client hammering uploads
    # can't force us to buffer hundreds of MB into memory just to
    # reject them. 5 uploads / user / hour is generous for legitimate
    # use and tight enough to shut a runaway script down fast.
    if not rl_upload.check(str(user.id)):
        raise HTTPException(
            status_code=429,
            detail="too many uploads today",
            headers={"Retry-After": str(rl_upload.window)},
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 200 MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="empty file")

    try:
        parsed = parse_book(data, file.filename or "book")
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        # We've seen corrupt fb2/epub hit lxml / zipfile with exotic
        # exception types; log the full trace for debugging but keep
        # the client-facing message generic.
        logger.exception("parse failed for upload filename=%r", file.filename)
        raise HTTPException(status_code=400, detail="failed to parse book")

    try:
        book_id = storage.book_save(parsed, user_id=user.id)
    except Exception:
        logger.exception("book_save failed for upload filename=%r", file.filename)
        raise HTTPException(status_code=500, detail="failed to save book")

    meta = storage.book_meta(book_id, user_id=user.id)
    # meta should never be None right after a successful book_save, but
    # guard defensively so a racing DELETE doesn't turn into an
    # AttributeError.
    if meta is None:
        raise HTTPException(status_code=500, detail="failed to save book")
    logger.info(
        "book uploaded: id=%d title=%r size=%d",
        book_id,
        meta.title,
        len(data),
    )
    return {
        "book_id": book_id,
        "title": meta.title,
        "total_pages": meta.total_pages,
    }


# ---------- debug / observability (M14.1) ----------


@app.get("/debug/health")
def debug_health() -> dict:
    """Return a small, secret-free liveness + metadata blob.

    Public on purpose — designed for uptimerobot-style checks. Exposes
    only aggregate counts and process metadata, nothing per-user. The
    ``translate_counters`` block mirrors the M6.2 in-memory counters so
    a quick "are we hitting cache?" sanity-check doesn't need a shell.
    """
    return {
        "status": "ok",
        "git_sha": _get_git_sha(),
        "uptime_seconds": int((datetime.now(timezone.utc) - _startup_ts).total_seconds()),
        "counts": {
            "users": storage.count_users(),
            "books": storage.count_books(),
        },
        "translate_counters": {
            "hit": counters.translate_hit,
            "miss": counters.translate_miss,
        },
    }


@app.get("/debug/logs")
def debug_logs(
    n: int = 200,
    user: User = Depends(get_current_user),
) -> Response:
    """Return the tail of the in-memory log buffer as ``text/plain``.

    Auth: ``get_current_user`` rejects anonymous callers with 401; the
    extra admin check below returns 403 unless the signed-in user's
    email matches ``ADMIN_EMAIL`` *and* that env var is non-empty
    (keeping the route closed on hosts that forgot to set it). ``n`` is
    clamped to ``[1, 1000]`` so a bogus query string can't ask for more
    than the buffer actually holds.
    """
    admin_email = os.getenv("ADMIN_EMAIL", "")
    if not admin_email or user.email != admin_email:
        raise HTTPException(status_code=403)
    n = min(max(n, 1), 1000)
    lines = get_ring().tail(n)
    return Response(
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for SPA deep links; let /api/* and /static/* 404 normally."""
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    return FileResponse(_STATIC_DIR / "index.html")
