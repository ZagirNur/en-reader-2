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

import hashlib
import logging
import os
import re
import secrets
import subprocess
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from en_reader import storage, tg, tokens
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
from en_reader.translate import (
    TranslateError,
    build_rich_card,
    generate_training_card,
    simplify_one,
    translate_one,
)

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


def _secret_key_path() -> Path:
    """Return the absolute path for the persisted session-cookie secret.

    Anchored to the same directory as ``DB_PATH`` (default ``data/``) so
    the key travels with the DB: a redeploy that preserves the DB file
    also preserves every live session. The path is resolved to an
    absolute one up-front so a later ``os.chdir`` or a differing
    ``WorkingDirectory`` between systemd restarts can't make us silently
    mint a fresh key in a stale cwd.
    """
    db = Path(os.environ.get("DB_PATH", "data/en-reader.db"))
    return (db.parent / ".secret_key").resolve()


def _secret_key() -> str:
    """Return a persistent SECRET_KEY, creating it on first call.

    Lookup order:

    1. ``SESSION_SECRET_KEY`` env var (from ``/opt/en-reader/.env``) —
       wins if set, so an operator can pin the key explicitly.
    2. The file returned by :func:`_secret_key_path` — created on first
       run with mode 0o600 and an absolute path so subsequent restarts
       read back the same bytes.
    3. A freshly minted 32-byte URL-safe token, persisted to the file
       above so the *next* restart finds it.

    Never falls back to "mint a new one every process start" silently —
    that was the M11.2 bug where sessions evaporated on every deploy
    whenever the file hadn't been reachable at import time.
    """
    env_key = (os.environ.get("SESSION_SECRET_KEY") or "").strip()
    if env_key:
        return env_key
    path = _secret_key_path()
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    path.write_text(key)
    os.chmod(path, 0o600)
    return key


SECRET_KEY = _secret_key()
# M19.6: log a short fingerprint of the secret (NEVER the secret itself)
# so two consecutive /debug/health or journalctl lines can confirm the
# key survived a redeploy. A flapping id here is a smoking gun for a
# sessions-dropping regression.
_SECRET_KEY_ID = hashlib.sha256(SECRET_KEY.encode("utf-8")).hexdigest()[:8]
logger.info("session secret id=%s path=%s", _SECRET_KEY_ID, _secret_key_path())


# ---------- Telegram integration (M18.1) ----------

# Bot token must NEVER be checked into the repo — only read from the
# runtime environment (populated from /opt/en-reader/.env by systemd).
_TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
# The webhook URL the bot POSTs updates to. PUBLIC_ORIGIN is set in
# production (.env) to the Cloudflare-fronted domain so Telegram's
# reverse DNS check passes.
_PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "").strip().rstrip("/")
# Guard path so only Telegram can hit the webhook endpoint.
_TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET") or secrets.token_urlsafe(32)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Run DB migrations on startup + register the Telegram webhook."""
    storage.migrate()
    if _TELEGRAM_BOT_TOKEN and _PUBLIC_ORIGIN:
        # Best-effort: failure here shouldn't block the app from coming up.
        # Common cause of a failure is Telegram's rate-limit on repeated
        # setWebhook calls during rapid autopull cycles; a retry on the
        # next restart is fine.
        try:
            tg.set_webhook(
                _TELEGRAM_BOT_TOKEN,
                f"{_PUBLIC_ORIGIN}/tg/webhook",
                secret_token=_TELEGRAM_WEBHOOK_SECRET,
            )
            tg.set_chat_menu_button(_TELEGRAM_BOT_TOKEN, _PUBLIC_ORIGIN)
            logger.info("telegram webhook + menu button registered")
        except Exception:
            logger.exception("telegram setup failed (non-fatal)")
    yield


# ---------- security middlewares (M14.2) ----------

# Content-Security-Policy: lock every subresource to the same origin, with
# a few narrow whitelists:
#   * ``img-src data:`` — we serve inline book illustrations as real
#     ``/api/.../images/...`` URLs today, but keep ``data:`` on the
#     allowlist defensively so a future embed (e.g. a 1x1 pixel) doesn't
#     break.
#   * ``style-src 'unsafe-inline'`` — the SPA sets a lot of ``element.style``
#     properties from JavaScript (layout tweaks, dynamic colours, pbar
#     widths). Under CSP3 these counts as "style attributes" and fall back
#     to ``style-src`` when ``style-src-attr`` is absent, so without
#     ``'unsafe-inline'`` every ``el.style.foo = 'bar'`` is silently
#     blocked and the UI renders unstyled. We do NOT load any third-party
#     stylesheets beyond Google Fonts, so the attack surface remains
#     restricted to same-origin script injection — which is already
#     blocked by the matching ``script-src 'self'``.
#   * Google Fonts — ``index.html`` loads the Geist family from
#     ``fonts.googleapis.com`` (stylesheet) + ``fonts.gstatic.com`` (the
#     actual font files) since M3.3.
# ``frame-ancestors`` is the modern replacement for XFO. M18.1: allow the
# Telegram web clients to embed us so the Mini App iframe renders in
# Telegram Web / Desktop. Native mobile Telegram uses a WebView (no
# iframe) and is unaffected by either this or XFO. We drop XFO entirely
# since it has no multi-origin mode — any browser modern enough to be
# running Telegram's web client also supports frame-ancestors.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https://t.me; "
    "connect-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "script-src 'self' https://telegram.org; "
    "font-src 'self' https://fonts.gstatic.com; "
    "frame-ancestors 'self' https://web.telegram.org https://telegram.org"
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
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


