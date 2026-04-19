// en-reader SPA (M3.3 + M4.2): state + router + reader render + inline translation.
// XSS discipline: any text from API responses goes via document.createTextNode / textContent only.

// --- state ---
const state = {
  view: "loading",
  error: null,
  route: "/",
  currentBook: null,
  userDict: {},
  // Library listing: undefined = not fetched, [] = fetched-and-empty, array = loaded.
  books: undefined,
  // Scroll-restore (M10.2). `targetPageIndex` and `targetOffset` are sourced
  // from the server's /content response (`last_page_index` + `last_page_offset`)
  // and drive the initial render + `restoreScroll()` pass. `restoring` stays
  // true for the 2-second restore window so later milestones (M10.4) can skip
  // progress saves while we're still nudging scrollTop into place.
  targetPageIndex: 0,
  targetOffset: 0,
  restoring: false,
};

// Reader scroll state (M9.3). Kept at module scope so we can detach the
// listener when leaving the reader view without leaking a closure per render.
let _readerScrollHandler = null;
let _readerLastScrollY = 0;
let _readerScrollRafId = 0;
// Scroll-restore ResizeObserver (M10.2). Kept at module scope so a mid-flight
// navigation can disconnect it from `teardownReaderScroll()` instead of
// waiting for the 2 s timeout to fire on a dead DOM.
let _restoreRO = null;
let _restoreTimeoutId = 0;
// Lazy-neighbor sentinel observers (M10.3). Two IntersectionObservers watch
// invisible 1-px sentinels flanking the rendered `.page` sections; when the
// user scrolls within 400 px of a boundary we fetch the adjacent page and
// splice it into the DOM. `_loadingTop` / `_loadingBottom` are in-flight
// re-entrancy guards so overlapping scroll ticks don't double-fetch.
let _topObs = null;
let _bottomObs = null;
let _loadingTop = false;
let _loadingBottom = false;
// Debounced progress save (M10.4). `_saveTimer` is the pending setTimeout
// handle (null when nothing is scheduled). `_lastSaved` remembers what we
// actually POSTed so we can skip trivially-close re-saves. The
// `_beforeUnloadHandler` reference is held here so `teardownReaderScroll`
// can detach it — otherwise we'd leak a handler per reader mount.
let _saveTimer = null;
let _lastSaved = { pageIndex: null, offset: null };
let _beforeUnloadHandler = null;

function setState(patch) {
  const prevView = state.view;
  Object.assign(state, patch);
  // Leaving the reader view? Tear down the scroll listener set up by
  // renderReader so we don't keep reacting to scrolls on the library. We
  // also abandon any in-flight restore: we only reset `state.restoring`
  // here (not inside teardownReaderScroll) so a same-view re-render that
  // calls teardown defensively doesn't clobber the freshly-set flag.
  if (prevView === "reader" && state.view !== "reader") {
    teardownReaderScroll();
    state.restoring = false;
  }
  render();
}

function teardownReaderScroll() {
  if (_readerScrollHandler) {
    window.removeEventListener("scroll", _readerScrollHandler);
    _readerScrollHandler = null;
  }
  if (_readerScrollRafId) {
    cancelAnimationFrame(_readerScrollRafId);
    _readerScrollRafId = 0;
  }
  _readerLastScrollY = 0;
  // M10.2: drop any in-flight restore observer / timer so they don't fire
  // against a reader DOM that's already been replaced. The restoring
  // flag itself stays — setState's view-transition branch resets it on
  // actual navigation, and restoreScroll() flips it off after the 2 s
  // window. This lets a same-view re-render tear down stale observers
  // without cancelling the pending restore intent.
  if (_restoreRO) {
    _restoreRO.disconnect();
    _restoreRO = null;
  }
  if (_restoreTimeoutId) {
    clearTimeout(_restoreTimeoutId);
    _restoreTimeoutId = 0;
  }
  // M10.3: also drop the lazy-neighbor sentinel observers and clear their
  // in-flight guards so a re-render from scratch starts clean. The
  // observers are re-created in `renderReader()` once the new DOM exists.
  if (_topObs) {
    _topObs.disconnect();
    _topObs = null;
  }
  if (_bottomObs) {
    _bottomObs.disconnect();
    _bottomObs = null;
  }
  _loadingTop = false;
  _loadingBottom = false;
  // M10.4: drop the debounced progress-save timer and detach the
  // beforeunload handler so a library view doesn't keep pinging
  // /progress on tab close. We do NOT reset `_lastSaved` here — it's
  // keyed implicitly by the currently-loaded book and gets reset on
  // book change inside `renderReader`'s loader branch.
  if (_saveTimer) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
  }
  if (_beforeUnloadHandler) {
    window.removeEventListener("beforeunload", _beforeUnloadHandler);
    _beforeUnloadHandler = null;
  }
}

// --- router ---
const BOOK_ROUTE_RE = /^\/books\/(\d+)$/;

function parseRoute(path) {
  if (path === "/") return { view: "library" };
  // Legacy back-compat: /reader → first seeded book.
  if (path === "/reader") return { view: "reader", bookId: 1 };
  const m = BOOK_ROUTE_RE.exec(path);
  if (m) return { view: "reader", bookId: Number(m[1]) };
  return { view: "error" };
}

function navigate(path) {
  history.pushState({}, "", path);
  const parsed = parseRoute(path);
  const patch = { route: path, view: parsed.view };
  if (parsed.view === "error") patch.error = `Unknown route: ${path}`;
  // A navigation to a different book should drop any previously-loaded content.
  if (parsed.view === "reader") {
    const prev = state.currentBook;
    if (!prev || prev.bookId !== parsed.bookId) patch.currentBook = null;
  }
  // Leaving the library? Forget the cached listing so a later visit refetches.
  if (state.view === "library" && parsed.view !== "library") {
    patch.books = undefined;
  }
  setState(patch);
}

function onPopState() {
  const path = location.pathname;
  const parsed = parseRoute(path);
  const patch = { route: path, view: parsed.view };
  if (parsed.view === "error") patch.error = `Unknown route: ${path}`;
  if (parsed.view === "reader") {
    const prev = state.currentBook;
    if (!prev || prev.bookId !== parsed.bookId) patch.currentBook = null;
  }
  if (state.view === "library" && parsed.view !== "library") {
    patch.books = undefined;
  }
  setState(patch);
}

