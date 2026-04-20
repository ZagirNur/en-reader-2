"""Fixtures and collection-time skip guard for the Playwright E2E suite.

The rest of the test tree talks to the FastAPI app via :class:`TestClient`,
but the two scenarios covered here (signup → upload → click-to-translate,
and resume) only make sense in a real browser. We run uvicorn in a
subprocess with an isolated SQLite file, flip the ``E2E_MOCK_LLM`` stub
on so :func:`en_reader.translate.translate_one` never touches Gemini,
and let Playwright drive Chromium against the live port.

If Chromium isn't installed on the box (``pip install pytest-playwright``
doesn't pull browsers; that needs ``playwright install``) we skip the
entire directory cleanly at collection time rather than crashing the
suite — the other 333 tests still run to green.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest


# --- collection-time skip guard -------------------------------------------
#
# Playwright resolves browsers from ``PLAYWRIGHT_BROWSERS_PATH`` if set
# (our sandbox uses ``/opt/pw-browsers``) and falls back to
# ``~/.cache/ms-playwright`` otherwise. We probe both so the skip doesn't
# fire just because the environment uses the non-default location.
def _chromium_available() -> bool:
    candidates: list[Path] = []
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".cache" / "ms-playwright")

    for base in candidates:
        if not base.exists():
            continue
        if any(base.glob("chromium-*")) or any(base.glob("chromium_headless_shell-*")):
            return True
    return False


if not _chromium_available():
    pytest.skip(
        "chromium not installed — run `playwright install chromium`",
        allow_module_level=True,
    )


# --- live uvicorn fixture -------------------------------------------------
_HOST = "127.0.0.1"
_PORT = 8765
_BASE_URL = f"http://{_HOST}:{_PORT}"


def _wait_for_ready(url: str, tries: int = 20, delay: float = 0.5) -> bool:
    """Poll ``url`` until it answers 2xx or we run out of attempts."""
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, ConnectionError, socket.timeout):
            pass
        time.sleep(delay)
    return False


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Launch uvicorn in a subprocess for the duration of the session.

    The child process runs against a throwaway SQLite database under
    ``tmp_path_factory``'s session dir, stubs Gemini via ``E2E_MOCK_LLM``,
    and is torn down with a graceful ``terminate()`` followed by a bounded
    ``wait`` so we don't leak a uvicorn between test runs.
    """
    db_path = tmp_path_factory.mktemp("e2e-db") / "e2e.db"

    env = os.environ.copy()
    env["DB_PATH"] = str(db_path)
    env["GEMINI_API_KEY"] = "fake"
    env["E2E_MOCK_LLM"] = "1"
    env["ENV"] = "dev"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "en_reader.app:app",
            "--host",
            _HOST,
            "--port",
            str(_PORT),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if not _wait_for_ready(f"{_BASE_URL}/debug/health"):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            pytest.fail("live uvicorn did not become ready within 10s")
        yield _BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