# M17.8: Cloudflare (or any reverse proxy we trust) talks to the origin
# over plain HTTP, so ``request.base_url`` resolves to ``http://<ip>/``
# even though the browser's visible URL is ``https://enreader.zagirnur.dev/``.
# Without an explicit allow-list, every in-browser POST gets a 403 from
# the Origin check because ``https://enreader.zagirnur.dev`` does not
# start with ``http://138.201.153.242``. Configure the public URL(s)
# via ``ALLOWED_ORIGINS`` (comma-separated, no trailing slash).
_ALLOWED_ORIGINS = tuple(
    o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
)


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Cheap CSRF guard on top of ``SameSite=Lax`` session cookies.

    For any non-safe method (POST/PUT/PATCH/DELETE) we look at
    ``Origin`` first, then ``Referer``. The header must match either
    the request's own ``base_url`` (same-origin / no proxy) OR one of
    the ``ALLOWED_ORIGINS`` env-configured prefixes (trusted public
    hostnames behind a reverse proxy). If neither header is present we
    allow the request through — a handful of legitimate clients
    (``navigator.sendBeacon`` in some browsers, server-to-server curl)
    omit both, and blocking them would be more user-visible breakage
    than the attack surface it closes. The session cookie's
    ``SameSite=Lax`` flag still protects against the classic cross-site
    form-post case.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin") or request.headers.get("referer", "")
            if origin:
                expected = str(request.base_url).rstrip("/")
                if not origin.startswith(expected) and not any(
                    origin.startswith(a) for a in _ALLOWED_ORIGINS
                ):
                    return JSONResponse(
                        {"detail": "forbidden origin"},
                        status_code=403,
                    )
        return await call_next(request)


