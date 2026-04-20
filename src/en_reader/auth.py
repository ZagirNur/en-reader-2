"""Password hashing, email normalisation, and a simple rate limiter (M11.2).

Kept deliberately small and dependency-light — the real auth API lives in
:mod:`en_reader.app`. This module only provides the primitives:

* ``hash_password`` / ``check_password`` around bcrypt, with the mandatory
  72-byte truncate so long passwords don't explode at hash time.
* ``normalize_email`` — validates and lowercases an email via
  ``email-validator`` so ``Foo@Example.com`` and ``foo@example.com`` map
  to a single user row.
* ``AuthRateLimit`` — a per-process, in-memory sliding-window limiter
  (10 hits / 60 s / IP) used by the signup/login routes. A single module-
  level instance ``auth_ratelimit`` is exposed; tests reset its internal
  state between cases to avoid cross-test bleed.
"""

from __future__ import annotations

import time
from collections import defaultdict

import bcrypt
from email_validator import EmailNotValidError, validate_email

# bcrypt silently ignores bytes past index 72, which turns long passwords
# into silent prefix-collisions. We truncate explicitly so the behaviour
# is at least deterministic and documented at our boundary.
BCRYPT_MAX = 72

# Sentinel written into ``users.password_hash`` by the v4→v5 migration for
# the seed row. It is *not* a valid bcrypt hash — ``check_password`` must
# reject it outright so a malicious client can't craft a password whose
# literal bytes happen to equal the sentinel.
PLACEHOLDER_HASH = "__migration_placeholder__"


class EmailExistsError(Exception):
    """Raised by :func:`en_reader.storage.user_create` on UNIQUE violation."""


def hash_password(password: str) -> str:
    """Hash ``password`` with bcrypt (cost 12), truncating to 72 bytes first."""
    pw = password.encode("utf-8")[:BCRYPT_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("ascii")


def check_password(password: str, hashed: str) -> bool:
    """Return ``True`` iff ``password`` verifies against ``hashed``.

    Rejects the migration placeholder sentinel outright, and swallows any
    bcrypt exception (malformed hash, unexpected bytes) as ``False`` — the
    caller only cares about the boolean.
    """
    if hashed == PLACEHOLDER_HASH:
        return False
    pw = password.encode("utf-8")[:BCRYPT_MAX]
    try:
        return bcrypt.checkpw(pw, hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    """Validate and lowercase ``email``.

    Returns the normalized form suitable for DB storage. Raises
    :class:`ValueError` with the validator's message on any syntactic or
    domain-level failure. ``check_deliverability=False`` skips DNS — we
    don't want signup flow blocked on a flaky resolver.
    """
    try:
        v = validate_email(email, check_deliverability=False)
    except EmailNotValidError as e:
        raise ValueError(str(e)) from e
    return v.normalized.lower()


class AuthRateLimit:
    """In-memory sliding-window rate limiter (10 hits / 60 s / key).

    Keyed by IP string. Stores the last-minute hit timestamps per key and
    prunes stale entries on each ``check``. Not thread-safe in the strict
    sense (dict mutation under the GIL is atomic for single statements,
    but the read-modify-write on the list isn't) — good enough for the
    single-worker dev server. A real deployment would front this with
    nginx or an external limiter.
    """

    WINDOW_SECONDS = 60.0
    MAX_HITS = 10

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, ip: str) -> bool:
        """Return ``True`` if the request is allowed, recording the hit.

        Returns ``False`` once the 11th attempt lands inside the same
        60-second window; the limiter does not count rejected attempts,
        so the window naturally empties out after a minute of quiet.
        """
        now = time.time()
        bucket = self._hits[ip]
        cutoff = now - self.WINDOW_SECONDS
        fresh = [t for t in bucket if t >= cutoff]
        if len(fresh) >= self.MAX_HITS:
            self._hits[ip] = fresh
            return False
        fresh.append(now)
        self._hits[ip] = fresh
        return True


# Module-level singleton — the auth routes import this directly. Tests
# reset ``auth_ratelimit._hits`` between cases to avoid cross-test bleed.
auth_ratelimit = AuthRateLimit()
