"""Tests for /debug/health, /debug/logs, and RingBufferHandler (M14.1)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from en_reader.app import app
from en_reader.logs import get_ring
from tests.conftest import FIXTURE_EMAIL


def test_health_public() -> None:
    """``/debug/health`` is auth-free and returns the documented shape."""
    c = TestClient(app)
    resp = c.get("/debug/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Required top-level keys.
    for key in ("status", "git_sha", "uptime_seconds", "counts", "translate_counters"):
        assert key in body, key

    # Types match the contract.
    assert body["status"] == "ok"
    assert isinstance(body["git_sha"], str)
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0

    counts = body["counts"]
    assert isinstance(counts, dict)
    assert isinstance(counts.get("users"), int)
    assert isinstance(counts.get("books"), int)

    tc = body["translate_counters"]
    assert isinstance(tc, dict)
    assert isinstance(tc.get("hit"), int)
    assert isinstance(tc.get("miss"), int)


def test_logs_require_auth() -> None:
    """Bare (unauthenticated) client hitting /debug/logs must get 401."""
    c = TestClient(app)
    resp = c.get("/debug/logs")
    assert resp.status_code == 401, resp.text


def test_logs_non_admin_403(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Authed user whose email != ADMIN_EMAIL gets a 403."""
    # Deliberately set ADMIN_EMAIL to something other than FIXTURE_EMAIL
    # so the non-admin branch exercises cleanly.
    monkeypatch.setenv("ADMIN_EMAIL", "someone-else@example.com")
    resp = client.get("/debug/logs")
    assert resp.status_code == 403, resp.text


def test_logs_admin_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin user sees text/plain body containing recent log lines."""
    # Seed the ring with a recognizable line so the tail is non-empty.
    logging.getLogger("en_reader").info("test_logs_admin_200 probe line")

    monkeypatch.setenv("ADMIN_EMAIL", FIXTURE_EMAIL)
    resp = client.get("/debug/logs?n=50")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    assert "test_logs_admin_200 probe line" in resp.text


def test_ring_buffer_size() -> None:
    """Emitting 1100 records leaves exactly 1000 in the buffer (maxlen eviction)."""
    ring = get_ring()
    ring.buffer.clear()
    logger = logging.getLogger("en_reader.test_ring")
    for i in range(1100):
        logger.info("ring-size probe %d", i)
    assert len(ring.buffer) == 1000


def test_health_counts_after_signup(client: TestClient) -> None:
    """``counts.users`` reflects the freshly signed-up fixture user."""
    # ``client`` fixture has already signed up FIXTURE_EMAIL.
    resp = client.get("/debug/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At least one real user exists; the seed row pushes the count
    # higher, but the important invariant is "non-zero after signup".
    assert body["counts"]["users"] >= 1
