"""Bearer-token auth (M21) — opaque tokens hashed at rest.

Access + refresh tokens for native mobile / browser-extension clients.
The web SPA and Mini App keep using the cookie session; this module
layers on top, doesn't replace it.

Tokens are opaque strings ``er_`` + 43 URL-safe bytes. Only the sha256
digest lands in ``auth_tokens`` so a DB leak can't be replayed. The
module exposes a tiny DAO:

* :func:`issue` — mint an access+refresh pair for a user.
* :func:`verify_access` — resolve an access token → user_id or None.
* :func:`rotate_refresh` — validate a refresh token, issue a fresh
  access + refresh pair, revoke the consumed refresh (single-use
  refresh semantics blunt stolen-refresh replays).
* :func:`revoke_token` / :func:`revoke_all` — explicit logout.

Token prefix ``er_`` is purely a readability marker; security is all
in the random bytes + sha256-at-rest. A client that echoes the raw
token back on subsequent requests gets verified by SELECT by hash.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from . import storage

_TOKEN_PREFIX = "er_"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)


def _mint() -> str:
    """Return a fresh opaque token string (``er_<43 random urlsafe chars>``)."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(32)


def _hash(token: str) -> str:
    """sha256 hex digest of ``token`` — the form we persist."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def issue(user_id: int) -> dict:
    """Issue a fresh access + refresh pair for ``user_id``.

    Returns the raw tokens and their expiry ISO timestamps so the
    caller can hand them back to the client. The raw strings are
    never persisted; only their sha256 digests land in the DB.
    """
    now = datetime.now(timezone.utc)
    access = _mint()
    refresh = _mint()
    access_exp = now + ACCESS_TTL
    refresh_exp = now + REFRESH_TTL
    conn = storage.get_db()
    with conn:
        conn.execute(
            "INSERT INTO auth_tokens(token_hash, user_id, kind, expires_at, created_at) "
            "VALUES(?, ?, 'access', ?, ?)",
            (_hash(access), user_id, access_exp.isoformat(), now.isoformat()),
        )
        conn.execute(
            "INSERT INTO auth_tokens(token_hash, user_id, kind, expires_at, created_at) "
            "VALUES(?, ?, 'refresh', ?, ?)",
            (_hash(refresh), user_id, refresh_exp.isoformat(), now.isoformat()),
        )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "access_expires_at": access_exp.isoformat(),
        "refresh_expires_at": refresh_exp.isoformat(),
    }


def _verify(token: str, kind: str) -> int | None:
    """Resolve ``token`` of the expected ``kind`` to a user_id, or None.

    Rejects expired / revoked tokens without leaking the reason — the
    caller only cares about the user_id. No timing-attack concerns: the
    token itself is opaque random and the DB lookup is on a UNIQUE
    index, so the attacker can't probe structure.
    """
    if not token or not token.startswith(_TOKEN_PREFIX):
        return None
    conn = storage.get_db()
    row = conn.execute(
        "SELECT user_id, expires_at, revoked_at FROM auth_tokens "
        "WHERE token_hash = ? AND kind = ?",
        (_hash(token), kind),
    ).fetchone()
    if row is None:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] <= _now_iso():
        return None
    return int(row["user_id"])


def verify_access(token: str) -> int | None:
    """Return the user_id behind a non-expired, non-revoked access token."""
    return _verify(token, "access")


def rotate_refresh(refresh_token: str) -> dict | None:
    """Atomically burn ``refresh_token`` and mint a fresh pair.

    Single-use refresh: the consumed token is immediately marked
    ``revoked_at`` so a thief who intercepted the old refresh can't
    reuse it after the legitimate client has rotated. Returns ``None``
    if the input is invalid / expired / already revoked.
    """
    uid = _verify(refresh_token, "refresh")
    if uid is None:
        return None
    conn = storage.get_db()
    with conn:
        conn.execute(
            "UPDATE auth_tokens SET revoked_at = ? WHERE token_hash = ?",
            (_now_iso(), _hash(refresh_token)),
        )
    return issue(uid)


def revoke_token(token: str) -> bool:
    """Revoke a specific token (access or refresh). Returns True if a row was hit."""
    conn = storage.get_db()
    with conn:
        cur = conn.execute(
            "UPDATE auth_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (_now_iso(), _hash(token)),
        )
    return cur.rowcount > 0


def revoke_all(user_id: int) -> int:
    """Revoke every live token for ``user_id``. Used by full-logout flows."""
    conn = storage.get_db()
    with conn:
        cur = conn.execute(
            "UPDATE auth_tokens SET revoked_at = ? " "WHERE user_id = ? AND revoked_at IS NULL",
            (_now_iso(), user_id),
        )
    return cur.rowcount