// --- api ---
async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiDelete(path) {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
}

// Fetch a slice of a book's pages via the M8.2 content API. `limit` is capped
// server-side at 20 regardless of what we ask for.
async function loadBookContent(bookId, offset = 0, limit = 1) {
  return apiGet(
    `/api/books/${encodeURIComponent(bookId)}/content` +
      `?offset=${offset}&limit=${limit}`,
  );
}

// --- views ---
// Long-tap timer for `.card` touch interactions on mobile. Kept at module
// scope so `touchmove`/`touchend` listeners can cancel the pending timeout.
let _longTapTimer = null;
let _longTapCard = null;
// Set when the long-tap timer fires, to swallow the synthetic click that
// touchend produces. Cleared by the grid click handler after one swallow.
let _longTapFired = false;

function closeCardMenu() {
  document.querySelectorAll(".card-menu").forEach((n) => n.remove());
  document.removeEventListener("click", _onDocClickCloseMenu, true);
}

function _onDocClickCloseMenu(e) {
  // Clicks inside the menu itself are handled by the menu's own listeners —
  // we still want the menu to stay open while the user hovers the button.
  if (e.target && e.target.closest && e.target.closest(".card-menu")) return;
  closeCardMenu();
}

function showCardMenu(cardEl, bookId) {
  closeCardMenu();
  const menu = document.createElement("div");
  menu.className = "card-menu";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "Удалить";
  btn.addEventListener("click", async () => {
    closeCardMenu();
    if (!confirm("Удалить книгу?")) return;
    try {
      await apiDelete(`/api/books/${encodeURIComponent(bookId)}`);
    } catch (err) {
      toast("Не удалось удалить");
      return;
    }
    const books = Array.isArray(state.books)
      ? state.books.filter((b) => b.id !== bookId)
      : state.books;
    setState({ books });
  });
  menu.appendChild(btn);

  // Position relative to the card: attach to the card itself (which is
  // position: relative) and pin to the top-right corner.
  menu.style.top = "6px";
  menu.style.right = "6px";
  cardEl.appendChild(menu);

  // Close on any outside click. Capture phase so it fires before the click
  // bubbles to any other delegated listeners.
  setTimeout(() => {
    document.addEventListener("click", _onDocClickCloseMenu, true);
  }, 0);
}

function renderLibrary() {
  const root = document.getElementById("root");

  // Kick off the fetch on first entry. `state.books === undefined` means
  // "never fetched"; an explicit [] is a valid loaded-and-empty state.
  if (state.books === undefined) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    apiGet("/api/books")
      .then((data) => {
        if (state.view !== "library") return;
        setState({ books: Array.isArray(data) ? data : [] });
      })
      .catch((err) => setState({ view: "error", error: err.message }));
    return;
  }

  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "library";

  const header = document.createElement("header");
  header.className = "library-header";
  const h1 = document.createElement("h1");
  h1.textContent = "Моя полка";
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "E";
  header.appendChild(h1);
  header.appendChild(avatar);
  main.appendChild(header);

  const grid = document.createElement("div");
  grid.className = "grid";

  const books = state.books;
  const isEmpty = !books || books.length === 0;
  if (isEmpty) {
    main.classList.add("library-empty");
  }

  if (!isEmpty) {
    for (const b of books) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "card";
      card.dataset.bookId = String(b.id);

      const cover = document.createElement("div");
      cover.className = "cover-placeholder";
      cover.textContent = "📖";
      card.appendChild(cover);

      const meta = document.createElement("div");
      meta.className = "meta";
      const title = document.createElement("div");
      title.className = "title";
      title.textContent = b.title || "";
      const author = document.createElement("div");
      author.className = "author";
      author.textContent = b.author || "";
      meta.appendChild(title);
      meta.appendChild(author);
      card.appendChild(meta);

      grid.appendChild(card);
    }
  }

  const addCard = document.createElement("button");
  addCard.type = "button";
  addCard.className = "add-card";
  addCard.innerHTML = ""; // reset (we use DOM below)
  addCard.appendChild(document.createTextNode("+"));
  addCard.appendChild(document.createElement("br"));
  addCard.appendChild(document.createTextNode("Добавить книгу"));
  grid.appendChild(addCard);

  main.appendChild(grid);
  root.appendChild(main);

  // --- delegated listeners on `.grid` ---
  grid.addEventListener("click", (e) => {
    // If a long-tap just opened the menu, swallow the synthetic click so we
    // don't navigate away from the card the user intended to delete.
    if (_longTapFired) {
      _longTapFired = false;
      e.preventDefault();
      return;
    }
    // If a click happens on the menu itself, don't trigger card navigation.
    if (e.target && e.target.closest && e.target.closest(".card-menu")) return;
    const add = e.target.closest(".add-card");
    if (add) {
      toast("Upload — скоро (M12.4)");
      return;
    }
    const card = e.target.closest(".card[data-book-id]");
    if (card) {
      const id = Number(card.dataset.bookId);
      navigate(`/books/${id}`);
    }
  });

  grid.addEventListener("contextmenu", (e) => {
    const card = e.target.closest(".card[data-book-id]");
    if (!card) return;
    e.preventDefault();
    const id = Number(card.dataset.bookId);
    showCardMenu(card, id);
  });

  // --- mobile long-tap (≥ 500 ms) ---
  grid.addEventListener("touchstart", (e) => {
    const card = e.target.closest(".card[data-book-id]");
    if (!card) return;
    _longTapCard = card;
    _longTapFired = false;
    clearTimeout(_longTapTimer);
    _longTapTimer = setTimeout(() => {
      if (!_longTapCard) return;
      const id = Number(_longTapCard.dataset.bookId);
      showCardMenu(_longTapCard, id);
      _longTapFired = true;
      _longTapCard = null;
      _longTapTimer = null;
    }, 500);
  }, { passive: true });

  const cancelLongTap = () => {
    clearTimeout(_longTapTimer);
    _longTapTimer = null;
    _longTapCard = null;
  };
  grid.addEventListener("touchmove", cancelLongTap, { passive: true });
  grid.addEventListener("touchend", cancelLongTap, { passive: true });
  grid.addEventListener("touchcancel", cancelLongTap, { passive: true });
}

// --- reader render ---
const IMAGE_MARKER_RE_JS = /IMG[0-9a-f]{12}/g;
const IMAGE_MARKER_LEN = 15; // "IMG" + 12 hex chars

