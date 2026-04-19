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
};

// Reader scroll state (M9.3). Kept at module scope so we can detach the
// listener when leaving the reader view without leaking a closure per render.
let _readerScrollHandler = null;
let _readerLastScrollY = 0;
let _readerScrollRafId = 0;

function setState(patch) {
  const prevView = state.view;
  Object.assign(state, patch);
  // Leaving the reader view? Tear down the scroll listener set up by
  // renderReader so we don't keep reacting to scrolls on the library.
  if (prevView === "reader" && state.view !== "reader") {
    teardownReaderScroll();
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

// Find the page `<section class="page">` whose vertical center is nearest to
// the viewport center and return its `data-page-index` as a Number. Returns
// 0 when no page sections exist in the DOM.
function findVisiblePageIndex() {
  const pages = document.querySelectorAll("section.page");
  if (!pages.length) return 0;
  const vCenter = window.innerHeight / 2;
  let bestIdx = 0;
  let bestDist = Infinity;
  for (const p of pages) {
    const rect = p.getBoundingClientRect();
    const center = rect.top + rect.height / 2;
    const dist = Math.abs(center - vCenter);
    if (dist < bestDist) {
      bestDist = dist;
      const raw = p.dataset.pageIndex;
      const n = Number(raw);
      bestIdx = Number.isFinite(n) ? n : 0;
    }
  }
  return bestIdx;
}

function renderReader() {
  const root = document.getElementById("root");
  if (state.currentBook === null) {
    // Derive bookId from the current route (default 1 for legacy /reader).
    const parsed = parseRoute(state.route);
    const bookId = parsed.bookId != null ? parsed.bookId : 1;
    root.innerHTML = `<div class="loader">Loading…</div>`;
    // Pull the first 20 pages up-front; true lazy loading is M10.3.
    // Fetch book metadata in parallel — /api/books/{id}/content doesn't
    // include the title, so we look it up in /api/books. A metadata failure
    // must NOT block the reader: we fall back to "Книга".
    Promise.all([
      loadBookContent(bookId, 0, 20),
      apiGet("/api/books").catch(() => null),
    ])
      .then(([data, books]) => {
        if (state.view !== "reader") return;
        // Seed state.userDict from server, merging over any local state so
        // an in-flight click isn't clobbered by a stale server payload.
        if (data && data.user_dict) {
          state.userDict = { ...data.user_dict, ...state.userDict };
        }
        let title = "Книга";
        if (Array.isArray(books)) {
          const found = books.find((b) => b.id === data.book_id);
          if (found && found.title) title = found.title;
        }
        setState({
          currentBook: {
            bookId: data.book_id,
            title,
            totalPages: data.total_pages,
            pages: data.pages || [],
            userDict: data.user_dict || {},
          },
        });
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

  const pageSections = [];
  for (const page of state.currentBook.pages) {
    const section = buildPageSection(page);
    pageSections.push({ page, section });
    main.appendChild(section);
  }

  main.addEventListener("click", onWordTap);

  root.appendChild(main);

  // --- scroll listener: auto-hide header + progress-bar update ---
  // Tear down any listener from a previous render before attaching a new
  // one (defensive — currentBook changes re-run renderReader()).
  teardownReaderScroll();
  _readerLastScrollY = window.scrollY || 0;

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
  };

  _readerScrollHandler = () => {
    // Throttle via requestAnimationFrame — a single tick per frame, which
    // is plenty for a 60Hz scroll and avoids jank from layout reads.
    if (_readerScrollRafId) return;
    _readerScrollRafId = requestAnimationFrame(runScrollTick);
  };
  window.addEventListener("scroll", _readerScrollHandler, { passive: true });

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
