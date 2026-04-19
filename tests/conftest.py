"""Shared pytest configuration for en-reader tests.

Adds the ``--update-golden`` flag used by `tests/test_golden.py` to rewrite
on-disk `.golden.json` fixtures when the pipeline's output is intentionally
changed.
"""

from __future__ import annotations

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