function buildPageSection(page) {
  const section = document.createElement("section");
  section.className = "page";
  section.dataset.pageIndex = String(page.page_index);

  const label = document.createElement("div");
  label.className = "uplabel";
  label.textContent = `Стр. ${page.page_index + 1}`;
  section.appendChild(label);

  const body = document.createElement("div");
  body.className = "page-body";
  section.appendChild(body);

  const tokens = page.tokens || [];
  const units = page.units || [];
  const text = page.text || "";
  const pageImages = (page.images || []).slice().sort((a, b) => a.position - b.position);
  const bookId = (state.currentBook && state.currentBook.bookId != null) ? state.currentBook.bookId : 1;

  // token local index → unit object
  const unitByToken = new Map();
  for (const unit of units) {
    for (const tid of unit.token_ids) unitByToken.set(tid, unit);
  }

  // Set of positions where a marker starts, for token-skip decisions.
  const imagePositions = new Set(pageImages.map((img) => img.position));

  let para = document.createElement("p");
  body.appendChild(para);

  // Sentence wrapper: opened when is_sent_start (or on first token).
  let sent = null;
  let sentCounter = 0;

  const openSentence = () => {
    sent = document.createElement("span");
    sent.className = "sentence";
    sent.dataset.sentenceId = `page-${page.page_index}-sent-${sentCounter++}`;
    para.appendChild(sent);
  };

  let imgCursor = 0;

  const insertImage = (img) => {
    const el = document.createElement("img");
    el.className = "inline-image";
    el.src = `/api/books/${bookId}/images/${encodeURIComponent(img.image_id)}`;
    el.alt = "";
    // Images break the paragraph flow — append directly to <body> so the
    // surrounding <p>s keep their margins.
    body.appendChild(el);
    // Start a fresh paragraph for the text that follows the image.
    para = document.createElement("p");
    body.appendChild(para);
    sent = null;
  };

  // Flush any images whose position falls inside [from, to).
  const flushImagesUpTo = (to) => {
    while (imgCursor < pageImages.length && pageImages[imgCursor].position < to) {
      insertImage(pageImages[imgCursor]);
      imgCursor += 1;
    }
  };

  // Emit literal gap text, splitting on blank-line runs and image markers.
  // `gapStart` is the char offset of `gap` inside `text`.
  const appendGap = (gap, gapStart) => {
    if (!gap) return;
    // First, check for image markers inside this gap and split around them.
    // Markers are always flanked by \n\n in the seed pipeline, so splitting
    // naturally bubbles them into their own segments; but we scan for
    // position-based hits to be safe.
    let cursor = 0;
    while (cursor < gap.length) {
      const absStart = gapStart + cursor;
      // Find the next marker position (if any) inside the remaining gap.
      let nextMarkerRel = -1;
      while (imgCursor < pageImages.length) {
        const p = pageImages[imgCursor].position;
        if (p < absStart) { imgCursor += 1; continue; }
        if (p >= gapStart + gap.length) break;
        nextMarkerRel = p - gapStart;
        break;
      }
      const chunkEnd = nextMarkerRel >= 0 ? nextMarkerRel : gap.length;
      const chunk = gap.slice(cursor, chunkEnd);
      if (chunk) appendTextChunk(chunk);
      if (nextMarkerRel >= 0) {
        insertImage(pageImages[imgCursor]);
        imgCursor += 1;
        cursor = nextMarkerRel + IMAGE_MARKER_LEN;
      } else {
        cursor = gap.length;
      }
    }
  };

  // Append plain gap text (no image markers), handling \n\n paragraph splits.
  const appendTextChunk = (chunk) => {
    // Defensive: strip any stray markers that slipped through (shouldn't
    // happen with correct positions, but keeps the DOM clean).
    chunk = chunk.replace(IMAGE_MARKER_RE_JS, "");
    if (!chunk) return;
    const parts = chunk.split(/\n\n+/);
    for (let k = 0; k < parts.length; k++) {
      if (parts[k]) {
        const target = sent || para;
        target.appendChild(document.createTextNode(parts[k]));
      }
      if (k < parts.length - 1) {
        para = document.createElement("p");
        body.appendChild(para);
        if (sent) {
          sent = document.createElement("span");
          sent.className = "sentence";
          sent.dataset.sentenceId = `page-${page.page_index}-sent-${sentCounter - 1}-cont`;
          para.appendChild(sent);
        }
      }
    }
  };

  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];

    // Skip tokens that coincide with an image marker position — those are
    // the spaCy-produced "IMG<hex>" tokens. They must not render as text or
    // as .word spans. The associated image is emitted when we hit the
    // marker's position via the surrounding gap logic.
    if (imagePositions.has(tok.idx_in_text) && /^IMG[0-9a-f]{12}$/.test(tok.text)) {
      // Flush the image in-place in case no gap preceded it.
      flushImagesUpTo(tok.idx_in_text + IMAGE_MARKER_LEN);
      const nextTok = tokens[i + 1];
      const gapStart = tok.idx_in_text + tok.text.length;
      const gap = nextTok
        ? text.slice(gapStart, nextTok.idx_in_text)
        : text.slice(gapStart);
      appendGap(gap, gapStart);
      i += 1;
      continue;
    }

    const unit = unitByToken.get(i);

    // Open a new sentence wrapper at the sentence boundary.
    if (tok.is_sent_start || sent === null) {
      openSentence();
    }

    if (unit && unit.token_ids[0] === i) {
      // MWE / phrasal / split_phrasal / word unit: one span per unit.
      const span = document.createElement("span");
      span.className = "word";
      span.dataset.unitId = String(unit.id);
      span.dataset.lemma = unit.lemma;
      span.dataset.kind = unit.kind;
      if (unit.pair_id != null) span.dataset.pairId = String(unit.pair_id);

      const ids = unit.token_ids;
      let spanText = "";
      for (let j = 0; j < ids.length; j++) {
        const tj = tokens[ids[j]];
        spanText += tj.text;
        if (j < ids.length - 1) {
          const nextTj = tokens[ids[j + 1]];
          spanText += text.slice(tj.idx_in_text + tj.text.length, nextTj.idx_in_text);
        }
      }
      span.textContent = spanText;
      sent.appendChild(span);

      const lastId = ids[ids.length - 1];
      const lastTok = tokens[lastId];
      const nextTok = tokens[lastId + 1];
      const gapStart = lastTok.idx_in_text + lastTok.text.length;
      const gap = nextTok
        ? text.slice(gapStart, nextTok.idx_in_text)
        : text.slice(gapStart);
      appendGap(gap, gapStart);
      i = lastId + 1;
      continue;
    }

    if (!unit && tok.translatable) {
      const span = document.createElement("span");
      span.className = "word";
      span.dataset.lemma = tok.lemma;
      span.dataset.kind = "word";
      span.textContent = tok.text;
      sent.appendChild(span);
    } else if (!unit) {
      sent.appendChild(document.createTextNode(tok.text));
    }
    // else: token inside a multi-token unit — already emitted.

    const nextTok = tokens[i + 1];
    const gapStart = tok.idx_in_text + tok.text.length;
    const gap = nextTok
      ? text.slice(gapStart, nextTok.idx_in_text)
      : text.slice(gapStart);
    appendGap(gap, gapStart);
    i += 1;
  }

  // Any trailing images past the last token's end position.
  flushImagesUpTo(text.length + 1);

  return section;
}

