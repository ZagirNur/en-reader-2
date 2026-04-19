"""Shared pytest configuration for en-reader tests.

* Registers the ``--update-golden`` flag used by `tests/test_golden.py`
  to rewrite on-disk `.golden.json` fixtures when the pipeline's output
  is intentionally changed.
* Provides an autouse ``tmp_db`` fixture (M6.1) that pins ``DB_PATH`` to
  a fresh per-test SQLite file and runs migrations, so no test leaks
  dictionary state to another. Tests that don't touch storage pay a
  negligible cost — the DB only materializes on first ``get_db()`` call.
* Exposes a ``client`` fixture (M11.3) that signs up a fresh user and
  returns an authenticated :class:`TestClient`. Opt-in so non-API tests
  that genuinely want the unauthenticated app (``test_auth.py``,
  ``test_spa_routes.py``) keep working unchanged. The companion
  :data:`FIXTURE_EMAIL` is the email the fixture user is created with —
  seed scripts that need to attach books to this user should pass it as
  ``email=FIXTURE_EMAIL``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Reused by seed_main(email=...) calls in tests that mix the `client`
# fixture with storage-level book seeding — same email means the seeded
# books land under the fixture user's id, preserving per-user isolation
# without any handler-level workarounds.
FIXTURE_EMAIL = "fixture@example.com"
FIXTURE_PASSWORD = "fixturepass"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--update-golden`` CLI flag."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite golden JSON fixtures from the current pipeline output.",
    )


@pytest.fixture()
def update_golden(request: pytest.FixtureRequest) -> bool:
    """Expose the ``--update-golden`` flag value to tests."""
    return bool(request.config.getoption("--update-golden"))


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point ``DB_PATH`` at a per-test SQLite file and migrate it.

    Runs as autouse so every test starts with an empty dictionary and a
    fresh connection, regardless of whether the test touches storage
    directly. Closes the connection on teardown so the next test can
    open its own file cleanly.
    """
    from en_reader import storage

    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    storage._reset_for_tests()
    storage.migrate()
    yield
    storage._reset_for_tests()


@pytest.fixture(autouse=True)
def _reset_auth_ratelimit() -> None:
    """Empty the auth rate-limit bucket between tests (M11.3).

    The ``client`` fixture calls ``/auth/signup`` for every test that opts
    in, and the auth flow's sliding-window limiter maxes out at 10
    attempts per IP — so once we cross that threshold further signups
    start returning 429 and the fixture blows up. The buckets are global
    module state on ``auth_ratelimit``, so the cleanest fix is a global
    autouse reset that matches the pattern ``test_auth.py`` already used
    locally.
    """
    from en_reader.auth import auth_ratelimit

    auth_ratelimit._hits.clear()
    yield
    auth_ratelimit._hits.clear()


@pytest.fixture()
def client():
    """Return a :class:`TestClient` with a fresh signed-in fixture user.

    M11.3 put every ``/api/*`` route behind ``Depends(get_current_user)``,
    so tests that hit those routes need a session cookie. This fixture
    hides the signup round-trip behind a single import, and pairs with
    :data:`FIXTURE_EMAIL` for tests that also call ``scripts.seed.main``
    with ``email=FIXTURE_EMAIL`` to attach seeded content to the same
    user id. It's opt-in rather than autouse because a handful of suites
    (auth, SPA fallback) still need the unauthenticated app surface.
    """
    from fastapi.testclient import TestClient

    from en_reader.app import app

    c = TestClient(app)
    resp = c.post(
        "/auth/signup",
        json={"email": FIXTURE_EMAIL, "password": FIXTURE_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return c
