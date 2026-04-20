"""Extra per-user isolation coverage (M15.4 gap-fill).

``test_isolation.py`` (M11.3) covers the big-five surfaces:
books list / content / delete, dictionary, current-book pointer.
The cover and inline-image routes weren't included there because
pre-M12 parsers don't populate ``cover_path`` and the bulk of the
seed suite doesn't write images.

For the isolation contract, though, both endpoints matter: a book
that genuinely has a cover (or a stored illustration) must still
404 for a non-owner — same as any other per-book resource. These
tests prime storage directly with a cover file and an image blob
under user A, then confirm user B's cross-user GETs 404.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from en_reader import storage
from en_reader.app import app


def _signup(email: str) -> TestClient:
    """Sign up a fresh user and return their authenticated TestClient."""
    c = TestClient(app)
    r = c.post("/auth/signup", json={"email": email, "password": "longpass1"})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def two_users_with_assets(tmp_path: Path) -> tuple[TestClient, int, str, TestClient]:
    """Spin up users A and B; A owns a book that has a cover + one image.

    Returns ``(client_a, book_id_a, image_id, client_b)``. B owns no
    books — we only need B to act as the cross-user caller.
    """
    client_a = _signup("iso-cover-a@example.com")
    client_b = _signup("iso-cover-b@example.com")

    # Insert a book row under A directly via the DAO (bypasses parser).
    from en_reader.parsers import ParsedBook

    parsed = ParsedBook(
        title="A's Book",
        author="A",
        language="en",
        source_format="txt",
        source_bytes_size=10,
        text="Hello world.",
        images=[],
        cover=None,
    )
    user_a = storage.user_by_email("iso-cover-a@example.com")
    assert user_a is not None
    book_id_a = storage.book_save(parsed, user_id=user_a.id)

    # Stamp a real cover file on disk and point the row at it so the
    # cover route reaches the FileResponse branch for A (and can still
    # 404 for B on the owner-check).
    cover_file = tmp_path / f"{book_id_a}.png"
    cover_file.write_bytes(b"\x89PNG\r\n\x1a\nfake cover bytes")
    conn = storage.get_db()
    with conn:
        conn.execute(
            "UPDATE books SET cover_path = ? WHERE id = ?",
            (str(cover_file), book_id_a),
        )

    # And save one image blob under A's book. image_save is bucketed
    # by ``book_id``, so B reaching it requires bypassing the owner
    # check — which is exactly what we're testing against.
    image_id = "img-isolation-1"
    storage.image_save(book_id_a, image_id, "image/png", b"fakeimgbytes")

    return client_a, book_id_a, image_id, client_b


# ---------- cover endpoint ----------


def test_cover_owner_200_cross_user_404(
    two_users_with_assets: tuple[TestClient, int, str, TestClient],
) -> None:
    """A gets 200 on their own cover; B gets 404 on A's cover id.

    The 200 side proves the setup actually wired a cover path (so the
    404 side isn't a trivial pass against a missing resource). The 404
    side is the isolation assertion — the owner-check must fire before
    the file-exists check, otherwise a non-owner could probe for the
    existence of another user's cover via response timing.
    """
    client_a, book_id_a, _image_id, client_b = two_users_with_assets

    ok = client_a.get(f"/api/books/{book_id_a}/cover")
    assert ok.status_code == 200, ok.text
    # And the body must be the bytes we wrote — sanity check on the
    # FileResponse wiring.
    assert ok.content.startswith(b"\x89PNG")

    nope = client_b.get(f"/api/books/{book_id_a}/cover")
    assert nope.status_code == 404, nope.text


# ---------- image endpoint ----------


def test_image_owner_200_cross_user_404(
    two_users_with_assets: tuple[TestClient, int, str, TestClient],
) -> None:
    """A gets 200 for their own image; B gets 404 for the same id.

    The image blob lives on ``book_images`` keyed by ``(book_id,
    image_id)``, so a non-owner who guesses the right book_id and
    image_id must still be stopped by the ``_ensure_book_owner``
    pre-check, regardless of whether the row exists.
    """
    client_a, book_id_a, image_id, client_b = two_users_with_assets

    ok = client_a.get(f"/api/books/{book_id_a}/images/{image_id}")
    assert ok.status_code == 200, ok.text
    assert ok.content == b"fakeimgbytes"

    nope = client_b.get(f"/api/books/{book_id_a}/images/{image_id}")
    assert nope.status_code == 404, nope.text