function applyAutoTranslation(pageSection, unitId, ru) {
  const escaped = CSS.escape(String(unitId));
  pageSection.querySelectorAll(`.word[data-unit-id="${escaped}"]`).forEach((span) => {
    replaceWithTranslation(span, ru);
  });
}

// Find the page `<section class="page">` whose intersection with the
// viewport is greatest and return it. Returns null when no .page sections
// exist (or none intersect). M10.4 reuses this for progress-save so we
// align on a single "visible page" definition across the reader.
function findVisiblePageSection() {
  const pages = document.querySelectorAll("section.page");
  if (!pages.length) return null;
  const vh = window.innerHeight || 0;
  let best = null;
  let bestIntersect = 0;
  for (const p of pages) {
    const r = p.getBoundingClientRect();
    const top = Math.max(r.top, 0);
    const bot = Math.min(r.bottom, vh);
    const intersect = Math.max(0, bot - top);
    if (intersect > bestIntersect) {
      bestIntersect = intersect;
      best = p;
    }
  }
  return best;
}

// Returns the visible page's `data-page-index` as a Number (0 when none).
// M10.4 delegates to findVisiblePageSection so the progress-bar and
// progress-save agree on a single "visible page" definition.
function findVisiblePageIndex() {
  const section = findVisiblePageSection();
  if (!section) return 0;
  const n = Number(section.dataset.pageIndex);
  return Number.isFinite(n) ? n : 0;
}

// M10.4: compute how far the given `.page` section has scrolled past the
// top of the viewport, as a fraction of its own height, clamped to [0, 1].
// `r.top < 0` means the section is partially above the viewport; `-r.top`
// is the number of pixels scrolled past. Zero-height sections collapse to 0.
function computeOffset(section) {
  const r = section.getBoundingClientRect();
  if (r.height <= 0) return 0;
  const offset = -r.top / r.height;
  return Math.max(0, Math.min(1, offset));
}

// M10.4: debounced progress save with a stale-save guard. Called once per
// rAF tick from the reader scroll handler. We ALWAYS clear any pending
// `_saveTimer` before any early-return — otherwise a fast 10 → 8 scroll
// could return early at 8 while the 10-timer survives and lands a stale
// POST. Bails entirely while `state.restoring` is true (M10.2) so the
// programmatic scrollTo's don't overwrite the target we're restoring to.
function scheduleProgressSave() {
  if (state.restoring) return;
  const cb = state.currentBook;
  if (!cb || cb.bookId == null) return;

  const section = findVisiblePageSection();
  if (!section) return;
  const pageIndex = Number(section.dataset.pageIndex);
  if (!Number.isFinite(pageIndex)) return;
  const offset = computeOffset(section);

  // Clear BEFORE any no-op return so a stale pending timer can't land.
  if (_saveTimer) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
  }

  // No meaningful change since last successful POST — skip, with the
  // timer already cleared so the previous pending save (if any) is gone.
  if (
    _lastSaved.pageIndex === pageIndex &&
    _lastSaved.offset != null &&
    Math.abs(_lastSaved.offset - offset) < 0.02
  ) {
    return;
  }

  const bookId = cb.bookId;
  _saveTimer = setTimeout(async () => {
    try {
      await apiPost(`/api/books/${bookId}/progress`, {
        last_page_index: pageIndex,
        last_page_offset: offset,
      });
      _lastSaved = { pageIndex, offset };
    } catch (_e) {
      // Silent: user shouldn't see transient progress-save errors.
    }
    _saveTimer = null;
  }, 1500);
}

// --- scroll restore (M10.2) ---
// Scroll the window so the given page `section` is aligned such that
// `section.height * offset` pixels have passed its top. Reads layout
// synchronously (getBoundingClientRect + offsetHeight) because callers
// have already awaited the relevant readiness signal.
function scrollToOffset(section, offset) {
  if (!section) return;
  const rect = section.getBoundingClientRect();
  const currentTop = rect.top + window.scrollY;
  window.scrollTo(0, currentTop + section.offsetHeight * offset);
}