app = FastAPI(
    title="en-reader",
    description=(
        "English-reader backend: SQLite-backed per-user dictionary, "
        "Gemini-powered translation + simplification, SRS training cards, "
        "Telegram Mini-App auth, bearer-token auth for native / extension "
        "clients."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------- M21: path-rewrite alias /api/v1/* → /api/* ----------
#
# Native / extension clients call ``/api/v1/…`` so we have a stable
# surface independent of internal churn. Inside the app every route is
# still declared under ``/api/…``; this middleware rewrites the path
# on the request object so the route resolver matches. The contract
# with ``/api/v1/*`` is "only add fields, never rename, never remove".
class ApiVersionRewriteMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # noqa: D401 — framework hook
        path = request.scope.get("path", "")
        if path.startswith("/api/v1/"):
            new_path = "/api/" + path[len("/api/v1/") :]
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
        return await call_next(request)


# Middleware registration in Starlette wraps **around** previously-added
# middleware, so the last ``add_middleware`` call runs first on the way
# in. We want, inbound:
#     OriginCheck  →  SessionMiddleware  →  SecurityHeaders  →  route
# so we register in the reverse order: SecurityHeaders first (innermost,
# runs last inbound / first outbound → always stamps headers), then
# SessionMiddleware (so the Origin check sees session cookies if it ever
# needs them), then OriginCheck outermost (reject CSRF before we touch
# the session or any route handler).
# M21: CORS for mobile / extension clients. The env var
# ``CORS_ALLOW_ORIGINS`` is comma-separated (e.g.
# ``https://enreader.zagirnur.dev,https://staging.example.com``). A
# regex-allowlist covers the two well-known browser-extension origin
# prefixes (Chromium + Firefox). Credentials are allowed on the cookie
# path; bearer-token clients don't need them. If nothing is configured
# and we aren't in prod, we fall back to a dev-friendly wildcard that
# still refuses credentials — a compromise that keeps ``curl`` / local
# dev working without handing cookies to arbitrary origins.
_CORS_ORIGINS = tuple(
    o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
)
_CORS_REGEX = r"^(chrome-extension|moz-extension|safari-web-extension)://[^/]+$"
from fastapi.middleware.cors import CORSMiddleware  # local import to keep the top tidy

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_CORS_ORIGINS) if _CORS_ORIGINS else [],
    allow_origin_regex=_CORS_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

app.add_middleware(SecurityHeadersMiddleware)
# SessionMiddleware goes on before any routes run — Starlette walks the
# middleware stack on every request, so position doesn't affect route
# resolution, only the visible order of request/response callbacks.
# ``https_only`` only flips on in prod because the dev server is plain HTTP.
# Starlette's SessionMiddleware always sets HttpOnly internally (the JS
# side has no business reading this cookie), so no ``http_only`` kwarg
# is needed or accepted on current Starlette versions.
# M18.1: in prod use ``SameSite=None`` so the cookie round-trips through
# the Telegram Mini App iframe (Telegram Web/Desktop embeds us cross-site,
# and ``Lax`` cookies are stripped from fetches made inside a third-party
# iframe). ``None`` requires ``Secure``, which is already on in prod via
# ``https_only``. Dev keeps ``Lax`` because ``None`` without ``Secure`` is
# rejected outright by modern browsers.
_IS_PROD = os.getenv("ENV") == "prod"
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="sess",
    max_age=60 * 60 * 24 * 30,  # 30 days
    same_site="none" if _IS_PROD else "lax",
    https_only=_IS_PROD,
)
app.add_middleware(OriginCheckMiddleware)
# ApiVersionRewriteMiddleware sits OUTSIDE OriginCheck so route
# resolution sees the rewritten ``/api/*`` path, but the Origin check
# runs on the already-rewritten request. Outermost in add_middleware
# order = last-added = first-to-run on inbound.
app.add_middleware(ApiVersionRewriteMiddleware)
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
    # M19.1: per-instance translation sends one sentence before and after
    # the target so the LLM can disambiguate word sense. Either may be
    # blank at a page/book boundary; the caller still sends the field.
    prev_sentence: str = Field(default="", max_length=2000)
    next_sentence: str = Field(default="", max_length=2000)
    # M20.3: which side of the LLM the caller wants. ``translate`` is
    # the legacy EN→RU dictionary path (returns Russian + populates
    # user_dictionary). ``simplify`` returns the simplest English
    # synonym in the same grammatical form, OR a sentinel that the
    # word is already simplest. Simplify mode does NOT touch
    # user_dictionary or the background card builder.
    # M21: ``None`` means "unset" — the single endpoint normalises to
    # ``translate`` while the batch endpoint can tell an unset item
    # apart from an item that explicitly pinned ``translate``.
    mode: str | None = Field(default=None, pattern=r"^(translate|simplify)$")


class TranslateResponse(BaseModel):
    ru: str
    # M19.4: where the payload came from — "dict" (user already had this
    # lemma in their dictionary), "cache" (prompt-hash hit in llm_cache,
    # no Gemini call), "llm" (fresh Gemini call), "mock" (E2E shim). The
    # reader renders a different toast per source on manual word clicks.
    source: str = "llm"
    # M20.3: simplify-mode-only fields. ``text`` is the EN replacement
    # word; ``is_simplest`` says the input is already the simplest form
    # so the frontend should NOT replace the span and should just open
    # the card directly. Both default to neutral values for the
    # translate path so the response shape stays uniform.
    text: str | None = None
    is_simplest: bool = False
    mode: str = "translate"


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


def _uid_from_bearer(request: Request) -> int | None:
    """Resolve a ``Authorization: Bearer <token>`` header to a user_id.

    Returns ``None`` if the header is missing, malformed, or the token
    is expired / revoked. Exists so ``get_current_user`` can accept
    cookie sessions AND bearer tokens without duplicating the DB lookup.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return tokens.verify_access(parts[1].strip())


def get_current_user(request: Request) -> User:
    """FastAPI dependency: resolve the signed-in user or 401.

    Accepts either a Starlette session cookie (web SPA / Mini App) or
    a bearer token from the M21 ``/auth/token`` endpoint (native
    mobile / browser extensions). Bearer takes precedence — if both
    are sent (shouldn't happen in practice) the bearer wins because
    the ``Authorization`` header is a direct opt-in per request.
    """
    uid = _uid_from_bearer(request)
    if uid is None:
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


def _background_build_card(
    user_id: int, lemma: str, unit_text: str, sentence: str, ru: str
) -> None:
    """Generate and persist the training card for ``lemma``.

    M20.1: the primary card is now the structured JSON shape built by
    :func:`build_rich_card` (open dictionary + Gemini Russian layer).
    We also still fill ``card_text`` with the legacy Markdown flavour
    so older clients have something to render; both land under the
    same ``card_generated_at`` stamp via :func:`storage.card_set`.

    Runs via FastAPI :class:`BackgroundTasks` after the translate
    response is already on the wire, so the click feels instant to
    the user. Any failure is swallowed — a missing card is a graceful
    degradation and the next translation of this lemma retries.
    """
    import json as _json

    card_json: str | None = None
    try:
        rich = build_rich_card(unit_text, ru, sentence)
        card_json = _json.dumps(rich, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        logger.exception("rich-card gen failed: lemma=%r", lemma)

    card_text: str | None = None
    try:
        card_text = generate_training_card(unit_text, ru, sentence)
    except Exception:  # noqa: BLE001
        logger.exception("markdown-card gen failed: lemma=%r", lemma)

    if card_text is None and card_json is None:
        return
    storage.card_set(lemma, card_text, card_json=card_json, user_id=user_id)
    logger.info(
        "card stored: lemma=%r md_len=%d json_len=%d",
        lemma,
        len(card_text or ""),
        len(card_json or ""),
    )


class TranslateBatchRequest(BaseModel):
    """M21: batched ``/api/translate/batch`` payload.

    Capped at 50 items per request so a misbehaving client can't
    saturate the rate limiter (each item still counts as one hit) and
    we keep per-response latency bounded. Each item carries the same
    shape as a single ``TranslateRequest``.
    """

    items: list[TranslateRequest] = Field(min_length=1, max_length=50)
    # Caller MAY pin a single ``mode`` for the whole batch — convenient
    # for readers that only issue translate or only simplify at a time.
    # Per-item ``mode`` inside ``items`` wins when set.
    mode: str | None = Field(default=None, pattern=r"^(translate|simplify)$")


class TranslateBatchResponse(BaseModel):
    results: list[TranslateResponse]


@app.post(
    "/api/translate/batch",
    response_model=TranslateBatchResponse,
    tags=["translate"],
)
def translate_batch(
    req: TranslateBatchRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> TranslateBatchResponse:
    """Run up to 50 per-instance translations in one round-trip.

    Each item is processed sequentially through the same
    :func:`translate_one` / :func:`simplify_one` plumbing as the
    singular endpoint, so every item hits the prompt-hash
    ``llm_cache`` just like a stand-alone click. Rate-limit counts
    each item (so a batch of 50 burns 50 slots out of the 300/min
    window), keeping the abuse surface identical to 50 individual
    POSTs.

    Errors on a single item DON'T fail the whole batch: a 502 from
    Gemini for item #17 returns ``{"ru":"","source":"error","mode":"translate"}``
    at index 17 and every other slot still carries its real result.
    """
    results: list[TranslateResponse] = []
    for item in req.items:
        if not rl_translate.check(str(user.id)):
            raise HTTPException(
                status_code=429,
                detail="slow down",
                headers={"Retry-After": str(rl_translate.window)},
            )
        eff_mode = item.mode or req.mode or "translate"
        # Route through the same handler logic by building a single
        # ``TranslateRequest`` with the effective mode and calling the
        # inner worker directly. Keeping the plumbing here (rather than
        # calling the FastAPI handler) avoids re-paying the
        # Depends(get_current_user) round-trip 50× per batch.
        try:
            if eff_mode == "simplify":
                simplified, is_simplest, src = simplify_one(
                    item.unit_text,
                    item.sentence,
                    prev_sentence=item.prev_sentence,
                    next_sentence=item.next_sentence,
                )
                results.append(
                    TranslateResponse(
                        ru=simplified or item.unit_text,
                        source=src,
                        text=simplified,
                        is_simplest=is_simplest,
                        mode="simplify",
                    )
                )
                continue
            existing = storage.dict_get(item.lemma, user_id=user.id)
            ru, llm_source = translate_one(
                item.unit_text,
                item.sentence,
                prev_sentence=item.prev_sentence,
                next_sentence=item.next_sentence,
            )
            source = "dict" if existing is not None else llm_source
            if existing is None:
                counters.translate_miss += 1
                storage.dict_add(
                    item.lemma,
                    ru,
                    user_id=user.id,
                    example=item.sentence,
                    source_book_id=item.source_book_id,
                )
                background.add_task(
                    _background_build_card,
                    user_id=user.id,
                    lemma=item.lemma,
                    unit_text=item.unit_text,
                    sentence=item.sentence,
                    ru=ru,
                )
            else:
                counters.translate_hit += 1
                if storage.card_get(item.lemma, user_id=user.id) is None:
                    background.add_task(
                        _background_build_card,
                        user_id=user.id,
                        lemma=item.lemma,
                        unit_text=item.unit_text,
                        sentence=item.sentence,
                        ru=ru,
                    )
            results.append(
                TranslateResponse(
                    ru=ru,
                    source=source,
                    text=None,
                    is_simplest=False,
                    mode="translate",
                )
            )
        except TranslateError as e:
            logger.warning("batch item failed: lemma=%r err=%r", item.lemma, e)
            results.append(
                TranslateResponse(
                    ru="",
                    source="error",
                    text=None,
                    is_simplest=False,
                    mode=eff_mode,
                )
            )
    return TranslateBatchResponse(results=results)


@app.post("/api/translate", response_model=TranslateResponse)
def translate(
    req: TranslateRequest,
    background: BackgroundTasks,
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
    # M20.3: simplify mode — return the simplest English synonym in the
    # same grammatical form, or a sentinel that the input is already
    # simplest. Skips dict_add and the background card task entirely;
    # those belong to the translate path's RU-vocab semantics.
    req_mode = req.mode or "translate"
    if req_mode == "simplify":
        try:
            simplified, is_simplest, src = simplify_one(
                req.unit_text,
                req.sentence,
                prev_sentence=req.prev_sentence,
                next_sentence=req.next_sentence,
            )
        except TranslateError as e:
            raise HTTPException(status_code=502, detail=str(e))
        # ``ru`` carries the EN replacement so the legacy field stays
        # populated; the frontend reads ``text`` + ``is_simplest`` for
        # the simplify path.
        return TranslateResponse(
            ru=simplified or req.unit_text,
            source=src,
            text=simplified,
            is_simplest=is_simplest,
            mode="simplify",
        )

    # M19.1: per-instance translation — every call goes through
    # translate_one, which itself hits the prompt-hash llm_cache. We no
    # longer short-circuit on dict_get because the same lemma in a
    # different sentence must yield its own context-aware translation.
    # The counters stay for observability; "hit" now reflects the
    # cache-layer hit reported by translate_one (approximated here as a
    # miss, since we don't get a signal back).
    existing = storage.dict_get(req.lemma, user_id=user.id)
    logger.info("translate call: lemma=%r has_prev=%s", req.lemma, bool(req.prev_sentence))
    try:
        ru, llm_source = translate_one(
            req.unit_text,
            req.sentence,
            prev_sentence=req.prev_sentence,
            next_sentence=req.next_sentence,
        )
    except TranslateError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # M19.4: "dict" takes precedence — if the lemma is already in the
    # user's dictionary, that's the user-facing story regardless of
    # what translate_one did under the hood. Otherwise report how
    # translate_one obtained the text: "cache" for a prompt-hash hit,
    # "llm" for a fresh Gemini round-trip, "mock" for E2E.
    source = "dict" if existing is not None else llm_source

    # First time we see this lemma for this user → add to their dictionary
    # (so it joins the SRS pool) and schedule a background card build.
    # ``source_book_id`` is not ownership-checked: the FK already targets
    # the caller's own books via ON DELETE SET NULL.
    if existing is None:
        counters.translate_miss += 1
        storage.dict_add(
            req.lemma,
            ru,
            user_id=user.id,
            example=req.sentence,
            source_book_id=req.source_book_id,
        )
        background.add_task(
            _background_build_card,
            user_id=user.id,
            lemma=req.lemma,
            unit_text=req.unit_text,
            sentence=req.sentence,
            ru=ru,
        )
    else:
        counters.translate_hit += 1
        # Card backfill: if the lemma is in the dict but was added before
        # M19.1, or its first background attempt failed, retry now.
        if storage.card_get(req.lemma, user_id=user.id) is None:
            background.add_task(
                _background_build_card,
                user_id=user.id,
                lemma=req.lemma,
                unit_text=req.unit_text,
                sentence=req.sentence,
                ru=ru,
            )
    return TranslateResponse(ru=ru, source=source)


@app.get("/api/dictionary")
def api_dictionary_list(user: User = Depends(get_current_user)) -> dict[str, str]:
    """Legacy flat ``{lemma: translation}`` map used by pre-M16.3 clients.

    Kept as-is so the reader's auto-highlight path (which only needs the
    key set) and existing tests keep working. The richer list-of-objects
    shape lives at :func:`api_dictionary_words` below.
    """
    return storage.dict_all(user_id=user.id)


@app.get("/api/dictionary/sync", tags=["dictionary"])
def api_dictionary_sync(
    since: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """M21: delta-sync for mobile/extension clients.

    Returns ``{server_time, since, upserts: [...], deletes: [...]}``.
    Each upsert is a full ``user_dictionary`` row (enough to populate a
    local cache without a second round-trip). ``since`` is an ISO-8601
    timestamp the client previously received as ``server_time`` — the
    server filters by ``updated_at > since`` / ``deleted_at > since``
    so the response size is O(delta).

    Omit ``since`` on the first call to fetch a full snapshot; save
    the returned ``server_time`` and pass it as ``since=`` on the next
    call. A client that rolls back its clock is safe: the server uses
    its own wall clock for both reads and the returned server_time.
    """
    return storage.dict_sync(since=since, user_id=user.id)


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


@app.get("/api/dictionary/{lemma}/card")
def api_dictionary_card(
    lemma: str,
    user: User = Depends(get_current_user),
) -> Response:
    """M20.1: return the structured training card for ``lemma`` as JSON.

    ``card_json`` is populated by the background task kicked off on the
    first translation — so a fresh click on a word returns an empty
    payload here for a second or two until the card lands. The
    frontend polls or shows a "Карточка готовится…" placeholder rather
    than blocking. Also 404s on a lemma the user doesn't own so a
    curious client can't enumerate other users' vocab lists.
    """
    import json as _json

    if storage.dict_get(lemma, user_id=user.id) is None:
        raise HTTPException(status_code=404)
    raw = storage.card_json_get(lemma, user_id=user.id)
    if not raw:
        return JSONResponse({"ready": False, "card": None})
    try:
        card = _json.loads(raw)
    except _json.JSONDecodeError:
        card = None
    return JSONResponse({"ready": card is not None, "card": card})


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


@app.get("/api/me/streak")
def api_me_streak(user: User = Depends(get_current_user)) -> dict:
    """Return the caller's current streak + today's daily-goal progress.

    M16.8: one endpoint feeds both the Library streak card and the Learn
    Home daily-goal card — enough for the MVP retention widgets without a
    separate daily-activity API. ``streak`` counts consecutive UTC days
    with ≥1 training answer; ``today`` carries ``{target, done, percent}``
    where ``done`` is today's correct-answer tally.
    """
    return {
        "streak": storage.compute_streak(user.id),
        "today": storage.today_goal(user.id),
    }


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


# ---------- Telegram Mini App auth + webhook (M18.1) ----------


class TelegramAuthIn(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


@app.post("/auth/telegram")
def auth_telegram(p: TelegramAuthIn, request: Request) -> dict:
    """Sign a Telegram Mini-App user into a session.

    Expects ``init_data`` — the raw ``Telegram.WebApp.initData`` string
    the client reads from its WebView. We HMAC-verify it (bot token is
    the shared secret), map the Telegram user id to a local row via
    ``user_upsert_telegram``, and stamp the session cookie the rest of
    the /api/* routes already honour. 401 on any verification failure
    — no leak about which step failed.

    M18.2: verbose logs on every branch so production issues (client
    sending empty initData, HMAC drift, etc.) are debuggable from
    ``journalctl -u en-reader``. Only the length + last 6 chars of the
    hash are logged — the user payload and full signature stay private.
    """
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:80]
    origin = request.headers.get("origin", "")
    init_len = len(p.init_data or "")
    init_tail = (p.init_data or "")[-12:]
    logger.info(
        "auth/telegram: ip=%s ua=%r origin=%r init_len=%d init_tail=%r",
        ip,
        ua,
        origin,
        init_len,
        init_tail,
    )
    if not _TELEGRAM_BOT_TOKEN:
        logger.warning("auth/telegram: 503 — TELEGRAM_BOT_TOKEN not configured")
        raise HTTPException(status_code=503, detail="telegram disabled")
    if not auth_ratelimit.check(ip):
        logger.warning("auth/telegram: 429 — rate-limited ip=%s", ip)
        raise HTTPException(status_code=429, detail="too many attempts")
    try:
        tg_user = tg.verify_init_data(p.init_data, _TELEGRAM_BOT_TOKEN)
    except tg.InvalidInitDataError as e:
        logger.warning("auth/telegram: 401 — verify failed: %s", e)
        raise HTTPException(status_code=401, detail="invalid telegram init")
    user = storage.user_upsert_telegram(tg_user.id, display_name=tg_user.first_name)
    request.session["user_id"] = user.id
    logger.info(
        "auth/telegram: 200 — tg_id=%d user_id=%d username=%r",
        tg_user.id,
        user.id,
        tg_user.username,
    )
    return {"email": user.email, "telegram_id": tg_user.id}


class TelegramDiagIn(BaseModel):
    event: str = Field(min_length=1, max_length=64)
    detail: str = Field(default="", max_length=512)


@app.post("/tg/diag")
def tg_diag(p: TelegramDiagIn, request: Request) -> dict:
    """Client-side breadcrumb from the Mini App into our server log.

    M18.2: the Telegram WebView doesn't expose DevTools on mobile, so
    when the auto-login flow fails silently we have no way to see what
    the client saw. This endpoint is a write-only log drain — the
    frontend POSTs short tags ("sdk_missing", "init_empty", etc.) and
    we land them in journalctl alongside the /auth/telegram attempts.
    No auth gate: the worst a malicious client can do is spam our log.
    """
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:80]
    logger.info("tg/diag: ip=%s event=%r detail=%r ua=%r", ip, p.event, p.detail, ua)
    return {"ok": True}


def _account_summary(user_id: int) -> str:
    """One-line account summary the Telegram confirm-keyboard shows.

    Counts are read cheaply — the link-flow call site is webhook-scoped
    and only fires once per conflicting linkage, so a few SELECTs don't
    need caching. Returns e.g. "12 слов, 3 книги".
    """
    conn = storage.get_db()
    words = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM user_dictionary WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
    )
    books = int(
        conn.execute("SELECT COUNT(*) AS n FROM books WHERE user_id = ?", (user_id,)).fetchone()[
            "n"
        ]
    )

    def _plural(n: int, one: str, few: str, many: str) -> str:
        if 11 <= (n % 100) <= 14:
            return many
        r = n % 10
        if r == 1:
            return one
        if 2 <= r <= 4:
            return few
        return many

    return (
        f"{words} {_plural(words, 'слово', 'слова', 'слов')}, "
        f"{books} {_plural(books, 'книга', 'книги', 'книг')}"
    )


def _handle_link_start(token_str: str, from_id: int, chat_id: int) -> None:
    """Process ``/start link_<token>`` inside the webhook.

    Handles all four paths in one place so the webhook entrypoint stays
    a thin dispatcher:

    1. Token missing / expired → tell the user to click Link again.
    2. Already linked (token.user_id already carries this tg_id) → no-op
       message, mark token done so the poller stops.
    3. No other user has this tg_id → write telegram_id onto the link
       initiator and reply "привязано".
    4. Another user has this tg_id:
       * If either side is empty → merge silently into the non-empty
         account (dest = session user, winner = whichever has data).
       * Else show the inline keyboard, flip status to
         ``conflict_waiting`` and let the callback_query handler finish.
    """
    link = storage.link_token_get(token_str)
    if link is None or link.status != "pending":
        tg.send_plain(
            _TELEGRAM_BOT_TOKEN,
            chat_id,
            "Ссылка для привязки просрочена — нажми «Привязать Telegram» снова.",
        )
        return
    dest = storage.user_by_id(link.user_id)
    if dest is None:
        storage.link_token_update(token_str, status="failed", result="dest gone")
        tg.send_plain(_TELEGRAM_BOT_TOKEN, chat_id, "Аккаунт не найден.")
        return
    if dest.telegram_id == from_id:
        storage.link_token_update(token_str, status="done", result="already_linked")
        tg.send_plain(_TELEGRAM_BOT_TOKEN, chat_id, "Этот Telegram уже привязан.")
        return
    existing = storage.user_by_telegram(from_id)
    if existing is None:
        # Easy path: claim the tg_id on dest. M18.4 partial UNIQUE
        # (dest didn't have one) means a straight UPDATE is safe.
        conn = storage.get_db()
        with conn:
            conn.execute(
                "UPDATE users SET telegram_id = ? WHERE id = ?",
                (from_id, dest.id),
            )
        storage.link_token_update(token_str, status="done", result="linked")
        tg.send_plain(_TELEGRAM_BOT_TOKEN, chat_id, "Привязал! Возвращайся в приложение.")
        return
    # Both exist. Decide: auto-merge or ask.
    dest_has = storage.user_has_data(dest.id)
    src_has = storage.user_has_data(existing.id)
    if not dest_has or not src_has:
        # Auto-merge: winner is always dest (the session user) — we move
        # src's data into dest regardless of which side was empty, since
        # dest is what the active session is logged in as.
        storage.user_merge(dest_id=dest.id, src_id=existing.id)
        storage.link_token_update(token_str, status="done", result="merged_auto")
        tg.send_plain(
            _TELEGRAM_BOT_TOKEN,
            chat_id,
            "Привязал и объединил данные. Возвращайся в приложение.",
        )
        return
    # Conflict: both sides have data → inline keyboard.
    dest_summary = _account_summary(dest.id)
    src_summary = _account_summary(existing.id)
    try:
        resp = tg.send_link_choice(
            _TELEGRAM_BOT_TOKEN, chat_id, token_str, dest_summary, src_summary
        )
    except Exception:
        logger.exception("send_link_choice failed")
        storage.link_token_update(token_str, status="failed", result="send_keyboard")
        return
    msg_id = int(resp.get("message_id") or 0) if isinstance(resp, dict) else 0
    storage.link_token_update(
        token_str,
        status="conflict_waiting",
        other_user_id=existing.id,
        chat_id=chat_id,
        message_id=msg_id,
    )


def _handle_link_callback(token_str: str, keep: str, callback_query: dict) -> None:
    """Resolve the user's "which account to keep" choice from the keyboard.

    ``keep`` ∈ {"dest", "src"}:
    * ``dest`` → keep the email account, merge the tg-only one in.
    * ``src``  → keep the tg-only account, merge the email account in.
      The email user's session keeps their user_id; after the src→dest
      swap the session user_id still points at a valid row because dest
      inherits src's state via user_merge(dest=src_id, src=dest_id)...
      wait, that flips what "dest" means. Clarification: we always
      keep ``session user`` (= original link.user_id) in the session,
      but its content changes depending on which side "wins".
    """
    cqid = callback_query.get("id") or ""
    link = storage.link_token_get(token_str)
    if link is None or link.status != "conflict_waiting":
        tg.answer_callback(_TELEGRAM_BOT_TOKEN, cqid, "Ссылка просрочена")
        return
    email_user = storage.user_by_id(link.user_id)
    tg_user = storage.user_by_id(link.other_user_id) if link.other_user_id is not None else None
    if email_user is None or tg_user is None:
        tg.answer_callback(_TELEGRAM_BOT_TOKEN, cqid, "Аккаунт пропал")
        storage.link_token_update(token_str, status="failed", result="user_gone")
        return
    # If the email-user is about to be deleted (keep=="src"), the
    # link_tokens row's ON DELETE CASCADE would take the token with
    # it — so re-point the token's user_id to the surviving row before
    # the merge. Without this, the status poller would see the token
    # vanish and never learn that it needs to reissue the session.
    if keep == "src":
        conn = storage.get_db()
        with conn:
            conn.execute(
                "UPDATE link_tokens SET user_id = ? WHERE token = ?",
                (tg_user.id, token_str),
            )
    try:
        if keep == "dest":
            storage.user_merge(dest_id=email_user.id, src_id=tg_user.id)
            result_msg = "Оставили текущий (email). Данные Telegram-аккаунта перенесены."
        else:
            # Keep TG-account's data. Email account row is deleted at the
            # end of user_merge; the status endpoint then flips the session
            # cookie to the surviving tg_user id on the next poll.
            storage.user_merge(dest_id=tg_user.id, src_id=email_user.id)
            result_msg = "Оставили Telegram-аккаунт. Данные email-аккаунта перенесены."
    except Exception:
        logger.exception("user_merge failed for token %s", token_str)
        tg.answer_callback(_TELEGRAM_BOT_TOKEN, cqid, "Ошибка")
        storage.link_token_update(token_str, status="failed", result="merge_error")
        return
    # Record which user_id is the "surviving" one — the status poller
    # reads this to re-issue the session cookie when the surviving id
    # differs from the original session user.
    winner_id = email_user.id if keep == "dest" else tg_user.id
    storage.link_token_update(
        token_str,
        status="done",
        other_user_id=winner_id,
        result=f"merged_{keep}",
    )
    tg.answer_callback(_TELEGRAM_BOT_TOKEN, cqid, "Готово")
    if link.chat_id and link.message_id:
        try:
            tg.edit_message(
                _TELEGRAM_BOT_TOKEN, int(link.chat_id), int(link.message_id), result_msg
            )
        except Exception:
            logger.exception("edit_message failed for token %s", token_str)


@app.post("/tg/webhook")
async def tg_webhook(request: Request) -> Response:
    """Telegram → us update delivery.

    Flow:

    * ``/start`` (no args) → send the Mini-App launcher button.
    * ``/start link_<TOKEN>`` → run the account-linking protocol
      (:func:`_handle_link_start`).
    * ``callback_query`` with ``lk:<token>:<keep>`` data → resolve a
      pending link conflict (:func:`_handle_link_callback`).

    Everything else silent-200s so Telegram doesn't retry legitimate
    updates we don't care about yet. The secret-token check guards
    against forged POSTs to the public URL.
    """
    if not _TELEGRAM_BOT_TOKEN:
        return Response(status_code=503)
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if supplied != _TELEGRAM_WEBHOOK_SECRET:
        return Response(status_code=200)
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    # 1. callback_query path (inline keyboard clicks).
    cq = update.get("callback_query") or {}
    if cq:
        data = (cq.get("data") or "").strip()
        if data.startswith("lk:"):
            parts = data.split(":")
            if len(parts) == 3 and parts[2] in ("dest", "src"):
                try:
                    _handle_link_callback(parts[1], parts[2], cq)
                except Exception:
                    logger.exception("link callback failed")
        return Response(status_code=200)

    # 2. message path (/start and /start link_XXX).
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    frm = msg.get("from") or {}
    from_id = frm.get("id")
    if chat_id and text.startswith("/start"):
        if text.startswith("/start link_") and from_id is not None:
            token_str = text[len("/start link_") :].strip()
            if token_str:
                try:
                    _handle_link_start(token_str, int(from_id), int(chat_id))
                except Exception:
                    logger.exception("link start failed")
                return Response(status_code=200)
        webapp_url = _PUBLIC_ORIGIN or "https://enreader.zagirnur.dev"
        try:
            tg.send_start_reply(_TELEGRAM_BOT_TOKEN, int(chat_id), webapp_url)
        except Exception:
            logger.exception("send_start_reply failed")
    return Response(status_code=200)


# ---------- M18.4: authenticated link-flow endpoints ----------


@app.post("/auth/link/telegram/init")
def auth_link_telegram_init(request: Request, user: User = Depends(get_current_user)) -> dict:
    """Mint a one-time link token and return the deep link to hand off.

    The frontend opens ``deep_link`` in the Telegram app (or via
    ``Telegram.WebApp.openTelegramLink`` when we're already in the
    Mini App). The user's tap on "Start" in the bot chat sends
    ``/start link_<token>`` back, which the webhook consumes.
    """
    if not _TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="telegram disabled")
    # Derive the bot username from the token so we don't need a second
    # env var. Bot tokens are ``<numeric-id>:<opaque>``; the username
    # isn't in the token itself, so read /getMe once and cache.
    bot_username = _resolve_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="telegram misconfigured")
    token_str = storage.link_token_create(user.id)
    deep_link = f"https://t.me/{bot_username}?start=link_{token_str}"
    logger.info("auth/link/telegram/init: user_id=%d token=%s", user.id, token_str[:6])
    return {"token": token_str, "deep_link": deep_link}


@app.get("/auth/link/telegram/status")
def auth_link_telegram_status(token: str, request: Request) -> dict:
    """Poll the status of a pending link request.

    No ``Depends(get_current_user)`` — the 24-byte URL-safe token is
    itself the capability that authenticates this endpoint. Reasons:

    * The status endpoint needs to survive the keep-TG merge path,
      where the email-user row (which the browser's session cookie
      points at) is deleted as part of ``user_merge``. With Depends,
      the poller would 401 before it ever learned to re-issue.
    * The token has 192 bits of entropy, a 10-minute TTL, and only
      lands on the initiating frontend + the TG chat that scanned
      it — both under the user's control.

    On ``merged_src`` (keep-Telegram) we flip the session cookie to the
    surviving user id in the same response. ``_handle_link_callback``
    re-points ``link_tokens.user_id`` to the winner *before* the merge
    runs so the ON DELETE CASCADE on the email user doesn't take the
    token row with it.
    """
    link = storage.link_token_get(token)
    if link is None:
        return {"status": "expired", "result": None}
    payload: dict = {"status": link.status, "result": link.result}
    if link.status == "done" and link.result == "merged_src" and link.other_user_id is not None:
        request.session["user_id"] = link.other_user_id
        payload["session_reissued"] = True
    return payload


_BOT_USERNAME_CACHE: dict[str, str] = {}


def _resolve_bot_username() -> str | None:
    """Look up the bot's ``@username`` via ``getMe``; cached per-token.

    We don't require the operator to stuff the username into another
    env var — the Bot API exposes it, so we just ask once at first use
    and remember the answer. If the token is rotated the process
    restart will pick up the new one.
    """
    if not _TELEGRAM_BOT_TOKEN:
        return None
    cached = _BOT_USERNAME_CACHE.get(_TELEGRAM_BOT_TOKEN)
    if cached:
        return cached
    try:
        me = tg._call(_TELEGRAM_BOT_TOKEN, "getMe", {})
    except Exception:
        logger.exception("getMe failed")
        return None
    uname = me.get("username") if isinstance(me, dict) else None
    if uname:
        _BOT_USERNAME_CACHE[_TELEGRAM_BOT_TOKEN] = uname
    return uname


@app.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    """Clear the session cookie. Idempotent — 200 whether or not we had one."""
    request.session.clear()
    return Response(status_code=200)


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    """Return ``{"email": ...}`` for the signed-in user or 401."""
    # M21: accept bearer alongside cookie so a mobile/extension client
    # can hit /auth/me to probe its token without falling back to
    # cookie semantics.
    uid = _uid_from_bearer(request) or request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = storage.user_by_id(uid)
    if user is None:
        # The DB row backing this session is gone — drop the cookie
        # value so subsequent requests get a clean 401.
        request.session.clear()
        raise HTTPException(status_code=401)
    return {"email": user.email}


# ---------- M21: bearer-token endpoints ----------


class TokenRequest(BaseModel):
    """POST /auth/token input.

    One of two identification modes: ``password`` (email + password,
    same path as /auth/login) or ``telegram`` (init_data from the
    Mini-App SDK, same validation as /auth/telegram). Native mobile
    clients pick whichever they have.
    """

    mode: str = Field(pattern=r"^(password|telegram)$")
    email: str | None = None
    password: str | None = None
    init_data: str | None = Field(default=None, max_length=8192)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    access_expires_at: str
    refresh_expires_at: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=200)


@app.post("/auth/token", response_model=TokenResponse, tags=["auth"])
def auth_token(p: TokenRequest, request: Request) -> TokenResponse:
    """Exchange email/password or Telegram initData for a bearer pair.

    Rate-limited under the same bucket as /auth/login via
    :data:`auth_ratelimit` so brute-forcers hit the same ceiling.
    Returns an access + refresh token (opaque strings). The client
    sends ``Authorization: Bearer <access_token>`` on subsequent
    requests and calls /auth/token/refresh when the access token
    expires.
    """
    ip = _client_ip(request)
    if not auth_ratelimit.check(ip):
        raise HTTPException(status_code=429, detail="rate limited")

    if p.mode == "password":
        if not p.email or not p.password:
            raise HTTPException(status_code=400, detail="email and password required")
        try:
            email_norm = normalize_email(p.email)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid email")
        user = storage.user_by_email(email_norm)
        if user is None or not check_password(p.password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        return TokenResponse(**tokens.issue(user.id))

    # mode == "telegram"
    if not _TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="telegram not configured")
    if not p.init_data:
        raise HTTPException(status_code=400, detail="init_data required")
    try:
        tg_user = tg.verify_init_data(p.init_data, _TELEGRAM_BOT_TOKEN)
    except tg.InvalidInitDataError:
        raise HTTPException(status_code=401, detail="invalid telegram init")
    user = storage.user_upsert_telegram(
        tg_user.id,
        display_name=(tg_user.first_name or tg_user.username or str(tg_user.id))[:80],
    )
    return TokenResponse(**tokens.issue(user.id))


@app.post("/auth/token/refresh", response_model=TokenResponse, tags=["auth"])
def auth_token_refresh(p: RefreshRequest) -> TokenResponse:
    """Single-use refresh: burn the presented refresh and issue a new pair.

    ``None`` on an invalid / expired / already-used refresh token; we
    translate that to a 401 so the client re-authenticates via
    /auth/token. Single-use semantics blunt stolen-refresh replays — a
    thief gets at most one access-token-lifetime of abuse.
    """
    pair = tokens.rotate_refresh(p.refresh_token)
    if pair is None:
        raise HTTPException(status_code=401, detail="invalid refresh token")
    return TokenResponse(**pair)


class RevokeRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@app.post("/auth/token/revoke", status_code=204, tags=["auth"])
def auth_token_revoke(p: RevokeRequest) -> Response:
    """Explicitly revoke an access or refresh token.

    Idempotent: a token that's already revoked / never existed still
    returns 204. Handlers of this endpoint never leak the reason so a
    caller can't enumerate token validity.
    """
    tokens.revoke_token(p.token)
    return Response(status_code=204)


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
        # M19.7: prompt-hash cache visibility. ``hit`` / ``miss`` are
        # process-level counters from ``translate._cached_llm_call`` and
        # climb independently of dict state — watching them while a
        # reader scrolls through a known book should show ``hit`` dominate.
        # ``rows`` is the size of the persisted ``llm_cache`` table — one
        # row per unique (model, system, user-prompt) tuple.
        "llm_cache": {
            "hit": counters.llm_cache_hit,
            "miss": counters.llm_cache_miss,
            "rows": storage.llm_cache_count(),
        },
        # M19.6: 8-hex fingerprint of SECRET_KEY. Stable across redeploys
        # means sessions survive; a flapping value is the smoking gun for
        # a sessions-dropping regression.
        "session_key_id": _SECRET_KEY_ID,
    }


@app.get("/debug/tail")
def debug_tail(
    n: int = 50,
    grep: str = "translate|llm cache|auth/telegram",
    user: User = Depends(get_current_user),
) -> Response:
    """Return the tail of the log buffer filtered by a simple regex.

    Any authenticated user can read this — we scope the default filter
    to translate / cache / auth events so nothing user-specific from
    *other* accounts leaks (lemma content is already public per-user,
    and the filter cuts out things like email / signup lines). If the
    caller passes a custom ``grep`` that widens the scope, they still
    only see whatever lines happen to be in the shared ring buffer,
    which is bounded to 500 lines.

    Designed for M19.x diagnostics: the operator can click a word in
    the WebView, then hit ``/debug/tail`` to see the exact prompt hash
    and cache hit/miss without needing SSH to the host.
    """
    n = min(max(n, 1), 500)
    try:
        pattern = re.compile(grep)
    except re.error:
        raise HTTPException(status_code=400, detail="invalid regex in ?grep=")
    lines = [ln for ln in get_ring().tail(500) if pattern.search(ln)][-n:]
    return Response(
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8",
    )


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
