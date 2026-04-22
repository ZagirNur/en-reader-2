"""Regression guard for the OpenAPI contract (M21).

Native / extension clients are generated from ``docs/openapi.json``
and pinned to specific fields; a breaking change there would silently
wreck a shipped mobile app on the next backend deploy. These tests pin
the critical surface:

* A hand-picked list of paths that MUST exist.
* The translate endpoints' response schema includes every field a v1
  client relies on.
* The bearer-token endpoint's request and response shapes don't
  silently drop ``refresh_token`` / ``access_token``.

The on-disk ``docs/openapi.json`` snapshot is NOT asserted byte-for-
byte — additive changes (new paths, new optional fields) are allowed
by design. Regeneration instructions live in :mod:`scripts/dump_openapi`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from en_reader.app import app


REQUIRED_PATHS = {
    # Auth surface
    "/auth/signup",
    "/auth/login",
    "/auth/logout",
    "/auth/me",
    "/auth/telegram",
    "/auth/token",
    "/auth/token/refresh",
    "/auth/token/revoke",
    # Book/reader surface
    "/api/books",
    "/api/books/upload",
    "/api/books/{book_id}",
    "/api/books/{book_id}/content",
    "/api/books/{book_id}/progress",
    "/api/books/{book_id}/cover",
    # Translate surface
    "/api/translate",
    "/api/translate/batch",
    # Dictionary surface
    "/api/dictionary",
    "/api/dictionary/sync",
    "/api/dictionary/words",
    "/api/dictionary/stats",
    "/api/dictionary/training",
    "/api/dictionary/training/result",
    "/api/dictionary/{lemma}",
    "/api/dictionary/{lemma}/card",
    # Catalog
    "/api/catalog",
    "/api/catalog/{catalog_id}/import",
}


def _openapi() -> dict:
    return TestClient(app).get("/openapi.json").json()


def test_openapi_endpoint_serves() -> None:
    spec = _openapi()
    assert spec["info"]["title"] == "en-reader"
    assert spec["openapi"].startswith("3.")


def test_every_required_path_present() -> None:
    spec = _openapi()
    missing = REQUIRED_PATHS - set(spec["paths"].keys())
    assert not missing, f"OpenAPI missing required paths: {sorted(missing)}"


def test_translate_response_schema_is_complete() -> None:
    """``TranslateResponse`` keeps every field M19.4 + M20.3 added."""
    spec = _openapi()
    schemas = spec["components"]["schemas"]
    tr = schemas["TranslateResponse"]
    props = set(tr["properties"].keys())
    required_fields = {"ru", "source", "text", "is_simplest", "mode"}
    assert required_fields <= props, f"TranslateResponse drops: {required_fields - props}"


def test_token_response_schema_is_complete() -> None:
    spec = _openapi()
    schemas = spec["components"]["schemas"]
    tok = schemas["TokenResponse"]
    props = set(tok["properties"].keys())
    assert {"access_token", "refresh_token", "token_type", "access_expires_at", "refresh_expires_at"} <= props


def test_v1_alias_is_noop_for_openapi() -> None:
    """The /api/v1 alias is implemented as a request-path rewrite so it
    does NOT appear in /openapi.json. That's a feature — clients point
    at /api/v1/… for versioning guarantees, but the spec stays flat and
    doesn't double every path. Pin the behaviour here so a future
    refactor that registers duplicate routes gets caught.
    """
    spec = _openapi()
    v1_paths = [p for p in spec["paths"] if p.startswith("/api/v1/")]
    assert v1_paths == [], f"OpenAPI should not expose /api/v1/* paths: {v1_paths}"


def test_translate_batch_rejects_over_50_items() -> None:
    """Schema pin: the 50-item cap lives in TranslateBatchRequest.items."""
    spec = _openapi()
    schemas = spec["components"]["schemas"]
    br = schemas["TranslateBatchRequest"]
    items = br["properties"]["items"]
    assert items.get("maxItems") == 50