// Restore the reader's scroll position to `state.targetPageIndex` +
// `state.targetOffset`. Runs a sequence of scrollTo passes gated on the
// browser signals that can still change a page section's height after
// first paint: fonts ready, images loaded, and any remaining layout
// resizes. After a 2 s window we disconnect the ResizeObserver and clear
// `state.restoring`, so subsequent user scrolls are treated as genuine.
async function restoreScroll() {
  const targetIdx = state.targetPageIndex;
  const section = document.querySelector(
    `.page[data-page-index="${CSS.escape(String(targetIdx))}"]`,
  );
  if (!section) {
    state.restoring = false;
    return;
  }

  // Pass 1 — synchronous, before any awaits.
  scrollToOffset(section, state.targetOffset);

  // Pass 2 — after fonts finish loading (Georgia is system, but a custom
  // @font-face elsewhere could still shift metrics).
  if (document.fonts && document.fonts.ready) {
    try {
      await document.fonts.ready;
    } catch (_) {
      /* ignore */
    }
    if (state.view !== "reader") return;
    scrollToOffset(section, state.targetOffset);
  }

  // Pass 3 — after every <img> in the target section has resolved.
  const imgs = section.querySelectorAll("img");
  const imgPromises = Array.from(imgs).map((img) => {
    if (img.complete) return Promise.resolve();
    return new Promise((res) => {
      img.addEventListener("load", res, { once: true });
      img.addEventListener("error", res, { once: true });
    });
  });
  if (imgPromises.length) {
    await Promise.all(imgPromises);
    if (state.view !== "reader") return;
    scrollToOffset(section, state.targetOffset);
  }

  // Pass 4 — watch for further height shifts (lazy reflow, late layout)
  // for a 2 s window. Any ResizeObserver tick re-runs scrollToOffset with
  // the same offset so the user sees a single stable final position.
  if (_restoreRO) {
    _restoreRO.disconnect();
    _restoreRO = null;
  }
  if (typeof ResizeObserver !== "undefined") {
    _restoreRO = new ResizeObserver(() =>
      scrollToOffset(section, state.targetOffset),
    );
    _restoreRO.observe(section);
  }
  if (_restoreTimeoutId) {
    clearTimeout(_restoreTimeoutId);
    _restoreTimeoutId = 0;
  }
  _restoreTimeoutId = setTimeout(() => {
    if (_restoreRO) {
      _restoreRO.disconnect();
      _restoreRO = null;
    }
    _restoreTimeoutId = 0;
    state.restoring = false;
  }, 2000);
}

