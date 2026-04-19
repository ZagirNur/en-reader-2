"""Shared pytest configuration for en-reader tests.

* Registers the ``--update-golden`` flag used by `tests/test_golden.py`
  to rewrite on-disk `.golden.json` fixtures when the pipeline's output
  is intentionally changed.
* Provides an autouse ``tmp_db`` fixture (M6.1) that pins ``DB_PATH`` to
  a fresh per-test SQLite file and runs migrations, so no test leaks
  dictionary state to another. Tests that don't touch storage pay a
  negligible cost — the DB only materializes on first ``get_db()`` call.
"""

from __future__ import annotations

from pathlib import Path

import pytest


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
