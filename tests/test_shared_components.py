"""M16.2 — static-file assertions for the shared sheet/toast/tabbar
components, plus a light smoke pass to confirm that introducing the new
DOM shells didn't break existing routes.

We can't execute the SPA's JS in CI (same constraint as the rest of the
``test_*_view.py`` family), so these tests pin down the contract pieces
that later milestones will lean on:

* ``index.html`` ships the four canonical shell ids so
  ``openSheet`` / ``showToast`` / ``renderTabBar`` find something to
  populate without having to lazy-mount from scratch on every open.
* ``app.js`` exposes the canonical function names (``openSheet``,
  ``closeSheet``, ``showToast``, ``renderTabBar``, ``hideTabBar``,
  ``showTabBar``), the ``_ICONS`` dictionary, and binds the Escape key
  so later suites can pivot off the same selectors.
* ``style.css`` carries the canonical selectors (``.scrim``,
  ``.sheet .handle``, ``.tabbar``, ``.tab.on``, ``.tab-dot``) — if a
  later refactor drops any of these the visual design breaks silently,
  so fail early.
* ``/login``, ``/`` and ``/books/1`` still return a 200 HTML document
  even though we inserted four new top-level nodes after ``#root``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from scripts.seed import main as seed_main
from tests.conftest import FIXTURE_EMAIL

_FIXTURE = "tests/fixtures/golden/05-complex.txt"


def test_index_html_has_shared_shells(client: TestClient) -> None:
    """index.html must ship the four canonical shell ids."""
    html = client.get("/static/index.html").text
    assert 'id="scrim"' in html
    assert 'id="sheet"' in html
    assert 'id="toast"' in html
    assert 'id="tabbar"' in html


def test_app_js_component_api(client: TestClient) -> None:
    """app.js must expose the canonical component functions + icon set."""
    js = client.get("/static/app.js").text
    for name in (
        "openSheet",
        "closeSheet",
        "showToast",
        "renderTabBar",
        "hideTabBar",
        "showTabBar",
        "_ICONS",
        # Escape-key close lives in a top-level keydown listener.
        "Escape",
    ):
        assert name in js, f"missing {name!r} in app.js"


def test_style_css_shared_component_selectors(client: TestClient) -> None:
    """style.css must carry the canonical selectors for the new shells."""
    css = client.get("/static/style.css").text
    for sel in (".scrim", ".sheet .handle", ".tabbar", ".tab.on", ".tab-dot"):
        assert sel in css, f"missing {sel!r} in style.css"


def test_spa_routes_still_render(client: TestClient) -> None:
    """Adding DOM shells under <body> shouldn't regress SPA routing —
    /login, / and /books/<id> each must return 200 with the index doc."""
    # Seed a book so /books/1 resolves to an owned book for the fixture user.
    seed_main(_FIXTURE, email=FIXTURE_EMAIL)
    for path in ("/login", "/", "/books/1"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        assert 'id="root"' in resp.text, f"{path} missing SPA root"