function renderReader() {
  const root = document.getElementById("root");
  if (state.currentBook === null) {
    // Derive bookId from the current route (default 1 for legacy /reader).
    const parsed = parseRoute(state.route);
    const bookId = parsed.bookId != null ? parsed.bookId : 1;
    root.innerHTML = `<div class="loader">Loading…</div>`;
    // M10.2 two-step open:
    //   1. Fetch page 0 with limit=1 — cheap probe that also returns the
    //      server-side `last_page_index` / `last_page_offset` / `total_pages`.
    //   2. If `last_page_index > 0`, fetch that target page with limit=1.
    //      Otherwise reuse meta.pages[0] as the target (no second RTT).
    // Rationale: the /content API clamps `limit` to [1, 20] (no 0 allowed),
    // so we can't ask for "just metadata". A single-page fetch is the
    // minimum viable probe, and when the user was on page 0 we avoid the
    // second call entirely.
    // A /api/books metadata lookup runs in parallel (book title for header).
    Promise.all([
      loadBookContent(bookId, 0, 1),
      apiGet("/api/books").catch(() => null),
    ])
      .then(async ([meta, books]) => {
        if (state.view !== "reader") return null;
        const lastIdx = Number.isFinite(meta.last_page_index)
          ? meta.last_page_index
          : 0;
        const lastOff = Number.isFinite(meta.last_page_offset)
          ? meta.last_page_offset
          : 0;
        let targetPage;
        if (lastIdx > 0) {
          const second = await loadBookContent(bookId, lastIdx, 1);
          if (state.view !== "reader") return null;
          targetPage =
            Array.isArray(second.pages) && second.pages.length
              ? second.pages[0]
              : null;
        } else {
          targetPage =
            Array.isArray(meta.pages) && meta.pages.length
              ? meta.pages[0]
              : null;
        }
        // Seed state.userDict from server, merging over any local state so
        // an in-flight click isn't clobbered by a stale server payload.
        if (meta && meta.user_dict) {
          state.userDict = { ...meta.user_dict, ...state.userDict };
        }
        let title = "Книга";
        if (Array.isArray(books)) {
          const found = books.find((b) => b.id === meta.book_id);
          if (found && found.title) title = found.title;
        }
        setState({
          currentBook: {
            bookId: meta.book_id,
            title,
            totalPages: meta.total_pages,
            pages: targetPage ? [targetPage] : [],
            loadedFirstIndex: lastIdx,
            loadedLastIndex: lastIdx,
            userDict: meta.user_dict || {},
          },
          targetPageIndex: lastIdx,
          targetOffset: lastOff,
          restoring: true,
        });
        return null;
      })
      .catch((err) => setState({ view: "error", error: err.message }));
    return;
  }

  root.innerHTML = "";

  // --- sticky header (M9.3) ---
  const header = document.createElement("header");
  header.className = "reader-header";

  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "back-btn";
  backBtn.setAttribute("aria-label", "В библиотеку");
  backBtn.textContent = "←";
  backBtn.addEventListener("click", () => navigate("/"));
  header.appendChild(backBtn);

  const titleEl = document.createElement("div");
  titleEl.className = "book-title";
  // XSS discipline: title goes in via textContent only.
  titleEl.textContent = state.currentBook.title || "Книга";
  header.appendChild(titleEl);

  // Right-side slot (reserved for settings button in a later milestone).
  // Empty div keeps the three-column grid balanced.
  const rightSlot = document.createElement("div");
  rightSlot.className = "header-right";
  header.appendChild(rightSlot);

  const progressBar = document.createElement("div");
  progressBar.className = "progress-bar";
  const progressFill = document.createElement("div");
  progressFill.className = "progress-fill";
  progressFill.style.width = "0%";
  progressBar.appendChild(progressFill);
  header.appendChild(progressBar);

  root.appendChild(header);

  const main = document.createElement("main");
  main.className = "reader size-m reader-root";

  // M10.3: sentinels flank the rendered .page sections so two
  // IntersectionObservers can pre-fetch neighbors as the user approaches
  // either end. The sentinels are 1-px divs; the observers are wired up
  // after this loop.
  const topSentinel = document.createElement("div");
  topSentinel.className = "sentinel sentinel-top";
  main.appendChild(topSentinel);

  const pageSections = [];
  for (const page of state.currentBook.pages) {
    const section = buildPageSection(page);
    pageSections.push({ page, section });
    main.appendChild(section);
  }

  const bottomSentinel = document.createElement("div");
  bottomSentinel.className = "sentinel sentinel-bottom";
  main.appendChild(bottomSentinel);

  main.addEventListener("click", onWordTap);

  root.appendChild(main);

  // --- scroll listener: auto-hide header + progress-bar update ---
  // Tear down any listener from a previous render before attaching a new
  // one (defensive — currentBook changes re-run renderReader()).
  teardownReaderScroll();
  _readerLastScrollY = window.scrollY || 0;
  // M10.4: reset the "last POSTed" memo on each mount so switching books
  // (or remounting the same book) never skips the first save because the
  // old book happened to land at the same (pageIndex, offset).
  _lastSaved = { pageIndex: null, offset: null };

  const totalPages =
    (state.currentBook && state.currentBook.totalPages) ||
    state.currentBook.pages.length ||
    1;

  const runScrollTick = () => {
    _readerScrollRafId = 0;
    const hdr = document.querySelector(".reader-header");
    if (!hdr) return;
    const y = window.scrollY || 0;
    const delta = y - _readerLastScrollY;
    // Auto-hide: only engage below the 100 px threshold. Above it we always
    // keep the header visible so the reader doesn't flicker at the top.
    if (y > 100 && delta > 0) {
      hdr.classList.add("hidden");
    } else if (delta < 0) {
      hdr.classList.remove("hidden");
    }
    _readerLastScrollY = y;

    // Progress bar — spec uses (currentPageIndex + 1) / totalPages.
    const idx = findVisiblePageIndex();
    const percent = Math.max(
      0,
      Math.min(100, Math.round(((idx + 1) / totalPages) * 100)),
    );
    const fill = hdr.querySelector(".progress-fill");
    if (fill) fill.style.width = `${percent}%`;

    // M10.4: same rAF tick drives the debounced progress save so we don't
    // add a second scroll listener. scheduleProgressSave bails internally
    // while state.restoring is true.
    scheduleProgressSave();
  };

  _readerScrollHandler = () => {
    // Throttle via requestAnimationFrame — a single tick per frame, which
    // is plenty for a 60Hz scroll and avoids jank from layout reads.
    if (_readerScrollRafId) return;
    _readerScrollRafId = requestAnimationFrame(runScrollTick);
  };
  window.addEventListener("scroll", _readerScrollHandler, { passive: true });

  // M10.4: flush the current position on tab close via sendBeacon. We
  // fire unconditionally (not just when `_saveTimer` is pending) because
  // the browser might also kill us between two debounce windows where
  // the timer is clear but the user has scrolled since the last POST.
  // sendBeacon is the only transport that reliably ships during unload.
  _beforeUnloadHandler = () => {
    if (state.restoring) return;
    const cb = state.currentBook;
    if (!cb || cb.bookId == null) return;
    if (_saveTimer) {
      clearTimeout(_saveTimer);
      _saveTimer = null;
    }
    const section = findVisiblePageSection();
    if (!section) return;
    const pageIndex = Number(section.dataset.pageIndex);
    if (!Number.isFinite(pageIndex)) return;
    const offset = computeOffset(section);
    try {
      const body = JSON.stringify({
        last_page_index: pageIndex,
        last_page_offset: offset,
      });
      const blob = new Blob([body], { type: "application/json" });
      navigator.sendBeacon(`/api/books/${cb.bookId}/progress`, blob);
    } catch (_e) {
      // Silent — nothing we can do during unload.
    }
  };
  window.addEventListener("beforeunload", _beforeUnloadHandler);

  // Prime the progress bar so it reflects the initially-visible page.
  runScrollTick();

  // Apply auto-translations post-render. Pass 1: per-page auto_unit_ids
  // (Units whose lemma matched the server-side dictionary).
  for (const { page, section } of pageSections) {
    const autoIds = page.auto_unit_ids || [];
    for (const unitId of autoIds) {
      // Look up the unit's lemma from the page payload so we can find the
      // right translation in state.userDict (keys are lowercased lemmas).
      const unit = (page.units || []).find((u) => u.id === unitId);
      if (!unit) continue;
      const ru = state.userDict[unit.lemma.toLowerCase()];
      if (!ru) continue;
      applyAutoTranslation(section, unitId, ru);
    }
  }
  // Pass 2: sweep plain (non-unit) `.word[data-lemma=...]` spans across the
  // whole reader once, for every lemma currently in state.userDict.
  for (const lemma of Object.keys(state.userDict)) {
    const ru = state.userDict[lemma];
    const sel = `.word[data-lemma="${CSS.escape(lemma)}"]:not(.translated)`;
    main.querySelectorAll(sel).forEach((span) => {
      replaceWithTranslation(span, ru);
    });
  }

  // M10.3: wire up sentinel-based lazy loading of neighboring pages. The
  // observers live for the lifetime of the reader view; `teardownReaderScroll`
  // disconnects them on navigation, and each callback disables itself once
  // it hits the book boundary. We check `state.restoring` at the callback
  // top so the restore pass doesn't race with a fetch that would then shift
  // layout under restoreScroll's feet.
  if (typeof IntersectionObserver !== "undefined") {
    const cb = state.currentBook;
    // If we already rendered the full book (single-page case or tiny book),
    // skip both observers entirely — nothing to fetch.
    const needTop = cb.loadedFirstIndex > 0;
    const needBottom = cb.loadedLastIndex < cb.totalPages - 1;
    if (needTop) {
      _topObs = new IntersectionObserver(
        (entries) => {
          if (state.restoring) return;
          if (!entries.some((e) => e.isIntersecting)) return;
          loadAbove();
        },
        { rootMargin: "400px 0px 0px 0px" },
      );
      _topObs.observe(topSentinel);
    }
    if (needBottom) {
      _bottomObs = new IntersectionObserver(
        (entries) => {
          if (state.restoring) return;
          if (!entries.some((e) => e.isIntersecting)) return;
          loadBelow();
        },
        { rootMargin: "0px 0px 400px 0px" },
      );
      _bottomObs.observe(bottomSentinel);
    }
  }

  // M10.2: kick off scroll restoration. `state.restoring` was set by the
  // loader branch above; we honour it here so re-renders that don't carry
  // a fresh restore intent (e.g. a userDict change mid-read) don't snap
  // the viewport back to the target.
  if (state.restoring) {
    restoreScroll();
  }
}

// --- lazy neighbor loading (M10.3) ---
// Apply the same `auto_unit_ids` + lemma-sweep passes renderReader runs,
// but scoped to a single freshly-inserted page section. Keeps the new page
// visually consistent with its neighbors without re-sweeping the whole
// reader DOM on every prepend/append.
function applyTranslationsToSection(page, section) {
  const autoIds = page.auto_unit_ids || [];
  for (const unitId of autoIds) {
    const unit = (page.units || []).find((u) => u.id === unitId);
    if (!unit) continue;
    const ru = state.userDict[unit.lemma.toLowerCase()];
    if (!ru) continue;
    applyAutoTranslation(section, unitId, ru);
  }
  // Pass-2 lemma sweep within the new section only (not the full reader).
  for (const lemma of Object.keys(state.userDict)) {
    const ru = state.userDict[lemma];
    const sel = `.word[data-lemma="${CSS.escape(lemma)}"]:not(.translated)`;
    section.querySelectorAll(sel).forEach((span) => {
      replaceWithTranslation(span, ru);
    });
  }
}

