"""Tests for M7.1 inline-image storage, endpoint, and seed integration.

The ``tmp_db`` autouse fixture in ``conftest.py`` already gives every test a
fresh migrated SQLite file, which is all the storage bits here need. The
shared ``client`` fixture (M11.3) builds an authenticated ``TestClient``
so the HTTP endpoint tests can reach ``/api/books/{id}/images/{id}`` past
the new per-user guard. Image ownership is enforced by the owning book,
so we seed a real book via ``seed_main(..., email=FIXTURE_EMAIL)`` and
then attach the test image to that book id.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from en_reader import images, storage
from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

# 1x1 transparent PNG, checked in as tests/fixtures/demo-images/star.png.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="
)

_FIXTURE_TXT = "tests/fixtures/golden/05-complex.txt"


@pytest.fixture()
def owned_book_id() -> int:
    """Seed a minimal book owned by the fixture user and return its id.

    Needed because M11.3 made ``/api/books/{id}/images/{id}`` run an
    ownership check first — a naked ``image_save(1, ...)`` into a
    bookless DB would now 404 at the book-owner guard before the image
    lookup even runs.
    """
    return seed_main(_FIXTURE_TXT, email=FIXTURE_EMAIL)


# ---------- images module ----------


def test_new_image_id_format() -> None:
    image_id = images.new_image_id()
    assert len(image_id) == 12
    assert re.fullmatch(r"[0-9a-f]{12}", image_id)
    assert images.IMAGE_MARKER_RE.fullmatch(images.marker_for(image_id))


# ---------- storage DAO ----------


def test_image_save_and_get() -> None:
    image_id = images.new_image_id()
    storage.image_save(1, image_id, "image/png", _TINY_PNG)
    result = storage.image_get(1, image_id)
    assert result is not None
    mime, data = result
    assert mime == "image/png"
    assert data == _TINY_PNG


def test_image_missing_returns_none() -> None:
    assert storage.image_get(1, "deadbeefdead") is None


# ---------- HTTP endpoint ----------


def test_image_endpoint_200(client: TestClient, owned_book_id: int) -> None:
    image_id = images.new_image_id()
    storage.image_save(owned_book_id, image_id, "image/png", _TINY_PNG)

    resp = client.get(f"/api/books/{owned_book_id}/images/{image_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert "immutable" in resp.headers["cache-control"]
    assert "max-age=31536000" in resp.headers["cache-control"]
    assert resp.content == _TINY_PNG


def test_image_endpoint_404(client: TestClient, owned_book_id: int) -> None:
    resp = client.get(f"/api/books/{owned_book_id}/images/deadbeefdead")
    assert resp.status_code == 404


def test_image_endpoint_wrong_book(client: TestClient, owned_book_id: int) -> None:
    image_id = images.new_image_id()
    storage.image_save(owned_book_id, image_id, "image/png", _TINY_PNG)
    # Book id that doesn't exist at all — ownership check 404s first.
    resp = client.get(f"/api/books/{owned_book_id + 999}/images/{image_id}")
    assert resp.status_code == 404


# ---------- seed pipeline ----------


def test_seed_injects_images_and_positions(client: TestClient, tmp_path: Path) -> None:
    images_dir = tmp_path / "imgs"
    images_dir.mkdir()
    (images_dir / "pic.png").write_bytes(_TINY_PNG)

    book_id = seed_main(_FIXTURE_TXT, images_dir=images_dir, email=FIXTURE_EMAIL)
    assert book_id >= 1

    resp = client.get(f"/api/books/{book_id}/content?offset=0&limit=20")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("book_id") == book_id
    pages = body["pages"]
    assert len(pages) > 0

    total_images = 0
    for page in pages:
        page_imgs = page.get("images", [])
        marker_hits = images.IMAGE_MARKER_RE.findall(page["text"])
        assert len(marker_hits) == len(page_imgs), (
            f"page {page['page_index']}: {len(marker_hits)} markers vs "
            f"{len(page_imgs)} image records"
        )
        for img in page_imgs:
            assert page["text"][img["position"] : img["position"] + 3] == "IMG"
        total_images += len(page_imgs)
    assert total_images >= 1