async function loadBelow() {
  if (_loadingBottom) return;
  if (state.restoring) return;
  const cb = state.currentBook;
  if (!cb) return;
  const nextIdx = cb.loadedLastIndex + 1;
  if (nextIdx >= cb.totalPages) {
    if (_bottomObs) {
      _bottomObs.disconnect();
      _bottomObs = null;
    }
    return;
  }
  _loadingBottom = true;
  try {
    const data = await apiGet(
      `/api/books/${encodeURIComponent(cb.bookId)}/content?offset=${nextIdx}&limit=1`,
    );
    if (state.view !== "reader" || state.currentBook !== cb) return;
    const page =
      Array.isArray(data.pages) && data.pages.length ? data.pages[0] : null;
    if (!page) return;
    const section = buildPageSection(page);
    applyTranslationsToSection(page, section);

    const bottomSentinel = document.querySelector(".sentinel-bottom");
    if (!bottomSentinel || !bottomSentinel.parentNode) return;
    bottomSentinel.parentNode.insertBefore(section, bottomSentinel);

    cb.loadedLastIndex = nextIdx;
    cb.pages.push(page);

    if (cb.loadedLastIndex === cb.totalPages - 1 && _bottomObs) {
      _bottomObs.disconnect();
      _bottomObs = null;
    }
  } catch (_err) {
    // Network failure: drop the guard so the observer can retry on the
    // next intersection tick. A persistent outage just means the reader
    // stops at whatever's loaded — acceptable for M10.3.
  } finally {
    _loadingBottom = false;
  }
}

async function loadAbove() {
  if (_loadingTop) return;
  if (state.restoring) return;
  const cb = state.currentBook;
  if (!cb) return;
  const prevIdx = cb.loadedFirstIndex - 1;
  if (prevIdx < 0) {
    if (_topObs) {
      _topObs.disconnect();
      _topObs = null;
    }
    return;
  }
  _loadingTop = true;
  try {
    const data = await apiGet(
      `/api/books/${encodeURIComponent(cb.bookId)}/content?offset=${prevIdx}&limit=1`,
    );
    if (state.view !== "reader" || state.currentBook !== cb) return;
    const page =
      Array.isArray(data.pages) && data.pages.length ? data.pages[0] : null;
    if (!page) return;
    const section = buildPageSection(page);
    applyTranslationsToSection(page, section);

    const topSentinel = document.querySelector(".sentinel-top");
    if (!topSentinel || !topSentinel.parentNode) return;

    // Scroll compensation: snapshot scrollHeight + scrollY BEFORE the
    // insertion, then `scrollTo` the delta synchronously afterwards so
    // the user's viewport stays anchored to the page they were reading.
    // `document.documentElement.scrollHeight` is more reliable than
    // `document.body.scrollHeight` across mobile browsers.
    const scrollHeightBefore = document.documentElement.scrollHeight;
    const scrollTopBefore = window.scrollY;

    // Insert AFTER the top sentinel (before any existing .page section).
    topSentinel.parentNode.insertBefore(section, topSentinel.nextSibling);

    const scrollHeightAfter = document.documentElement.scrollHeight;
    const delta = scrollHeightAfter - scrollHeightBefore;
    window.scrollTo(0, scrollTopBefore + delta);

    cb.loadedFirstIndex = prevIdx;
    cb.pages.unshift(page);

    if (cb.loadedFirstIndex === 0 && _topObs) {
      _topObs.disconnect();
      _topObs = null;
    }
  } catch (_err) {
    // See loadBelow — leave _loadingTop to be cleared in finally and let
    // the next intersection retry.
  } finally {
    _loadingTop = false;
  }
}

function renderLoading() {
  document.getElementById("root").innerHTML = `<div class="loader">Loading…</div>`;
}

function renderError() {
  const root = document.getElementById("root");
  root.innerHTML = "";
  const box = document.createElement("div");
  box.className = "error";
  box.textContent = state.error ?? "Unknown error";
  const p = document.createElement("p");
  const link = document.createElement("a");
  link.id = "go-home";
  link.href = "/";
  link.textContent = "Go home";
  link.onclick = (ev) => {
    ev.preventDefault();
    navigate("/");
  };
  p.appendChild(link);
  root.append(box, p);
}

// --- inline translation (M4.2) ---
function getSentenceFor(span) {
  const sentEl = span.closest("[data-sentence-id]");
  if (sentEl) return sentEl.textContent;
  const page = span.closest(".page-body");
  return page ? page.textContent.slice(0, 300) : "";
}

async function onWordTap(e) {
  const span = e.target.closest(".word");
  if (!span) return;
  if (span.classList.contains("translated")) {
    openWordSheet(span);
    return;
  }
  await translateAndReplace(span);
}

async function translateAndReplace(span) {
  if (span.classList.contains("loading")) return;
  const lemma = span.dataset.lemma;
  const pairId = span.dataset.pairId;
  const unitText = span.textContent.trim();
  const sentence = getSentenceFor(span);

  span.classList.add("loading");

  let ru;
  try {
    const r = await apiPost("/api/translate", {
      unit_text: unitText,
      sentence,
      lemma,
    });
    ru = r.ru;
  } catch (err) {
    span.classList.remove("loading");
    toast("Не удалось перевести");
    return;
  }

  withScrollAnchor(() => {
    state.userDict[lemma] = ru;

    const lemmaSel = `.word[data-lemma="${CSS.escape(lemma)}"]`;
    document.querySelectorAll(lemmaSel).forEach((w) => {
      replaceWithTranslation(w, ru);
    });
    if (pairId != null) {
      const pairSel = `.word[data-pair-id="${CSS.escape(pairId)}"]`;
      document.querySelectorAll(pairSel).forEach((w) => {
        if (!w.classList.contains("translated")) replaceWithTranslation(w, ru);
      });
    }

    span.classList.add("highlighted");
    setTimeout(() => span.classList.remove("highlighted"), 800);
  });

  toast("В словарь ✓");
}

function replaceWithTranslation(span, ru) {
  if (!("originalText" in span.dataset)) {
    span.dataset.originalText = span.textContent;
  }
  span.textContent = ru;
  span.classList.remove("loading");
  span.classList.add("translated");
}

function revertTranslation(lemma) {
  // Primary pass: restore all spans with this data-lemma.
  const lemmaSel = `.word.translated[data-lemma="${CSS.escape(lemma)}"]`;
  const reverted = new Set();
  document.querySelectorAll(lemmaSel).forEach((w) => {
    if (w.dataset.originalText != null) {
      w.textContent = w.dataset.originalText;
      delete w.dataset.originalText;
    }
    w.classList.remove("translated");
    if (w.dataset.pairId != null) reverted.add(w.dataset.pairId);
  });

  // Secondary pass: restore any paired halves that were translated via pair_id.
  for (const pid of reverted) {
    const pairSel = `.word.translated[data-pair-id="${CSS.escape(pid)}"]`;
    document.querySelectorAll(pairSel).forEach((w) => {
      if (w.dataset.originalText != null) {
        w.textContent = w.dataset.originalText;
        delete w.dataset.originalText;
      }
      w.classList.remove("translated");
    });
  }

  delete state.userDict[lemma];

  // Fire-and-forget server sync. A network failure here must NOT block the
  // client-side revert that already happened above.
  apiDelete(`/api/dictionary/${encodeURIComponent(lemma)}`).catch((err) => {
    console.warn("DELETE /api/dictionary failed", err);
  });
}

// --- bottom sheet (M4.2 minimal; M16.2 later) ---
function closeSheet() {
  document.querySelectorAll(".sheet-backdrop, .sheet").forEach((n) => n.remove());
  document.removeEventListener("keydown", onSheetKeydown);
}

function onSheetKeydown(e) {
  if (e.key === "Escape") closeSheet();
}

function openWordSheet(span) {
  closeSheet(); // ensure only one open at a time

  const lemma = span.dataset.lemma;
  const original = span.dataset.originalText ?? span.textContent;
  const ruText = span.textContent;
  const sentenceText = getSentenceFor(span);

  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop";
  backdrop.addEventListener("click", closeSheet);

  const sheet = document.createElement("div");
  sheet.className = "sheet";
  sheet.setAttribute("role", "dialog");

  const headword = document.createElement("div");
  headword.className = "sheet-headword";
  headword.textContent = original;
  sheet.appendChild(headword);

  const meta = document.createElement("div");
  meta.className = "sheet-meta";
  meta.textContent = "— · —";
  sheet.appendChild(meta);

  const tCard = document.createElement("div");
  tCard.className = "sheet-card sheet-translation";
  tCard.textContent = ruText;
  sheet.appendChild(tCard);

  // "Из книги" section — sentence with the RU translation wrapped in <b>.
  const fromBook = document.createElement("div");
  fromBook.className = "sheet-from-book";
  const uplabel = document.createElement("div");
  uplabel.className = "uplabel";
  uplabel.textContent = "Из книги";
  fromBook.appendChild(uplabel);

  const sentWrap = document.createElement("div");
  sentWrap.className = "sheet-from-book-text";
  // Sentence text already contains the RU word (it was replaced in the DOM).
  // Highlight the first occurrence by splitting on the RU string.
  const idx = ruText ? sentenceText.indexOf(ruText) : -1;
  if (idx >= 0 && ruText) {
    sentWrap.appendChild(document.createTextNode(sentenceText.slice(0, idx)));
    const b = document.createElement("b");
    b.setAttribute("style", "color:var(--accent)");
    b.textContent = ruText;
    sentWrap.appendChild(b);
    sentWrap.appendChild(
      document.createTextNode(sentenceText.slice(idx + ruText.length)),
    );
  } else {
    sentWrap.textContent = sentenceText;
  }
  fromBook.appendChild(sentWrap);
  sheet.appendChild(fromBook);

  const actions = document.createElement("div");
  actions.className = "sheet-actions";
  const primary = document.createElement("button");
  primary.className = "btn primary";
  primary.textContent = "✓ В словаре";
  primary.disabled = true;
  const ghost = document.createElement("button");
  ghost.className = "btn ghost";
  ghost.textContent = "Оригинал";
  ghost.addEventListener("click", () => {
    revertTranslation(lemma);
    closeSheet();
    toast("Вернули оригинал");
  });
  actions.appendChild(primary);
  actions.appendChild(ghost);
  sheet.appendChild(actions);

  document.body.appendChild(backdrop);
  document.body.appendChild(sheet);
  document.addEventListener("keydown", onSheetKeydown);
}

// --- helpers (M4.2) ---
function withScrollAnchor(mutateSync) {
  // Pick the page whose top is nearest to the viewport top (but still visible
  // — preferring above-the-fold if any). Falls back to first page if nothing
  // is on screen, and to a plain mutate if no pages exist.
  const pages = Array.from(document.querySelectorAll(".page"));
  if (pages.length === 0) {
    mutateSync();
    return;
  }
  const vh = window.innerHeight;
  let anchor = null;
  let bestDist = Infinity;
  for (const p of pages) {
    const top = p.getBoundingClientRect().top;
    if (top > vh) continue;
    const dist = Math.abs(top);
    if (dist < bestDist) {
      bestDist = dist;
      anchor = p;
    }
  }
  if (!anchor) anchor = pages[0];
  const topBefore = anchor.getBoundingClientRect().top;
  mutateSync();
  const topAfter = anchor.getBoundingClientRect().top;
  window.scrollBy(0, topAfter - topBefore);
}

function toast(message) {
  document.querySelectorAll(".toast").forEach((n) => n.remove());
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  }, 2000);
}

// --- render ---
function render() {
  switch (state.view) {
    case "library": return renderLibrary();
    case "reader": return renderReader();
    case "loading": return renderLoading();
    case "error": return renderError();
    default: return renderError();
  }
}

// --- bootstrap ---
{
  const dark = (localStorage.theme === "dark") ||
    (localStorage.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) document.documentElement.classList.add("dark");
}
window.addEventListener("popstate", onPopState);
{
  const path = location.pathname;
  const { view } = parseRoute(path);
  const patch = { route: path, view };
  if (view === "error") patch.error = `Unknown route: ${path}`;
  setState(patch);
}
