// en-reader SPA (M3.3 + M4.2 + M16.2): state + router + reader render +
// inline translation + shared sheet/toast/tabbar components.
// XSS discipline: any text from API responses goes via document.createTextNode / textContent only.

// --- M16.2: icons (SVG string literals from tasks/_assets/design/prototype.html) ---
// These are static, trusted markup — the whole reason we use innerHTML for
// them. User-facing text (labels, messages) always flows through textContent.
const _ICONS = {
  books: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5v13Z"/><path d="M4 19.5A2.5 2.5 0 0 1 6.5 22H20v-5"/></svg>',
  compass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5.5-5.5 2 2-5.5 5.5-2Z"/></svg>',
  dict: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h11a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4Z"/><path d="M4 16a4 4 0 0 1 4-4h11"/></svg>',
  brain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 2.8V13a3 3 0 0 0 2 2.8V17a3 3 0 0 0 3 3h.5V4H9Z"/><path d="M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 2.8V13a3 3 0 0 1-2 2.8V17a3 3 0 0 1-3 3h-.5V4H15Z"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  chevL: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 6-6 6 6 6"/></svg>',
  chevR: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>',
  star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 2.9 5.9 6.5.95-4.7 4.6 1.1 6.5L12 17.9 6.2 20.95l1.1-6.5L2.6 9.85l6.5-.95L12 3Z"/></svg>',
  undo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h11a6 6 0 0 1 0 12H8"/><path d="m7 3-4 4 4 4"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h10"/><path d="M4 12h6"/><path d="M4 17h12"/><circle cx="18" cy="7" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="20" cy="17" r="2"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  fire: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3c1.5 3 3.5 4.5 3.5 7.5 0 2-1.5 3.5-3.5 3.5-1 0-2-.5-2-2 0-1 .5-1.5.5-2.5-2 1-3.5 3-3.5 5.5 0 3 2.5 5.5 5.5 5.5s5.5-2.5 5.5-5.5c0-5-3-7-6-12Z"/></svg>',
  trend: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m3 17 5-5 4 4 8-8"/><path d="M15 8h5v5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m4 12 5 5 11-11"/></svg>',
};

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
  // Auth (M11.3). `authMode` toggles between login + signup on the /login
  // screen; it resets to "login" on every page load (nothing persisted).
  // `authError` renders a user-friendly message under the form.
  authMode: "login",
  authError: null,
  // M12.4: filename of the book currently being uploaded. Drives the
  // skeleton card that renders in the library grid just before the
  // `.add-card` tile. Null when no upload is in flight.
  uploadingFilename: null,
  // M16.4: dictionary screen state. `dictWords` is the last-fetched list
  // of entries from `/api/dictionary/words`; `null` means "not fetched
  // yet", `[]` is the valid loaded-and-empty state. `dictStats` mirrors
  // `/api/dictionary/stats`. `dictFilter` is the currently-active chip
  // id ("all" | "review" | "learning" | "new" | "mastered"); changing
  // it triggers a refetch.
  dictWords: null,
  dictStats: null,
  dictFilter: "all",
  // M16.5: catalog screen. `catalog` is the grouped-sections payload
  // from /api/catalog; `null` means "not fetched", non-null is the
  // loaded state. `catalogLevel` is the currently-selected level chip
  // (A1..C1); it defaults to B1 and is client-only for now — no
  // persistence until user.preferred_level lands.
  catalog: null,
  catalogLevel: "B1",
  catalogImporting: false,
  // M16.6: training session. `state.learn` is null outside the
  // learnCard flow; once the session starts it carries
  // {pool, idx, correct, feedback, pickedWrong, done}. `state.learn`
  // is ephemeral — never persisted. `state.learnStats` is a legacy
  // placeholder kept around for back-compat with mid-flight reads;
  // M16.8 now drives the real counter via `state.streak` below.
  learn: null,
  learnStats: null,
  // M16.7: flashcards session. `state.flash` mirrors `state.learn`
  // in lifecycle — null outside /learn/flash, populated on entry
  // with {pool, idx, flipped, correct, done}. Same backend; the
  // mode difference is purely UI (flip card + binary Knew/Didn't).
  flash: null,
  // M16.8: streak + daily-goal payload from GET /api/me/streak.
  // `null` = not fetched yet (renders a neutral placeholder);
  // object = {streak:N, today:{target,done,percent}}. Cleared on
  // leaving the library and on leaving any learn screen so a revisit
  // refetches — stats drift mid-session otherwise.
  streak: null,
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
  // M11.3: both /login and /signup render the same auth screen; the
  // signup/login toggle is driven by state.authMode so both paths map to
  // a single view and the UI switch button is the canonical mode driver.
  // M17.3: direct-land on /signup should flip authMode automatically so
  // a user who clicked "Sign up" in an email doesn't see the login form.
  if (path === "/signup") return { view: "login", authMode: "signup" };
  if (path === "/login") return { view: "login", authMode: "login" };
  // M16.4: dictionary screen. Tab bar's "dict" tab routes here.
  if (path === "/dict") return { view: "dictionary" };
  // M16.5: catalog screen. Tab bar's "cat" tab routes here.
  if (path === "/cat") return { view: "catalog" };
  // M16.6: training screens. `/learn` is the home (mode picker);
  // `/learn/card` is the multiple-choice session. M16.7 adds
  // `/learn/flash` — the flashcards flip-session.
  if (path === "/learn") return { view: "learnHome" };
  if (path === "/learn/card") return { view: "learnCard" };
  if (path === "/learn/flash") return { view: "learnFlash" };
  const m = BOOK_ROUTE_RE.exec(path);
  if (m) return { view: "reader", bookId: Number(m[1]) };
  return { view: "error" };
}

function navigate(path) {
  history.pushState({}, "", path);
  const parsed = parseRoute(path);
  const patch = { route: path, view: parsed.view };
  if (parsed.view === "error") patch.error = `Unknown route: ${path}`;
  // M17.3: /signup and /login carry authMode hints so a direct land picks
  // the right form without the user toggling.
  if (parsed.authMode) patch.authMode = parsed.authMode;
  // A navigation to a different book should drop any previously-loaded content.
  if (parsed.view === "reader") {
    const prev = state.currentBook;
    if (!prev || prev.bookId !== parsed.bookId) patch.currentBook = null;
  }
  // Leaving the library? Forget the cached listing so a later visit refetches.
  if (state.view === "library" && parsed.view !== "library") {
    patch.books = undefined;
    // M16.8: drop the streak card cache alongside the book list so
    // answers posted from the learn screens show up on next library
    // entry.
    patch.streak = null;
  }
  // M16.4: leaving the dictionary screen drops its caches so a revisit
  // refetches (counters could have changed mid-session).
  if (state.view === "dictionary" && parsed.view !== "dictionary") {
    patch.dictWords = null;
    patch.dictStats = null;
  }
  // M16.5: leaving the catalog drops its cached sections; level chip
  // persists across revisits so the user's last pick is remembered.
  if (state.view === "catalog" && parsed.view !== "catalog") {
    patch.catalog = null;
  }
  // M16.6/M16.7: leaving any learn screen drops the session state
  // so a revisit always starts fresh. Results are persisted
  // server-side after each answer, not in `state.learn` or
  // `state.flash`. We also clear on entry to /learn (home) so the
  // "Вернуться" button on the done screen doesn't leave a completed
  // session in memory that re-renders on a re-entry to a mode.
  const _isLearnView = (v) =>
    v === "learnHome" || v === "learnCard" || v === "learnFlash";
  const leavingLearn = _isLearnView(state.view) && !_isLearnView(parsed.view);
  if (leavingLearn || parsed.view === "learnHome") {
    patch.learn = null;
    patch.learnStats = null;
    patch.flash = null;
    // M16.8: same reason as library — streak counters may have moved
    // during the session we're leaving, so force a refetch on reentry.
    patch.streak = null;
  }
  setState(patch);
}

function onPopState() {
  const path = location.pathname;
  const parsed = parseRoute(path);
  const patch = { route: path, view: parsed.view };
  if (parsed.view === "error") patch.error = `Unknown route: ${path}`;
  if (parsed.authMode) patch.authMode = parsed.authMode;
  if (parsed.view === "reader") {
    const prev = state.currentBook;
    if (!prev || prev.bookId !== parsed.bookId) patch.currentBook = null;
  }
  if (state.view === "library" && parsed.view !== "library") {
    patch.books = undefined;
    patch.streak = null;
  }
  if (state.view === "dictionary" && parsed.view !== "dictionary") {
    patch.dictWords = null;
    patch.dictStats = null;
  }
  // M16.5: leaving the catalog drops its cached sections; level chip
  // persists across revisits so the user's last pick is remembered.
  if (state.view === "catalog" && parsed.view !== "catalog") {
    patch.catalog = null;
  }
  // M16.6/M16.7: leaving any learn screen drops the session state so
  // a revisit always starts fresh. Same "clear on entry to home" rule
  // as navigate(): prevents the done screen from persisting via
  // browser back/forward.
  const _isLearnView = (v) =>
    v === "learnHome" || v === "learnCard" || v === "learnFlash";
  const leavingLearn = _isLearnView(state.view) && !_isLearnView(parsed.view);
  if (leavingLearn || parsed.view === "learnHome") {
    patch.learn = null;
    patch.learnStats = null;
    patch.flash = null;
    patch.streak = null;
  }
  setState(patch);
}

// --- api ---

// M19.2: Telegram WebView (especially iOS Safari shell after a
// browser-back from a pushState navigation) sometimes drops the
// session cookie mid-session. The auto-login we ran at bootstrap()
// can't cover that case because back-nav doesn't re-enter bootstrap.
// This wrapper catches a 401 from any api* call, re-runs the Telegram
// handshake once, and retries the fetch. Outside the WebView the
// helper is a no-op (no window.Telegram.WebApp), so a real 401 just
// bubbles up to the caller as before.
let _tgReauthInflight = null;

async function _retryViaTelegram() {
  if (!(window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData)) {
    return false;
  }
  if (_tgReauthInflight) return _tgReauthInflight;
  _tgReauthInflight = (async () => {
    try {
      const res = await fetch("/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: window.Telegram.WebApp.initData }),
        credentials: "include",
      });
      return res.ok;
    } catch (_e) {
      return false;
    } finally {
      // Release the gate after a tick so concurrent 401-retriers don't all
      // race a second POST; a third 401 will open a new gate.
      setTimeout(() => {
        _tgReauthInflight = null;
      }, 0);
    }
  })();
  return _tgReauthInflight;
}

async function _fetchWithAuthRetry(path, init) {
  const res = await fetch(path, init);
  if (res.status !== 401) return res;
  const reauthed = await _retryViaTelegram();
  if (!reauthed) return res;
  return fetch(path, init);
}

async function apiGet(path) {
  const res = await _fetchWithAuthRetry(path, { credentials: "include" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await _fetchWithAuthRetry(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiDelete(path) {
  const res = await _fetchWithAuthRetry(path, {
    method: "DELETE",
    credentials: "include",
  });
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

// M12.4: POST a File to /api/books/upload, then refresh the library and
// navigate into the new book on success. Errors surface as toasts —
// there's no progress indicator beyond the skeleton card (spec §Что НЕ
// делать forbids per-upload progress).
async function uploadBook(file) {
  state.uploadingFilename = file.name;
  render();

  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch("/api/books/upload", {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      // The server responds with `{detail: "..."}` for HTTPException;
      // fall back to the HTTP status text if the body isn't JSON.
      const err = await resp.json().catch(() => ({ detail: `${resp.status}` }));
      throw new Error(err.detail || resp.statusText || `${resp.status}`);
    }
    const { book_id } = await resp.json();
    state.uploadingFilename = null;
    // Refresh the library so the newly-saved book shows up with the right
    // cover / preset before we even leave the grid — the reader view
    // fetches /api/books itself on mount, so this is belt-and-braces.
    try {
      const books = await apiGet("/api/books");
      state.books = Array.isArray(books) ? books : [];
    } catch (_e) {
      // Non-fatal: the library will refetch on next visit.
    }
    navigate(`/books/${book_id}`);
  } catch (e) {
    state.uploadingFilename = null;
    toast(`Не удалось загрузить: ${e.message}`);
    render();
  }
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

// M17.1: prototype's library header shows "Вторник · 9:41" — a weekday
// plus current time. We format dynamically so the screen feels alive
// on every open. Weekday is rendered in Russian long form; the time is
// HH:MM (24h). Hours/minutes are zero-padded.
function _formatLibraryDate(d) {
  const weekdays = [
    "Воскресенье",
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
  ];
  const wd = weekdays[d.getDay()];
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${wd} · ${hh}:${mm}`;
}

function renderLibrary() {
  const root = document.getElementById("root");

  // M16.2: library view owns the tab bar — show it here and paint the
  // "Мои книги" tab as active. The other tabs don't have destination
  // screens until M16.4/.5/.6, so for now we surface a "coming soon"
  // toast rather than navigate into a broken state.
  showTabBar();
  renderTabBar("lib", (id) => {
    if (id === "lib") return;
    if (id === "dict") {
      navigate("/dict");
      return;
    }
    if (id === "cat") {
      navigate("/cat");
      return;
    }
    if (id === "learn") {
      navigate("/learn");
      return;
    }
    // No more "Скоро" tabs — every id above routes to a real screen.
    showToast("Скоро");
  });

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

  // M16.8: kick off the streak fetch in parallel with the library
  // render. Failures are non-fatal — the card just stays hidden.
  if (state.streak === null) {
    apiGet("/api/me/streak")
      .then((data) => {
        if (state.view !== "library") return;
        setState({ streak: data });
      })
      .catch(() => {
        // 401 on a stale session would've redirected the user at
        // bootstrap already; anything else is transient and the card
        // will retry on next library entry.
      });
  }

  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "library screen-in";

  const header = document.createElement("header");
  header.className = "library-header";
  // M17.1: left column = date upper-label + H1 "Моя полка", matching the
  // Theme D prototype. Date is rendered client-side using the current
  // locale so the prototype's static "Вторник · 9:41" becomes a live
  // weekday + time of day (stripped of seconds).
  const headerLeft = document.createElement("div");
  const dateEl = document.createElement("div");
  dateEl.className = "date";
  dateEl.textContent = _formatLibraryDate(new Date());
  headerLeft.appendChild(dateEl);
  const h1 = document.createElement("h1");
  h1.textContent = "Моя полка";
  headerLeft.appendChild(h1);
  const headerRight = document.createElement("div");
  headerRight.className = "library-header-right";
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "E";
  // M11.3: logout button lives to the right of the avatar. On click we
  // fire-and-forget the logout POST (treating a failure as "session is
  // gone anyway") and navigate to /login so bootstrap never re-runs
  // against a now-dead session cookie.
  const logoutBtn = document.createElement("button");
  logoutBtn.type = "button";
  logoutBtn.className = "logout-btn";
  logoutBtn.title = "Выйти";
  logoutBtn.setAttribute("aria-label", "Выйти");
  logoutBtn.textContent = "Выйти";
  logoutBtn.addEventListener("click", async () => {
    try {
      await apiPost("/auth/logout", {});
    } catch (_e) {
      // Logout failures are ignored — we're navigating to /login either way.
    }
    navigate("/login");
  });
  // M18.4: gear → settings sheet (Telegram link lives here).
  const gearBtn = document.createElement("button");
  gearBtn.type = "button";
  gearBtn.className = "logout-btn";
  gearBtn.title = "Настройки";
  gearBtn.setAttribute("aria-label", "Настройки");
  gearBtn.textContent = "⚙";
  gearBtn.addEventListener("click", () => openSettingsSheet());
  headerRight.appendChild(avatar);
  headerRight.appendChild(gearBtn);
  headerRight.appendChild(logoutBtn);
  header.appendChild(headerLeft);
  header.appendChild(headerRight);
  main.appendChild(header);

  // M16.8: streak card sits between the header and the grid so the
  // motivational context is visible above the fold. We only render
  // when `state.streak` is loaded — skips the card entirely on first
  // paint (the async fetch above will re-render once the data lands)
  // and when the user has no activity yet (streak=0, done=0).
  if (state.streak && (state.streak.streak > 0 || state.streak.today.done > 0)) {
    const streakCard = document.createElement("div");
    streakCard.className = "streak-card";

    const fireBox = document.createElement("div");
    fireBox.className = "streak-card-icon";
    fireBox.innerHTML = _ICONS.fire;
    streakCard.appendChild(fireBox);

    const txt = document.createElement("div");
    txt.className = "streak-card-text";
    const title = document.createElement("div");
    title.className = "streak-card-title";
    title.textContent = `${state.streak.streak} дней подряд`;
    const sub = document.createElement("div");
    sub.className = "streak-card-sub";
    sub.textContent = `${state.streak.today.done} слов сегодня`;
    txt.appendChild(title);
    txt.appendChild(sub);
    streakCard.appendChild(txt);

    main.appendChild(streakCard);
  }

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

      // M12.4: if the book has a real cover on disk, serve it via
      // `/api/books/<id>/cover`; otherwise fall back to the deterministic
      // gradient preset (`c-olive`, `c-rose`, …) stamped on the server.
      if (b.has_cover) {
        const img = document.createElement("img");
        img.className = "cover";
        img.src = `/api/books/${encodeURIComponent(b.id)}/cover`;
        img.alt = "";
        card.appendChild(img);
      } else {
        const cover = document.createElement("div");
        cover.className = "cover-placeholder";
        if (b.cover_preset) cover.classList.add(b.cover_preset);
        cover.textContent = "📖";
        card.appendChild(cover);
      }

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

  // M12.4: skeleton "uploading" card lands right before the add-card
  // tile so the user sees their upload slot-in at the same visual
  // position where the new book will end up post-refresh.
  if (state.uploadingFilename) {
    const skel = document.createElement("div");
    skel.className = "card uploading";
    const skelCover = document.createElement("div");
    skelCover.className = "cover-placeholder";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    skelCover.appendChild(spinner);
    skel.appendChild(skelCover);

    const skelMeta = document.createElement("div");
    skelMeta.className = "meta";
    const skelTitle = document.createElement("div");
    skelTitle.className = "title";
    skelTitle.textContent = "Загружается…";
    const skelAuthor = document.createElement("div");
    skelAuthor.className = "author";
    // XSS discipline: filename comes from the user's OS, so textContent only.
    skelAuthor.textContent = state.uploadingFilename;
    skelMeta.appendChild(skelTitle);
    skelMeta.appendChild(skelAuthor);
    skel.appendChild(skelMeta);
    grid.appendChild(skel);
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
      // M12.4: spawn a hidden <input type=file>, click it, pass the
      // chosen file to uploadBook. No `accept` attribute — iOS Safari
      // rejects valid .fb2 files when we constrain on MIME.
      const input = document.createElement("input");
      input.type = "file";
      input.style.display = "none";
      input.addEventListener("change", (ev) => {
        const f = ev.target.files && ev.target.files[0];
        if (f) uploadBook(f);
        // Clean up the input once we've captured the file.
        if (input.parentNode) input.parentNode.removeChild(input);
      });
      document.body.appendChild(input);
      input.click();
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
  // M16.2: reader uses the full viewport — tab bar is hidden here.
  hideTabBar();
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
        // M10.5: mark this book as the current one so a later visit to `/`
        // redirects here. Fire-and-forget — a failed POST must not block the
        // render we just committed above.
        apiPost("/api/me/current-book", { book_id: meta.book_id }).catch(
          () => {},
        );
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
  // M10.5: explicit "back to library" clears the current-book pointer so a
  // subsequent visit to `/` lands on the library. We fire-and-forget (best
  // effort) and navigate regardless of the POST's outcome — a transient
  // network blip must not trap the reader.
  backBtn.addEventListener("click", async () => {
    await apiPost("/api/me/current-book", { book_id: null }).catch(() => {});
    navigate("/");
  });
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
  main.className = "reader size-m reader-root screen-in";

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

  // M19.1: per-instance translation. Every `.word` span whose lemma is
  // already in the user's dictionary gets its own 3-sentence-context
  // translation call. The server-side prompt-hash cache makes repeat
  // renders free; concurrent page insertions trigger their own
  // per-section sweep via `applyTranslationsToSection`. We run this in
  // the background so the reader is interactive immediately.
  preloadPageTranslations(main).catch(() => {});

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
  // M19.1: a freshly-inserted page (±1 from the visible viewport thanks
  // to the IntersectionObserver rootMargin) triggers per-instance
  // translation for every word whose lemma the user already knows. The
  // sweep runs in the background so the insert doesn't block scroll.
  // `page` is intentionally unused now — the old `auto_unit_ids` hint
  // was replaced by a DOM scan so the cross-sentence context lookup
  // (needed for the LLM prompt) can reuse `contextFor()` directly.
  void page;
  preloadPageTranslations(section).catch(() => {});
}

// M18.3b: IntersectionObserver only emits on boundary *crossings*, so if
// the new page we just inserted is short enough that the sentinel stays
// inside the 400 px rootMargin zone, we never get a second fire and the
// reader silently stops loading. Check with getBoundingClientRect after
// every successful insert and recurse if the sentinel is still hot.
function _sentinelStillHot(selector) {
  const sentinel = document.querySelector(selector);
  if (!sentinel) return false;
  const rect = sentinel.getBoundingClientRect();
  const vh = window.innerHeight || document.documentElement.clientHeight;
  if (selector === ".sentinel-bottom") return rect.top < vh + 400;
  return rect.bottom > -400; // .sentinel-top mirror of the 400 px rootMargin
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
  let loaded = false;
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
    loaded = true;

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
  if (loaded && _sentinelStillHot(".sentinel-bottom")) {
    queueMicrotask(loadBelow);
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
  let loaded = false;
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
    loaded = true;

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
  if (loaded && _sentinelStillHot(".sentinel-top")) {
    queueMicrotask(loadAbove);
  }
}

// --- M16.4: dictionary screen -----------------------------------------
// Chip ids map 1:1 to the `status` query on /api/dictionary/words so the
// filter row can stay a single source of truth. Label + stats-key are
// paired with the id so the render loop doesn't need a parallel lookup.
const _DICT_FILTERS = [
  { id: "all", label: "Все", statKey: "total" },
  { id: "review", label: "Повторить", statKey: "review" },
  { id: "learning", label: "Учу", statKey: "learning" },
  { id: "new", label: "Новые", statKey: "new" },
  { id: "mastered", label: "Выучено", statKey: "mastered" },
];

// Per-status badge presentation. Kept as a JS constant (rather than CSS
// classes) so the colour values — which the spec pins to specific hex
// codes, including the `#c9a253` mustard — live in one place the sheet
// and list-card can both read from. Dark-theme override is inlined as
// a second map and merged in at render time based on the <html> class.
const _DICT_BADGES = {
  new: { bg: "var(--accent)", color: "#fff", label: "новое" },
  learning: { bg: "var(--soft)", color: "var(--ink)", label: "учу" },
  review: { bg: "#c9a253", color: "#2d1a12", label: "повторить" },
  mastered: { bg: "#d8e0c0", color: "#2a3f14", label: "выучено" },
};
const _DICT_BADGES_DARK = {
  mastered: { bg: "#2a3f24", color: "#c5d5a0" },
};

function _badgeStyle(status) {
  const base = _DICT_BADGES[status] || _DICT_BADGES.new;
  const isDark = document.documentElement.classList.contains("dark");
  const override = isDark ? _DICT_BADGES_DARK[status] : null;
  return {
    bg: (override && override.bg) || base.bg,
    color: (override && override.color) || base.color,
    label: base.label,
  };
}

function _applyBadge(el, status) {
  const s = _badgeStyle(status);
  el.className = "badge";
  el.textContent = s.label;
  el.style.backgroundColor = s.bg;
  el.style.color = s.color;
}

// Fetch /stats + /words in parallel and stash them on state.
async function _fetchDictionary(filter) {
  try {
    const [stats, words] = await Promise.all([
      apiGet("/api/dictionary/stats"),
      apiGet(`/api/dictionary/words?status=${encodeURIComponent(filter)}`),
    ]);
    if (state.view !== "dictionary") return;
    setState({
      dictStats: stats,
      dictWords: Array.isArray(words) ? words : [],
    });
  } catch (err) {
    setState({ view: "error", error: err.message });
  }
}

function renderDictionary() {
  const root = document.getElementById("root");

  // Show the tab bar and paint "dict" as active. Clicking the other tabs
  // either navigates (lib) or toasts "Скоро" until later milestones ship
  // their screens.
  showTabBar();
  renderTabBar("dict", (id) => {
    if (id === "dict") return;
    if (id === "lib") {
      navigate("/");
      return;
    }
    if (id === "cat") {
      navigate("/cat");
      return;
    }
    if (id === "learn") {
      navigate("/learn");
      return;
    }
    showToast("Скоро");
  });

  // First entry (or revisit after leaving) — kick off the fetch. A null
  // dictWords is the "not fetched" signal; [] means loaded-and-empty.
  if (state.dictWords === null || state.dictStats === null) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    _fetchDictionary(state.dictFilter);
    return;
  }

  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "dictionary screen-in";

  // Header.
  const header = document.createElement("div");
  header.className = "dict-header";
  const h1 = document.createElement("h1");
  h1.textContent = "Словарь";
  header.appendChild(h1);
  const counter = document.createElement("span");
  counter.className = "counter";
  const total = (state.dictStats && state.dictStats.total) || 0;
  counter.textContent = `${total} слов`;
  header.appendChild(counter);
  main.appendChild(header);

  // Stats (3-col grid).
  const stats = document.createElement("div");
  stats.className = "dict-stats";
  const statItems = [
    { n: state.dictStats.review_today || 0, label: "Повт. / сегодня", cls: "review" },
    { n: state.dictStats.active || 0, label: "Учу сейчас", cls: "" },
    { n: state.dictStats.mastered || 0, label: "Выучено", cls: "" },
  ];
  for (const s of statItems) {
    const stat = document.createElement("div");
    stat.className = "stat";
    const n = document.createElement("div");
    n.className = "n" + (s.cls ? ` ${s.cls}` : "");
    n.textContent = String(s.n);
    const lbl = document.createElement("div");
    lbl.className = "lbl";
    lbl.textContent = s.label;
    stat.appendChild(n);
    stat.appendChild(lbl);
    stats.appendChild(stat);
  }
  main.appendChild(stats);

  // Filter chips.
  const filters = document.createElement("div");
  filters.className = "dict-filters";
  for (const f of _DICT_FILTERS) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip" + (state.dictFilter === f.id ? " on" : "");
    chip.dataset.filterId = f.id;
    // Label + "N" count in a sibling span so the `.chip .n` CSS (opacity)
    // can dim the count without affecting the label.
    chip.appendChild(document.createTextNode(f.label));
    const cnt = document.createElement("span");
    cnt.className = "n";
    const c = (state.dictStats && state.dictStats[f.statKey]) || 0;
    cnt.textContent = String(c);
    chip.appendChild(cnt);
    chip.addEventListener("click", () => {
      if (state.dictFilter === f.id) return;
      // Clear words so the loader branch re-fetches with the new filter.
      state.dictFilter = f.id;
      state.dictWords = null;
      render();
    });
    filters.appendChild(chip);
  }
  main.appendChild(filters);

  // Word list (or empty state).
  const words = state.dictWords || [];
  if (words.length === 0) {
    const empty = document.createElement("div");
    empty.className = "dict-empty";
    if (state.dictFilter === "all") {
      empty.textContent = "Здесь пока пусто";
    } else {
      const f = _DICT_FILTERS.find((x) => x.id === state.dictFilter);
      empty.textContent = f ? `Нет слов со статусом «${f.label}»` : "Здесь пока пусто";
    }
    main.appendChild(empty);
  } else {
    const list = document.createElement("div");
    list.className = "dict-list";
    for (const w of words) {
      list.appendChild(_buildWordItem(w));
    }
    main.appendChild(list);
  }

  root.appendChild(main);
}

function _buildWordItem(word) {
  const item = document.createElement("div");
  item.className = "word-item";
  item.dataset.lemma = word.lemma || "";

  const lhs = document.createElement("div");
  lhs.className = "lhs";

  const headLine = document.createElement("div");
  headLine.className = "head-line";
  const head = document.createElement("span");
  head.className = "head";
  head.textContent = word.lemma || "";
  headLine.appendChild(head);
  if (word.translation) {
    const tr = document.createElement("span");
    tr.className = "tr";
    tr.textContent = `— ${word.translation}`;
    headLine.appendChild(tr);
  }
  lhs.appendChild(headLine);

  if (word.example) {
    const ex = document.createElement("div");
    ex.className = "ex";
    // Trim whitespace and wrap in quote marks per spec prototype.
    const trimmed = String(word.example).trim();
    ex.textContent = trimmed ? `«${trimmed}»` : "";
    lhs.appendChild(ex);
  }

  const metaParts = [];
  const sourceTitle =
    word.source_book && word.source_book.title ? word.source_book.title : null;
  if (sourceTitle) metaParts.push(sourceTitle);
  if (word.days_since_review != null) {
    metaParts.push(`${word.days_since_review} дн.`);
  }
  if (metaParts.length) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaParts.join(" · ");
    lhs.appendChild(meta);
  }

  item.appendChild(lhs);

  const badge = document.createElement("span");
  _applyBadge(badge, word.status || "new");
  item.appendChild(badge);

  item.addEventListener("click", () => {
    openSheet(buildWordDetailSheet(word));
  });

  return item;
}

function buildWordDetailSheet(word) {
  const content = document.createElement("div");
  content.setAttribute("role", "dialog");

  const headword = document.createElement("div");
  headword.className = "sheet-headword";
  headword.textContent = word.lemma || "";
  content.appendChild(headword);

  const meta = document.createElement("div");
  meta.className = "sheet-meta";
  // IPA / POS land here in M17 — for now the spec asks for "— · —".
  const ipa = word.ipa || "—";
  const pos = word.pos || "—";
  meta.textContent = `${ipa} · ${pos}`;
  content.appendChild(meta);

  const tCard = document.createElement("div");
  tCard.className = "sheet-card sheet-translation";
  tCard.textContent = word.translation || "";
  content.appendChild(tCard);

  // "Из книги · <title>" section — only rendered when we know the source
  // book (words added before M16.3 have source_book=null).
  if (word.source_book && word.source_book.title) {
    const fromBook = document.createElement("div");
    fromBook.className = "sheet-from-book";
    const uplabel = document.createElement("div");
    uplabel.className = "uplabel";
    uplabel.textContent = `Из книги · ${word.source_book.title}`;
    fromBook.appendChild(uplabel);

    if (word.example) {
      const sentWrap = document.createElement("div");
      sentWrap.className = "sheet-from-book-text";
      const example = String(word.example);
      const translation = word.translation || "";
      // Case-insensitive find of the lemma OR translation token in the
      // example so we can bold it in accent colour per spec.
      let bolded = false;
      if (translation) {
        const idx = example.indexOf(translation);
        if (idx >= 0) {
          sentWrap.appendChild(document.createTextNode(example.slice(0, idx)));
          const b = document.createElement("b");
          b.setAttribute("style", "color:var(--accent)");
          b.textContent = translation;
          sentWrap.appendChild(b);
          sentWrap.appendChild(
            document.createTextNode(example.slice(idx + translation.length)),
          );
          bolded = true;
        }
      }
      if (!bolded && word.lemma) {
        const lemma = word.lemma;
        const lower = example.toLowerCase();
        const pos = lower.indexOf(lemma.toLowerCase());
        if (pos >= 0) {
          sentWrap.appendChild(document.createTextNode(example.slice(0, pos)));
          const b = document.createElement("b");
          b.setAttribute("style", "color:var(--accent)");
          b.textContent = example.slice(pos, pos + lemma.length);
          sentWrap.appendChild(b);
          sentWrap.appendChild(
            document.createTextNode(example.slice(pos + lemma.length)),
          );
          bolded = true;
        }
      }
      if (!bolded) {
        sentWrap.textContent = example;
      }
      fromBook.appendChild(sentWrap);
    }
    content.appendChild(fromBook);
  }

  const actions = document.createElement("div");
  actions.className = "sheet-actions";

  const primary = document.createElement("button");
  primary.className = "btn primary";
  primary.textContent = "Тренировать";
  primary.addEventListener("click", () => {
    closeSheet();
    navigate("/learn/card");
  });
  actions.appendChild(primary);

  const ghost = document.createElement("button");
  ghost.className = "btn ghost";
  ghost.textContent = "Удалить";
  ghost.addEventListener("click", async () => {
    if (!word.lemma) return;
    try {
      await apiDelete(`/api/dictionary/${encodeURIComponent(word.lemma)}`);
    } catch (_e) {
      showToast("Не удалось удалить");
      return;
    }
    closeSheet();
    showToast("Удалено");
    // Refetch both lists: /stats counters and /words for the current filter.
    state.dictWords = null;
    state.dictStats = null;
    if (state.view === "dictionary") _fetchDictionary(state.dictFilter);
  });
  actions.appendChild(ghost);

  content.appendChild(actions);
  return content;
}

// ---------- M16.5: catalog screen ----------

const _CATALOG_LEVELS = ["A1", "A2", "B1", "B2", "C1"];

async function _fetchCatalog(level) {
  try {
    const payload = await apiGet(
      `/api/catalog?level=${encodeURIComponent(level)}`,
    );
    setState({ catalog: payload.sections || [] });
  } catch (err) {
    setState({ view: "error", error: err.message });
  }
}

function _catalogLevelChips(activeLevel) {
  const wrap = document.createElement("div");
  wrap.className = "catalog-chips";
  for (const lvl of _CATALOG_LEVELS) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip" + (lvl === activeLevel ? " active" : "");
    chip.textContent = lvl;
    chip.addEventListener("click", () => {
      if (state.catalogImporting) return;
      if (state.catalogLevel === lvl) return;
      setState({ catalogLevel: lvl, catalog: null });
      _fetchCatalog(lvl);
    });
    wrap.appendChild(chip);
  }
  return wrap;
}

async function _importCatalogBook(item) {
  if (state.catalogImporting) return;
  state.catalogImporting = true;
  try {
    const resp = await apiPost(`/api/catalog/${item.id}/import`, {});
    showToast(
      resp.already_imported ? "Уже в библиотеке" : "Добавлено в библиотеку",
    );
    // Give the toast a breath before navigating so the user sees the
    // confirmation; 500 ms matches the spec's §4 handoff timing.
    setTimeout(() => {
      state.catalogImporting = false;
      navigate(`/books/${resp.book_id}`);
    }, 500);
  } catch (err) {
    state.catalogImporting = false;
    showToast("Не удалось добавить");
  }
}

function _catalogCard(item) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "catalog-card";
  // Gradient tile — reuses the .cover primitive + preset classes from M16.1.
  const cover = document.createElement("div");
  cover.className = `cover ${item.cover_preset || "c-olive"}`;
  card.appendChild(cover);

  const title = document.createElement("div");
  title.className = "catalog-card-title";
  title.textContent = item.title;
  card.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "catalog-card-meta";
  meta.textContent = `${item.level} · ${item.pages} стр.`;
  card.appendChild(meta);

  card.addEventListener("click", () => _importCatalogBook(item));
  return card;
}

function _catalogSection(section) {
  const wrap = document.createElement("section");
  wrap.className = "catalog-section";
  const label = document.createElement("div");
  label.className = "uplabel";
  label.textContent = section.key;
  wrap.appendChild(label);

  const row = document.createElement("div");
  row.className = "catalog-row";
  if (!section.items || section.items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "catalog-empty";
    empty.textContent = "Пока ничего";
    row.appendChild(empty);
  } else {
    for (const item of section.items) {
      row.appendChild(_catalogCard(item));
    }
  }
  wrap.appendChild(row);
  return wrap;
}

function renderCatalog() {
  const root = document.getElementById("root");
  showTabBar();
  renderTabBar("cat", (id) => {
    if (id === "cat") return;
    if (id === "lib") {
      navigate("/");
      return;
    }
    if (id === "dict") {
      navigate("/dict");
      return;
    }
    if (id === "learn") {
      navigate("/learn");
      return;
    }
    showToast("Скоро");
  });

  if (state.catalog === null) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    _fetchCatalog(state.catalogLevel);
    return;
  }

  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "catalog screen-in";

  const uplabel = document.createElement("div");
  uplabel.className = "uplabel";
  uplabel.textContent = "Каталог";
  main.appendChild(uplabel);

  const h1 = document.createElement("h1");
  h1.className = "catalog-h1";
  h1.textContent = "Что почитать";
  main.appendChild(h1);

  main.appendChild(_catalogLevelChips(state.catalogLevel));

  for (const section of state.catalog) {
    main.appendChild(_catalogSection(section));
  }

  root.appendChild(main);
}

// --- M16.6: training (multiple choice) ---------------------------------
// `/learn` is the home (mode picker) + daily-goal placeholder.
// `/learn/card` is the 4-option MC session. `state.learn` carries the
// whole session shape — see the comment on `state.learn` in the
// top-level state block for fields. The backend (M16.3) owns the
// progression state-machine; the frontend only POSTs per-answer
// results.

// Fallback distractors — used when the user's dictionary has fewer
// than 3 other words to draw from. Matches the prototype's list so a
// refresh on a sparse account still shows believable options.
const _LEARN_FALLBACK_DISTRACTORS = [
  "внушительный",
  "странный",
  "тёплый",
  "острый",
  "лёгкий",
  "прилежный",
  "хрупкий",
];

// Deterministic seeded shuffle. Given the same seed string and input
// array, always returns the same permutation — so a refresh of a
// learn card keeps the option order stable (seed = current lemma).
// Uses a tiny Mulberry32-style PRNG; good enough for 4-item arrays.
function _seededShuffle(arr, seed) {
  const out = arr.slice();
  let h = 2166136261 >>> 0;
  const s = String(seed || "");
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  function rand() {
    h = (h + 0x6d2b79f5) >>> 0;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    const tmp = out[i];
    out[i] = out[j];
    out[j] = tmp;
  }
  return out;
}

// Build the 4 MC options for the current word:
// - correct translation (always present)
// - up to 3 distractor translations from other pool words
// - padded with _LEARN_FALLBACK_DISTRACTORS if the pool is too small
// Dedupes against the correct answer so we never show it twice. The
// final order is a deterministic shuffle seeded by the lemma.
function buildOptions(currentWord, pool) {
  const correct = currentWord.translation;
  const seen = new Set([correct]);
  const distractors = [];
  for (const w of pool) {
    if (w.lemma === currentWord.lemma) continue;
    const t = w.translation;
    if (!t || seen.has(t)) continue;
    seen.add(t);
    distractors.push(t);
  }
  for (const t of _LEARN_FALLBACK_DISTRACTORS) {
    if (distractors.length >= 3) break;
    if (seen.has(t)) continue;
    seen.add(t);
    distractors.push(t);
  }
  const picks = [correct, ...distractors.slice(0, 3)];
  return _seededShuffle(picks, currentWord.lemma);
}

async function _fetchLearnPool() {
  try {
    const pool = await apiGet("/api/dictionary/training?limit=10");
    // Ignore the response if the user already navigated away.
    if (state.view !== "learnCard") return;
    setState({
      learn: {
        pool: Array.isArray(pool) ? pool : [],
        idx: 0,
        correct: 0,
        feedback: null,
        pickedWrong: null,
        done: false,
      },
    });
  } catch (err) {
    setState({ view: "error", error: err.message });
  }
}

function _advanceLearn() {
  // Guard: the user might have navigated away during the feedback
  // pause; re-check before touching state.learn.
  if (state.view !== "learnCard" || !state.learn) return;
  const total = state.learn.pool.length;
  const nextIdx = state.learn.idx + 1;
  const done = nextIdx >= total;
  state.learn.idx = nextIdx;
  state.learn.feedback = null;
  state.learn.pickedWrong = null;
  state.learn.done = done;
  render();
}

async function _postTrainingResult(lemma, correct) {
  try {
    await apiPost("/api/dictionary/training/result", { lemma, correct });
  } catch (_e) {
    // Swallow: the UI has already advanced; a transient failure here
    // shouldn't derail the session. The server is the source of truth,
    // so a missed POST just means one answer isn't scored. (M16.9 may
    // add a retry queue.)
  }
}

function renderLearnHome() {
  const root = document.getElementById("root");
  showTabBar();
  renderTabBar("learn", (id) => {
    if (id === "learn") return;
    if (id === "lib") {
      navigate("/");
      return;
    }
    if (id === "dict") {
      navigate("/dict");
      return;
    }
    if (id === "cat") {
      navigate("/cat");
      return;
    }
    showToast("Скоро");
  });

  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "learn-home screen-in";

  // M16.8: kick off the streak fetch on first entry. Same pattern as
  // the library card — re-renders on success, silently hides on
  // failure. Happens before we render the card below so the pbar /
  // text draw with live numbers on the second pass.
  if (state.streak === null) {
    apiGet("/api/me/streak")
      .then((data) => {
        if (state.view !== "learnHome") return;
        setState({ streak: data });
      })
      .catch(() => {});
  }

  const uplabel = document.createElement("div");
  uplabel.className = "uplabel";
  uplabel.textContent = "Тренировка";
  main.appendChild(uplabel);

  const h1 = document.createElement("h1");
  h1.className = "learn-h1";
  h1.textContent = "Что учим сегодня";
  main.appendChild(h1);

  // M16.8: daily-goal card now reads from `state.streak.today` when
  // available. Cold load (streak still fetching) falls back to zeros
  // so the card shape is stable and the pbar starts empty; it repaints
  // as soon as the fetch resolves via `setState`.
  const goalTotal =
    state.streak && state.streak.today ? state.streak.today.target : 10;
  const doneToday =
    state.streak && state.streak.today ? state.streak.today.done : 0;
  const pct =
    state.streak && state.streak.today
      ? state.streak.today.percent
      : 0;

  const goal = document.createElement("div");
  goal.className = "daily-goal";
  const goalRow = document.createElement("div");
  goalRow.className = "daily-goal-row";
  const fireBox = document.createElement("div");
  fireBox.className = "daily-goal-icon";
  // Fire SVG is trusted static markup → innerHTML is safe here.
  fireBox.innerHTML = _ICONS.fire;
  goalRow.appendChild(fireBox);

  const goalText = document.createElement("div");
  const goalTitle = document.createElement("div");
  goalTitle.className = "daily-goal-title";
  goalTitle.textContent = `Цель дня: ${goalTotal} слов`;
  const goalSub = document.createElement("div");
  goalSub.className = "daily-goal-sub";
  goalSub.textContent = `${doneToday} / ${goalTotal} сделано`;
  goalText.appendChild(goalTitle);
  goalText.appendChild(goalSub);
  goalRow.appendChild(goalText);
  goal.appendChild(goalRow);

  const pbar = document.createElement("div");
  pbar.className = "pbar";
  const pfill = document.createElement("i");
  pfill.style.width = `${pct}%`;
  pbar.appendChild(pfill);
  goal.appendChild(pbar);
  main.appendChild(goal);

  const modesLabel = document.createElement("div");
  modesLabel.className = "uplabel learn-modes-label";
  modesLabel.textContent = "Режимы";
  main.appendChild(modesLabel);

  // Two mode cards. "Выбор перевода" routes into the MC session
  // (M16.6); "Карточки" routes into the flashcard flip-session
  // (M16.7). Both use the same /training pool under the hood.
  const modes = [
    {
      id: "mc",
      emoji: "⚡",
      title: "Выбор перевода",
      desc: "4 варианта · быстро и бодро",
      onClick: () => navigate("/learn/card"),
    },
    {
      id: "fl",
      emoji: "🧠",
      title: "Карточки",
      desc: "Интервальные повторения",
      onClick: () => navigate("/learn/flash"),
    },
  ];
  for (const m of modes) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "mode-card";
    card.dataset.modeId = m.id;

    const emoji = document.createElement("div");
    emoji.className = "mode-card-emoji";
    emoji.textContent = m.emoji;
    card.appendChild(emoji);

    const txt = document.createElement("div");
    txt.className = "mode-card-text";
    const t = document.createElement("div");
    t.className = "mode-card-title";
    t.textContent = m.title;
    const d = document.createElement("div");
    d.className = "mode-card-desc";
    d.textContent = m.desc;
    txt.appendChild(t);
    txt.appendChild(d);
    card.appendChild(txt);

    const chev = document.createElement("span");
    chev.className = "mode-card-chev";
    chev.innerHTML = _ICONS.chevR;
    card.appendChild(chev);

    card.addEventListener("click", m.onClick);
    main.appendChild(card);
  }

  root.appendChild(main);
}

function renderLearnCard() {
  const root = document.getElementById("root");
  // MC session hides the tab bar to match the reader's focus mode.
  hideTabBar();

  if (state.learn === null) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    _fetchLearnPool();
    return;
  }

  const pool = state.learn.pool;
  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "learn-card-screen screen-in";

  // Empty-pool branch — no words to train, give the user a way back.
  if (pool.length === 0) {
    const empty = document.createElement("div");
    empty.className = "learn-empty";
    const msg = document.createElement("div");
    msg.className = "learn-empty-msg";
    msg.textContent = "Нечего учить, возвращайся позже";
    empty.appendChild(msg);
    const back = document.createElement("button");
    back.type = "button";
    back.className = "btn primary full";
    back.textContent = "Вернуться";
    back.addEventListener("click", () => navigate("/learn"));
    empty.appendChild(back);
    main.appendChild(empty);
    root.appendChild(main);
    return;
  }

  const total = pool.length;

  // Done screen — rendered once idx crosses total (or done flag
  // flips). Shared layout with M16.7 flashcards via `_buildLearnDone`
  // (see below); only the subtitle differs between the two modes.
  if (state.learn.done || state.learn.idx >= total) {
    const doneEl = _buildLearnDone(
      `${state.learn.correct} из ${total} верно`,
      state.learn.correct,
    );
    main.appendChild(doneEl);
    root.appendChild(main);
    return;
  }

  const current = pool[state.learn.idx];

  // Header row — back btn + "n / total" + spacer for symmetry.
  const header = document.createElement("div");
  header.className = "learn-header";
  const back = document.createElement("button");
  back.type = "button";
  back.className = "btn ghost sm learn-back";
  back.innerHTML = _ICONS.chevL;
  back.addEventListener("click", () => navigate("/learn"));
  header.appendChild(back);
  const counter = document.createElement("div");
  counter.className = "learn-counter";
  counter.textContent = `${state.learn.idx + 1} / ${total}`;
  header.appendChild(counter);
  const spacer = document.createElement("div");
  spacer.className = "learn-header-spacer";
  header.appendChild(spacer);
  main.appendChild(header);

  // Segmented progress bar.
  const segs = document.createElement("div");
  segs.className = "segments";
  for (let i = 0; i < total; i++) {
    const seg = document.createElement("div");
    if (i < state.learn.idx) seg.classList.add("past");
    else if (i === state.learn.idx) seg.classList.add("current");
    segs.appendChild(seg);
  }
  main.appendChild(segs);

  // Flashcard — headword + example with bolded lemma + source.
  const card = document.createElement("div");
  card.className = "learn-card";
  const prompt = document.createElement("div");
  prompt.className = "uplabel learn-card-prompt";
  prompt.textContent = "Какой перевод?";
  card.appendChild(prompt);

  const head = document.createElement("div");
  head.className = "learn-card-head";
  head.textContent = current.lemma;
  card.appendChild(head);

  if (current.example) {
    const ex = document.createElement("div");
    ex.className = "learn-card-ex";
    const text = String(current.example);
    const lemma = current.lemma || "";
    const lower = text.toLowerCase();
    const pos = lemma ? lower.indexOf(lemma.toLowerCase()) : -1;
    ex.appendChild(document.createTextNode('"'));
    if (pos >= 0 && lemma) {
      ex.appendChild(document.createTextNode(text.slice(0, pos)));
      const b = document.createElement("b");
      b.setAttribute("style", "color:var(--accent)");
      b.textContent = text.slice(pos, pos + lemma.length);
      ex.appendChild(b);
      ex.appendChild(document.createTextNode(text.slice(pos + lemma.length)));
    } else {
      ex.appendChild(document.createTextNode(text));
    }
    ex.appendChild(document.createTextNode('"'));
    card.appendChild(ex);
  }

  // Source line — book title or a dash when the word predates M16.3.
  const src = document.createElement("div");
  src.className = "learn-card-src";
  if (current.source_book && current.source_book.title) {
    src.textContent = current.source_book.title;
  } else if (current.source_book_id != null) {
    src.textContent = `Книга #${current.source_book_id}`;
  } else {
    src.textContent = "—";
  }
  card.appendChild(src);
  main.appendChild(card);

  // 2×2 MC grid.
  const grid = document.createElement("div");
  grid.className = "mc-grid";
  const options = buildOptions(current, pool);
  for (const opt of options) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mc-option";
    btn.textContent = opt;
    const isRight = opt === current.translation;
    if (state.learn.feedback) {
      if (isRight) btn.classList.add("right");
      else if (
        state.learn.feedback === "wrong" &&
        opt === state.learn.pickedWrong
      ) {
        btn.classList.add("wrong");
      }
      btn.disabled = true;
    }
    btn.addEventListener("click", () => {
      // Double-tap guard — once feedback is set the buttons are frozen
      // until the setTimeout-driven `advance` fires.
      if (!state.learn || state.learn.feedback !== null) return;
      if (isRight) {
        state.learn.feedback = "ok";
        state.learn.correct += 1;
        render();
        _postTrainingResult(current.lemma, true);
        setTimeout(_advanceLearn, 700);
      } else {
        state.learn.feedback = "wrong";
        state.learn.pickedWrong = opt;
        render();
        _postTrainingResult(current.lemma, false);
        setTimeout(_advanceLearn, 1200);
      }
    });
    grid.appendChild(btn);
  }
  main.appendChild(grid);

  // Footer — skip link + status text.
  const footer = document.createElement("div");
  footer.className = "learn-footer";
  const skip = document.createElement("span");
  skip.className = "learn-skip";
  skip.textContent = "Пропустить";
  skip.addEventListener("click", () => {
    if (!state.learn || state.learn.feedback !== null) return;
    _advanceLearn();
  });
  footer.appendChild(skip);

  const status = document.createElement("span");
  status.className = "learn-status";
  if (state.learn.feedback === "ok") status.textContent = "✓ верно";
  else if (state.learn.feedback === "wrong")
    status.textContent = "правильный вариант подсвечен";
  else status.textContent = "нажми любой вариант";
  footer.appendChild(status);
  main.appendChild(footer);

  root.appendChild(main);
}

// --- M16.7: training (flashcards) --------------------------------------
// `/learn/flash` is the flip-card session. `state.flash` carries
// {pool, idx, flipped, correct, done}. The backend contract is
// identical to the MC mode — GET /training to fill the pool, POST
// /training/result to score each answer. The difference is purely
// UI: a 3D flip card with a binary "Знал / Не знал" verdict instead
// of 4 MC options.

async function _fetchFlashPool() {
  try {
    const pool = await apiGet("/api/dictionary/training?limit=10");
    if (state.view !== "learnFlash") return;
    setState({
      flash: {
        pool: Array.isArray(pool) ? pool : [],
        idx: 0,
        flipped: false,
        correct: 0,
        done: false,
      },
    });
  } catch (err) {
    setState({ view: "error", error: err.message });
  }
}

function _advanceFlash() {
  if (state.view !== "learnFlash" || !state.flash) return;
  const total = state.flash.pool.length;
  const nextIdx = state.flash.idx + 1;
  const done = nextIdx >= total;
  state.flash.idx = nextIdx;
  state.flash.flipped = false;
  state.flash.done = done;
  render();
}

// Shared "done" screen for MC + flashcards — same ✨ / h1 / soft
// streak card / "Вернуться" layout, with only the subtitle string
// varying between modes. Returns a detached <div class="learn-done">
// ready to append.
function _buildLearnDone(subtitleText, xpCount) {
  const done = document.createElement("div");
  done.className = "learn-done";
  const emoji = document.createElement("div");
  emoji.className = "learn-done-emoji";
  emoji.textContent = "✨";
  done.appendChild(emoji);
  const h1 = document.createElement("h1");
  h1.className = "learn-done-h1";
  h1.textContent = "Готово!";
  done.appendChild(h1);
  const sub = document.createElement("div");
  sub.className = "learn-done-sub";
  sub.textContent = subtitleText;
  done.appendChild(sub);

  // Streak card — placeholder values until M16.8 wires the real data.
  const streak = document.createElement("div");
  streak.className = "learn-done-streak";
  const streakLabel = document.createElement("div");
  streakLabel.className = "learn-done-streak-label";
  streakLabel.textContent = "Серия";
  streak.appendChild(streakLabel);
  const streakVal = document.createElement("div");
  streakVal.className = "learn-done-streak-val";
  streakVal.textContent = "— дней подряд";
  streak.appendChild(streakVal);
  const xp = document.createElement("div");
  xp.className = "learn-done-xp";
  xp.textContent = `+${xpCount * 10} XP`;
  streak.appendChild(xp);
  done.appendChild(streak);

  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "btn primary full learn-done-back";
  backBtn.textContent = "Вернуться";
  backBtn.addEventListener("click", () => navigate("/learn"));
  done.appendChild(backBtn);
  return done;
}

function renderLearnFlash() {
  const root = document.getElementById("root");
  // Flash session hides the tab bar to match the MC focus mode.
  hideTabBar();

  if (state.flash === null) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    _fetchFlashPool();
    return;
  }

  const pool = state.flash.pool;
  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "learn-card-screen screen-in";

  // Empty-pool branch — no words to train, give the user a way back.
  if (pool.length === 0) {
    const empty = document.createElement("div");
    empty.className = "learn-empty";
    const msg = document.createElement("div");
    msg.className = "learn-empty-msg";
    msg.textContent = "Нечего учить, возвращайся позже";
    empty.appendChild(msg);
    const back = document.createElement("button");
    back.type = "button";
    back.className = "btn primary full";
    back.textContent = "Вернуться";
    back.addEventListener("click", () => navigate("/learn"));
    empty.appendChild(back);
    main.appendChild(empty);
    root.appendChild(main);
    return;
  }

  const total = pool.length;

  // Done screen — same shared component as MC, with a flashcards-
  // specific "Помнил N из M" subtitle.
  if (state.flash.done || state.flash.idx >= total) {
    const doneEl = _buildLearnDone(
      `Помнил ${state.flash.correct} из ${total}`,
      state.flash.correct,
    );
    main.appendChild(doneEl);
    root.appendChild(main);
    return;
  }

  const current = pool[state.flash.idx];

  // Header row — back btn + "n / total" + spacer for symmetry.
  const header = document.createElement("div");
  header.className = "learn-header";
  const back = document.createElement("button");
  back.type = "button";
  back.className = "btn ghost sm learn-back";
  back.innerHTML = _ICONS.chevL;
  back.addEventListener("click", () => navigate("/learn"));
  header.appendChild(back);
  const counter = document.createElement("div");
  counter.className = "learn-counter";
  counter.textContent = `${state.flash.idx + 1} / ${total}`;
  header.appendChild(counter);
  const spacer = document.createElement("div");
  spacer.className = "learn-header-spacer";
  header.appendChild(spacer);
  main.appendChild(header);

  // Segmented progress bar.
  const segs = document.createElement("div");
  segs.className = "segments";
  for (let i = 0; i < total; i++) {
    const seg = document.createElement("div");
    if (i < state.flash.idx) seg.classList.add("past");
    else if (i === state.flash.idx) seg.classList.add("current");
    segs.appendChild(seg);
  }
  main.appendChild(segs);

  // Flashcard with two absolutely-positioned faces and a 3D flip.
  const card = document.createElement("div");
  card.className = "flashcard" + (state.flash.flipped ? " flipped" : "");

  // Front face — EN lemma + ipa/pos.
  const front = document.createElement("div");
  front.className = "fc-front";
  const frontLbl = document.createElement("div");
  frontLbl.className = "uplabel";
  frontLbl.textContent = "Вспомни перевод";
  front.appendChild(frontLbl);
  const frontHead = document.createElement("h2");
  frontHead.className = "fc-headword";
  frontHead.textContent = current.lemma;
  front.appendChild(frontHead);
  if (current.ipa || current.pos) {
    const meta = document.createElement("div");
    meta.className = "fc-ipa";
    const bits = [];
    if (current.ipa) bits.push(current.ipa);
    if (current.pos) bits.push(current.pos);
    meta.textContent = bits.join(" · ");
    front.appendChild(meta);
  }
  card.appendChild(front);

  // Back face — RU translation + example (lemma bolded) + source.
  const backFace = document.createElement("div");
  backFace.className = "fc-back";
  const backLbl = document.createElement("div");
  backLbl.className = "uplabel";
  backLbl.textContent = "Перевод";
  backFace.appendChild(backLbl);
  const backHead = document.createElement("h2");
  backHead.className = "fc-headword";
  backHead.textContent = current.translation || "";
  backFace.appendChild(backHead);

  if (current.example) {
    const ex = document.createElement("div");
    ex.className = "fc-example";
    const text = String(current.example);
    const lemma = current.lemma || "";
    const lower = text.toLowerCase();
    const pos = lemma ? lower.indexOf(lemma.toLowerCase()) : -1;
    ex.appendChild(document.createTextNode('"'));
    if (pos >= 0 && lemma) {
      ex.appendChild(document.createTextNode(text.slice(0, pos)));
      const b = document.createElement("b");
      b.setAttribute("style", "color:var(--accent)");
      b.textContent = text.slice(pos, pos + lemma.length);
      ex.appendChild(b);
      ex.appendChild(document.createTextNode(text.slice(pos + lemma.length)));
    } else {
      ex.appendChild(document.createTextNode(text));
    }
    ex.appendChild(document.createTextNode('"'));
    backFace.appendChild(ex);
  }

  const src = document.createElement("div");
  src.className = "fc-source";
  if (current.source_book && current.source_book.title) {
    src.textContent = current.source_book.title;
  } else if (current.source_book_id != null) {
    src.textContent = `Книга #${current.source_book_id}`;
  } else {
    src.textContent = "—";
  }
  backFace.appendChild(src);
  card.appendChild(backFace);
  main.appendChild(card);

  // Actions — before flip: single "Показать перевод" primary button.
  // After flip: two-button row (ghost "Не знал" + primary "Знал").
  const actions = document.createElement("div");
  actions.className = "flash-actions";
  if (!state.flash.flipped) {
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "btn primary full";
    reveal.textContent = "Показать перевод";
    reveal.addEventListener("click", () => {
      if (!state.flash || state.flash.flipped) return;
      state.flash.flipped = true;
      render();
    });
    actions.appendChild(reveal);
  } else {
    const row = document.createElement("div");
    row.className = "flash-verdict-row";
    const no = document.createElement("button");
    no.type = "button";
    no.className = "btn ghost";
    no.style.flex = "1";
    no.textContent = "Не знал";
    no.addEventListener("click", () => {
      if (!state.flash || !state.flash.flipped) return;
      _postTrainingResult(current.lemma, false);
      _advanceFlash();
    });
    row.appendChild(no);
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "btn primary";
    yes.style.flex = "1";
    yes.textContent = "Знал";
    yes.addEventListener("click", () => {
      if (!state.flash || !state.flash.flipped) return;
      state.flash.correct += 1;
      _postTrainingResult(current.lemma, true);
      _advanceFlash();
    });
    row.appendChild(yes);
    actions.appendChild(row);
  }
  main.appendChild(actions);

  // Footer — skip link + status text (mirrors MC).
  const footer = document.createElement("div");
  footer.className = "learn-footer";
  const skip = document.createElement("span");
  skip.className = "learn-skip";
  skip.textContent = "Пропустить";
  skip.addEventListener("click", () => {
    if (!state.flash) return;
    _advanceFlash();
  });
  footer.appendChild(skip);

  const status = document.createElement("span");
  status.className = "learn-status";
  status.textContent = state.flash.flipped ? "нажми что помнишь" : "перевод скрыт";
  footer.appendChild(status);
  main.appendChild(footer);

  root.appendChild(main);
}

function renderLoading() {
  hideTabBar();
  document.getElementById("root").innerHTML = `<div class="loader">Loading…</div>`;
}

function renderError() {
  hideTabBar();
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

// --- login / signup (M11.3) ---
// Map HTTP status codes to user-friendly Russian error messages. Anything
// unexpected (network failure, 5xx, missing status) lands on the fallback.
function authErrorMessage(status, mode) {
  if (status === 401) return "Неверный email или пароль";
  if (status === 409) return "Этот email уже зарегистрирован";
  if (status === 422) return "Пароль слишком короткий (≥ 8 символов)";
  if (status === 400) return "Некорректный email";
  if (status === 429) return "Слишком много попыток, попробуйте позже";
  return mode === "signup"
    ? "Ошибка регистрации. Попробуйте ещё раз"
    : "Ошибка входа. Попробуйте ещё раз";
}

function renderLogin() {
  hideTabBar();
  const root = document.getElementById("root");
  root.innerHTML = "";

  const mode = state.authMode === "signup" ? "signup" : "login";
  const main = document.createElement("main");
  main.className = "auth-view screen-in";

  const h1 = document.createElement("h1");
  h1.id = "auth-title";
  h1.textContent = mode === "signup" ? "Регистрация" : "Войти";
  main.appendChild(h1);

  const form = document.createElement("form");
  form.id = "auth-form";

  const emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.name = "email";
  emailInput.required = true;
  emailInput.placeholder = "email";
  emailInput.autocomplete = "email";
  form.appendChild(emailInput);

  const passwordInput = document.createElement("input");
  passwordInput.type = "password";
  passwordInput.name = "password";
  passwordInput.required = true;
  passwordInput.minLength = 8;
  passwordInput.placeholder = "пароль (≥ 8)";
  passwordInput.autocomplete =
    mode === "signup" ? "new-password" : "current-password";
  form.appendChild(passwordInput);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = mode === "signup" ? "Зарегистрироваться" : "Войти";
  form.appendChild(submit);

  const errBox = document.createElement("div");
  errBox.id = "auth-error";
  errBox.className = "error";
  // XSS discipline: authError always flows through textContent only.
  if (state.authError) errBox.textContent = state.authError;
  form.appendChild(errBox);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = emailInput.value.trim();
    const password = passwordInput.value;
    submit.disabled = true;
    try {
      const path = mode === "signup" ? "/auth/signup" : "/auth/login";
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        setState({ authError: authErrorMessage(res.status, mode) });
        return;
      }
      // Success: session cookie is set. Navigate home — the library view
      // will fetch books; current-book redirection only fires on full
      // bootstraps, which is fine (the user is one click away anyway).
      state.authError = null;
      navigate("/");
    } catch (_err) {
      setState({ authError: authErrorMessage(0, mode) });
    } finally {
      submit.disabled = false;
    }
  });
  main.appendChild(form);

  const switchBtn = document.createElement("button");
  switchBtn.id = "auth-switch";
  switchBtn.type = "button";
  switchBtn.className = "auth-switch";
  switchBtn.textContent =
    mode === "signup" ? "Уже есть аккаунт? Войти" : "Зарегистрироваться";
  switchBtn.addEventListener("click", () => {
    setState({
      authMode: mode === "signup" ? "login" : "signup",
      authError: null,
    });
  });
  main.appendChild(switchBtn);

  root.appendChild(main);
}

// --- inline translation (M4.2, rewritten M19.1 for per-instance context) ---

// M19.1: every `.word` span gets its own translation request with ±1
// sentence of surrounding context. Identical (lemma, prev, sent, next)
// tuples are deduplicated client-side via `_translationInflight` so two
// spans in the same sentence collapse into a single HTTP round-trip,
// and the server's prompt-hash cache makes a second page render free.
const _translationInflight = new Map();
const _PRELOAD_CONCURRENCY = 4;

function getSentenceFor(span) {
  const sentEl = span.closest("[data-sentence-id]");
  if (sentEl) return sentEl.textContent;
  const page = span.closest(".page-body");
  return page ? page.textContent.slice(0, 300) : "";
}

function contextFor(span) {
  const sentEl = span.closest("[data-sentence-id]");
  if (!sentEl) {
    return { prev: "", sentence: getSentenceFor(span), next: "" };
  }
  const sentence = sentEl.textContent;
  const pageBody = sentEl.closest(".page-body");
  let prev = "";
  let next = "";
  if (pageBody) {
    const sentences = Array.from(pageBody.querySelectorAll("[data-sentence-id]"));
    const idx = sentences.indexOf(sentEl);
    if (idx > 0) {
      prev = sentences[idx - 1].textContent;
    } else {
      // At the top of a page, look one page up for the last sentence so
      // the context stays continuous across a page seam. Reader layout:
      // `.page > .page-body`; neighbouring pages are siblings under the
      // book container.
      const pageEl = pageBody.closest(".page");
      const prevPageBody = pageEl?.previousElementSibling?.querySelector?.(".page-body");
      const prevSents = prevPageBody ? prevPageBody.querySelectorAll("[data-sentence-id]") : null;
      if (prevSents && prevSents.length) {
        prev = prevSents[prevSents.length - 1].textContent;
      }
    }
    if (idx >= 0 && idx < sentences.length - 1) {
      next = sentences[idx + 1].textContent;
    } else {
      const pageEl = pageBody.closest(".page");
      const nextPageBody = pageEl?.nextElementSibling?.querySelector?.(".page-body");
      const nextSents = nextPageBody ? nextPageBody.querySelectorAll("[data-sentence-id]") : null;
      if (nextSents && nextSents.length) {
        next = nextSents[0].textContent;
      }
    }
  }
  return { prev, sentence, next };
}

function translationKey(lemma, ctx) {
  return `${lemma}||${ctx.prev}||${ctx.sentence}||${ctx.next}`;
}

// Fetch (or reuse an in-flight) translation for a single span. The
// response is shared between concurrent callers via the inflight map so
// every distinct prompt lands in exactly one POST. The map entry is
// evicted 30 s after resolution to keep memory bounded across long
// reading sessions.
// Returns ``{ ru, source }`` where source is "dict" | "cache" | "llm"
// | "mock". Same-key concurrent callers share one HTTP round-trip via
// ``_translationInflight``.
async function fetchTranslationFor(span) {
  const lemma = span.dataset.lemma;
  const unitText = (span.dataset.originalText || span.textContent).trim();
  const ctx = contextFor(span);
  const key = translationKey(lemma, ctx);
  if (_translationInflight.has(key)) {
    return _translationInflight.get(key);
  }
  const bookId = state.currentBook?.bookId ?? null;
  const promise = apiPost("/api/translate", {
    unit_text: unitText,
    sentence: ctx.sentence,
    prev_sentence: ctx.prev,
    next_sentence: ctx.next,
    lemma,
    source_book_id: bookId,
  }).then((r) => ({ ru: r.ru, source: r.source || "llm" }));
  _translationInflight.set(key, promise);
  promise.finally(() => {
    setTimeout(() => _translationInflight.delete(key), 30_000);
  });
  return promise;
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

// M19.4: human-readable label for /api/translate's `source` field on
// manual word clicks. Preload never toasts, so this is used only by
// translateAndReplace — it answers "где мы взяли этот перевод?".
function _translationSourceToast(source, firstForLemma) {
  if (source === "dict") return "Из словаря";
  if (source === "cache") {
    return firstForLemma ? "В словарь из кэша" : "Из кэша";
  }
  if (source === "mock") {
    return firstForLemma ? "В словарь (mock)" : "Mock";
  }
  // "llm" and any unexpected value fall through here.
  return firstForLemma ? "В словарь из LLM" : "Из LLM";
}

async function translateAndReplace(span) {
  if (span.classList.contains("loading")) return;
  if (span.classList.contains("translated")) return;
  const lemma = span.dataset.lemma;
  const pairId = span.dataset.pairId;

  span.classList.add("loading");

  let ru;
  let source = "llm";
  try {
    const result = await fetchTranslationFor(span);
    ru = result.ru;
    source = result.source;
  } catch (err) {
    span.classList.remove("loading");
    toast("Не удалось перевести");
    return;
  }

  const firstForLemma = !(lemma in state.userDict);

  withScrollAnchor(() => {
    // Track the lemma for the prefetch sweep, but only replace THIS
    // span (and its paired split-PV half, which lives in the same
    // sentence and shares context by construction). Other instances
    // will be translated individually by the prefetch scan.
    state.userDict[lemma] = ru;
    replaceWithTranslation(span, ru);
    if (pairId != null) {
      const pairSel = `.word[data-pair-id="${CSS.escape(pairId)}"]`;
      document.querySelectorAll(pairSel).forEach((w) => {
        if (!w.classList.contains("translated")) replaceWithTranslation(w, ru);
      });
    }
    span.classList.add("highlighted");
    setTimeout(() => span.classList.remove("highlighted"), 800);
  });

  // M19.4: tell the user exactly where the translation came from —
  // "Из словаря" / "Из кэша" / "Из LLM" (with "В словарь …" prefix
  // for the first click of each lemma). Preload path stays silent.
  toast(_translationSourceToast(source, firstForLemma));

  if (firstForLemma) {
    // Kick off a sweep across the rest of the reader so every already-
    // rendered instance of this lemma gets its own context-specific
    // translation. Runs in the background, bounded by _PRELOAD_CONCURRENCY.
    const main = document.getElementById("root");
    if (main) preloadPageTranslations(main).catch(() => {});
  }
}

// M19.1: iterate every `.word` span under ``scopeEl`` and trigger a
// per-instance translation for those whose lemma is already in
// ``state.userDict``. Each span gets its own 3-sentence context, so
// the LLM can disambiguate senses between occurrences. Runs with a
// small concurrency cap so scrolling into a dense page doesn't flood
// the server or the rate-limiter. Idempotent: already-translated /
// in-flight spans are skipped.
async function preloadPageTranslations(scopeEl) {
  if (!scopeEl) return;
  const lemmas = new Set(Object.keys(state.userDict));
  if (lemmas.size === 0) return;
  const tasks = [];
  scopeEl.querySelectorAll(".word").forEach((span) => {
    if (span.classList.contains("translated")) return;
    if (span.classList.contains("loading")) return;
    if (!lemmas.has(span.dataset.lemma)) return;
    tasks.push(span);
  });
  if (tasks.length === 0) return;
  let cursor = 0;
  const worker = async () => {
    while (cursor < tasks.length) {
      const span = tasks[cursor++];
      // A concurrent translateAndReplace may have handled this span in
      // the gap between task collection and dispatch — re-check.
      if (span.classList.contains("translated")) continue;
      if (span.classList.contains("loading")) continue;
      span.classList.add("loading");
      try {
        const { ru } = await fetchTranslationFor(span);
        withScrollAnchor(() => {
          replaceWithTranslation(span, ru);
          const pairId = span.dataset.pairId;
          if (pairId != null) {
            const pairSel = `.word[data-pair-id="${CSS.escape(pairId)}"]`;
            document.querySelectorAll(pairSel).forEach((w) => {
              if (!w.classList.contains("translated")) {
                replaceWithTranslation(w, ru);
              }
            });
          }
        });
      } catch (_err) {
        span.classList.remove("loading");
      }
    }
  };
  const workers = Array.from(
    { length: Math.min(_PRELOAD_CONCURRENCY, tasks.length) },
    worker,
  );
  await Promise.all(workers);
  // M19.3: preload mutates DOM after loadBelow/loadAbove did their
  // one-shot ``_sentinelStillHot`` check. IntersectionObserver only fires
  // on boundary *crossings*, so if the preload shifts layout such that
  // the bottom sentinel is now in the 400 px hot zone but wasn't at
  // insert time, pagination would silently stall. Re-drive both loaders
  // once after the preload settles — the idempotent guards inside them
  // make it cheap when nothing is actually due.
  if (state.view === "reader") {
    if (_sentinelStillHot(".sentinel-bottom")) loadBelow();
    if (_sentinelStillHot(".sentinel-top")) loadAbove();
  }
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

// --- M16.2: canonical shared components (sheet + scrim + tabbar) ---
// The #sheet / #scrim / #toast / #tabbar shells live in index.html. We
// lazy-mount them here as a fallback so unit tests (or any downstream
// markup drift) still get a working component instead of throwing.
function _ensureSheetShells() {
  let scrim = document.getElementById("scrim");
  if (!scrim) {
    scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.id = "scrim";
    document.body.appendChild(scrim);
  }
  let sheet = document.getElementById("sheet");
  if (!sheet) {
    sheet = document.createElement("div");
    sheet.className = "sheet";
    sheet.id = "sheet";
    document.body.appendChild(sheet);
  }
  if (!scrim._mgmtBound) {
    scrim.addEventListener("click", closeSheet);
    scrim._mgmtBound = true;
  }
  return { scrim, sheet };
}

// Open a bottom sheet with arbitrary content. The caller owns what goes
// inside; this function only manages the container, the handle pill, and
// the show/hide classes. Double-rAF so the browser commits the initial
// (untransformed) style before the transition target class lands.
function openSheet(contentEl) {
  const { scrim, sheet } = _ensureSheetShells();
  sheet.innerHTML = "";
  const handle = document.createElement("div");
  handle.className = "handle";
  sheet.appendChild(handle);
  if (contentEl) sheet.appendChild(contentEl);
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      scrim.classList.add("show");
      sheet.classList.add("show");
    }),
  );
}

function closeSheet() {
  const scrim = document.getElementById("scrim");
  const sheet = document.getElementById("sheet");
  if (scrim) scrim.classList.remove("show");
  if (sheet) sheet.classList.remove("show");
  // Legacy M4.2 ad-hoc sheets (if any still-in-flight caller kept the old
  // `.sheet-backdrop` path around). Harmless no-op under the canonical path.
  document.querySelectorAll(".sheet-backdrop").forEach((n) => n.remove());
}

// Press Escape → close the canonical sheet. Installed once at module load
// so we don't leak per-open listeners. Guarded on the sheet actually being
// open so Esc inside an input field doesn't trip it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const sheet = document.getElementById("sheet");
  if (sheet && sheet.classList.contains("show")) closeSheet();
});

// M16.2: canonical toast. 1.6 s auto-hide. Uses the shared #toast shell
// (lazy-mounted if missing) and a module-level timer handle so back-to-
// back calls reset the countdown instead of stacking.
let _toastTimer = null;
function showToast(msg) {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.className = "toast";
    t.id = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    t.classList.remove("show");
    _toastTimer = null;
  }, 1600);
}

// Back-compat alias — every existing M4.2 / M9.2 callsite still says
// `toast("...")`. Preserving the name avoids a coordinated rename across
// uploadBook / translateAndReplace / card-menu / bottom sheet.
const toast = showToast;

// M16.2: tab bar. Four tabs, icon + label + "on" dot on the active one.
// Caller supplies the active id and a click handler — the bar itself has
// no opinion about routing, so M16.4/.5/.6 can wire screens as they land.
const _TABS = [
  { id: "lib", label: "Мои книги", icon: _ICONS.books },
  { id: "cat", label: "Каталог", icon: _ICONS.compass },
  { id: "dict", label: "Словарь", icon: _ICONS.dict },
  { id: "learn", label: "Учить", icon: _ICONS.brain },
];

// M18.4: Settings sheet — for now just the Telegram link button.
// Keeps the flow self-contained: a POST mints a one-time token, we hand
// the user a t.me deep link, then poll until the webhook side declares
// the link done. On the keep-TG merge path the poller picks up a
// ``session_reissued`` flag and the caller re-runs bootstrap to re-bind
// the UI to the surviving user row.
let _linkPollTimer = null;

function openSettingsSheet() {
  const content = document.createElement("div");
  content.className = "settings-sheet";

  const title = document.createElement("h2");
  title.textContent = "Настройки";
  content.appendChild(title);

  const emailRow = document.createElement("div");
  emailRow.className = "settings-row";
  emailRow.textContent = "Email: " + (state.userEmail || "—");
  content.appendChild(emailRow);

  const tgRow = document.createElement("div");
  tgRow.className = "settings-row";
  const isTelegramLinked = !!(state.userEmail && !state.userEmail.startsWith("tg-"));
  // The email heuristic is rough — a real "is linked" flag would come
  // from /auth/me. Good enough for the MVP; a follow-up can surface the
  // telegram_id explicitly.
  tgRow.textContent = "Telegram: " + (isTelegramLinked ? "✓" : "не привязан");
  content.appendChild(tgRow);

  const linkBtn = document.createElement("button");
  linkBtn.type = "button";
  linkBtn.className = "btn primary";
  linkBtn.textContent = "Привязать Telegram";
  linkBtn.addEventListener("click", () => _startTelegramLink(linkBtn, statusLine));
  content.appendChild(linkBtn);

  const statusLine = document.createElement("div");
  statusLine.className = "settings-status";
  statusLine.textContent = "";
  content.appendChild(statusLine);

  openSheet(content);
}

async function _startTelegramLink(linkBtn, statusLine) {
  linkBtn.disabled = true;
  statusLine.textContent = "Генерирую ссылку…";
  let body;
  try {
    const res = await fetch("/auth/link/telegram/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
    });
    if (!res.ok) {
      linkBtn.disabled = false;
      statusLine.textContent =
        res.status === 503 ? "Telegram-бот не настроен" : "Не получилось, попробуй ещё раз";
      return;
    }
    body = await res.json();
  } catch (_e) {
    linkBtn.disabled = false;
    statusLine.textContent = "Нет соединения";
    return;
  }
  const { token, deep_link } = body || {};
  if (!token || !deep_link) {
    linkBtn.disabled = false;
    statusLine.textContent = "Не получилось, попробуй ещё раз";
    return;
  }
  statusLine.textContent = "Открываю Telegram…";
  // If we're already inside a Mini App, Telegram's SDK has a dedicated
  // API to hop to a bot chat without leaving the WebView.
  const wa = window.Telegram && window.Telegram.WebApp;
  if (wa && typeof wa.openTelegramLink === "function") {
    try { wa.openTelegramLink(deep_link); } catch (_e) {
      window.open(deep_link, "_blank");
    }
  } else {
    window.open(deep_link, "_blank");
  }
  _pollLinkStatus(token, statusLine, linkBtn);
}

function _pollLinkStatus(token, statusLine, linkBtn) {
  if (_linkPollTimer) {
    clearInterval(_linkPollTimer);
    _linkPollTimer = null;
  }
  statusLine.textContent = "Жду подтверждение в Telegram…";
  const started = Date.now();
  _linkPollTimer = setInterval(async () => {
    // 10 min cap — matches the token TTL on the server.
    if (Date.now() - started > 10 * 60 * 1000) {
      clearInterval(_linkPollTimer);
      _linkPollTimer = null;
      statusLine.textContent = "Время вышло, попробуй ещё раз";
      linkBtn.disabled = false;
      return;
    }
    let body;
    try {
      const res = await fetch(
        "/auth/link/telegram/status?token=" + encodeURIComponent(token),
        { credentials: "include" },
      );
      body = await res.json();
    } catch (_e) {
      return; // transient — try again next tick
    }
    if (body.status === "pending" || body.status === "conflict_waiting") {
      statusLine.textContent =
        body.status === "conflict_waiting"
          ? "Подтверди выбор в Telegram…"
          : "Жду подтверждение в Telegram…";
      return;
    }
    clearInterval(_linkPollTimer);
    _linkPollTimer = null;
    if (body.status === "done") {
      statusLine.textContent = "Готово!";
      showToast("Telegram привязан");
      closeSheet();
      // Re-bind the UI to whichever row survived the merge.
      bootstrap();
    } else if (body.status === "expired") {
      statusLine.textContent = "Ссылка просрочена";
      linkBtn.disabled = false;
    } else {
      statusLine.textContent = "Не получилось";
      linkBtn.disabled = false;
    }
  }, 2000);
}

// Export for tests/devtools.
window.openSettingsSheet = openSettingsSheet;

function renderTabBar(activeId, onTabClick) {
  let bar = document.getElementById("tabbar");
  if (!bar) {
    bar = document.createElement("nav");
    bar.className = "tabbar";
    bar.id = "tabbar";
    bar.setAttribute("aria-label", "Tabs");
    document.body.appendChild(bar);
  }
  bar.innerHTML = "";
  for (const t of _TABS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tab" + (activeId === t.id ? " on" : "");
    b.dataset.tabId = t.id;
    // Icon is trusted static SVG → innerHTML; label text is a literal
    // constant → still goes through textContent on its own <span> so a
    // future i18n table can't leak markup.
    const iconSpan = document.createElement("span");
    iconSpan.className = "tab-icon";
    iconSpan.innerHTML = t.icon;
    b.appendChild(iconSpan);
    const labelSpan = document.createElement("span");
    labelSpan.textContent = t.label;
    b.appendChild(labelSpan);
    if (activeId === t.id) {
      const dot = document.createElement("span");
      dot.className = "tab-dot";
      b.appendChild(dot);
    }
    b.addEventListener("click", () => {
      if (typeof onTabClick === "function") onTabClick(t.id);
    });
    bar.appendChild(b);
  }
}

function hideTabBar() {
  const bar = document.getElementById("tabbar");
  if (bar) bar.classList.add("hidden");
  document.body.classList.remove("with-tabbar");
}

function showTabBar() {
  const bar = document.getElementById("tabbar");
  if (bar) bar.classList.remove("hidden");
  document.body.classList.add("with-tabbar");
}

// --- M4.2 word-sheet, now driven by the canonical openSheet shell. ---
function openWordSheet(span) {
  const lemma = span.dataset.lemma;
  const original = span.dataset.originalText ?? span.textContent;
  const ruText = span.textContent;
  const sentenceText = getSentenceFor(span);

  const content = document.createElement("div");
  content.setAttribute("role", "dialog");

  const headword = document.createElement("div");
  headword.className = "sheet-headword";
  headword.textContent = original;
  content.appendChild(headword);

  const meta = document.createElement("div");
  meta.className = "sheet-meta";
  meta.textContent = "— · —";
  content.appendChild(meta);

  const tCard = document.createElement("div");
  tCard.className = "sheet-card sheet-translation";
  tCard.textContent = ruText;
  content.appendChild(tCard);

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
  content.appendChild(fromBook);

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
    showToast("Вернули оригинал");
  });
  actions.appendChild(primary);
  actions.appendChild(ghost);
  content.appendChild(actions);

  openSheet(content);
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

// Legacy ad-hoc `toast()` implementation removed — the canonical
// `showToast()` (M16.2) handles the #toast shell, and `const toast =
// showToast` at module top keeps the old name as a back-compat alias.
// Redefining it here as a function caused a SyntaxError under ES-module
// strict mode and killed the SPA at load time.

// --- render ---
function render() {
  switch (state.view) {
    case "library": return renderLibrary();
    case "reader": return renderReader();
    case "login": return renderLogin();
    case "dictionary": return renderDictionary();
    case "catalog": return renderCatalog();
    case "learnHome": return renderLearnHome();
    case "learnCard": return renderLearnCard();
    case "learnFlash": return renderLearnFlash();
    case "loading": return renderLoading();
    case "error": return renderError();
    default: return renderError();
  }
}

// --- M16.1: theme API --------------------------------------------------
// Named helpers (vs. the old inline IIFE) so later tasks — the settings
// sheet from M9.3 in particular — can flip the theme without duplicating
// the localStorage / prefers-color-scheme handshake. The canonical
// storage key is `en-reader.theme`; if the legacy pre-M16.1 `theme` key
// is present we migrate it once and then remove it so the two never
// drift out of sync.
const THEME_KEY = "en-reader.theme";

function getTheme() {
  const v = localStorage.getItem(THEME_KEY);
  return v === "dark" || v === "light" ? v : null;
}

function currentTheme() {
  // One-shot migration from the M3.3 key (`localStorage.theme`).
  const saved = getTheme();
  if (saved) return saved;
  const legacy = localStorage.getItem("theme");
  if (legacy === "dark" || legacy === "light") {
    localStorage.setItem(THEME_KEY, legacy);
    localStorage.removeItem("theme");
    return legacy;
  }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setTheme(t) {
  const theme = t === "dark" ? "dark" : "light";
  document.documentElement.classList.toggle("dark", theme === "dark");
  try { localStorage.setItem(THEME_KEY, theme); } catch (_e) { /* quota/private-mode */ }
}

// Expose on window for the future settings sheet (and for tests/devtools).
window.setTheme = setTheme;
window.currentTheme = currentTheme;
window.THEME_KEY = THEME_KEY;

// --- bootstrap ---
setTheme(currentTheme());
window.addEventListener("popstate", onPopState);

// M11.3 + M10.5: on boot we probe /auth/me first to distinguish
// 200 (authenticated — continue with the current-book redirect),
// 401 (no session — redirect to /login unless we're already there),
// and network/5xx (show a "Нет соединения" screen rather than loop the
// user through /login on every backend outage). Direct landings on
// /login or /signup still hit /auth/me but bypass the redirect, so a
// signed-in visitor navigating there manually gets bounced home instead
// of being shown the auth form they don't need.
// M18.1: tell the Telegram WebView we've rendered + go full-height. Safe
// no-op outside the WebView because `window.Telegram` is undefined there.
function _telegramHandshake() {
  const wa = window.Telegram && window.Telegram.WebApp;
  if (!wa) return null;
  try { wa.ready(); } catch (_e) {}
  try { wa.expand(); } catch (_e) {}
  return wa;
}

// M18.2: fire-and-forget breadcrumbs so we can reconstruct what the
// Telegram WebView saw from server-side journalctl. Mobile WebView has
// no accessible DevTools; this is the only way to diagnose a silent
// auto-login failure in production.
function _tgDiag(event, detail) {
  try {
    fetch("/tg/diag", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, detail: String(detail || "").slice(0, 500) }),
      keepalive: true,
    }).catch(() => {});
  } catch (_e) {}
}

// M18.1: if we're opened inside Telegram and have valid initData, trade
// it for a session cookie before the regular /auth/me probe fires. Any
// failure (missing initData, 401 from the backend) falls through to the
// normal flow — a user who opens the domain in a browser still lands on
// the login/signup screen.
async function _telegramAutoLogin() {
  const hasNs = !!window.Telegram;
  const wa = _telegramHandshake();
  if (!wa) {
    _tgDiag("sdk_missing", "hasNs=" + hasNs + " ua=" + navigator.userAgent.slice(0, 60));
    return false;
  }
  const initLen = (wa.initData || "").length;
  const platform = wa.platform || "?";
  const version = wa.version || "?";
  if (!wa.initData) {
    _tgDiag("init_empty", "platform=" + platform + " version=" + version);
    return false;
  }
  _tgDiag("init_start", "len=" + initLen + " platform=" + platform + " version=" + version);
  try {
    const res = await fetch("/auth/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: wa.initData }),
      credentials: "include",
    });
    _tgDiag("init_done", "status=" + res.status);
    return res.ok;
  } catch (e) {
    _tgDiag("init_throw", String(e).slice(0, 200));
    return false;
  }
}

async function bootstrap() {
  setState({ view: "loading" });

  const path = location.pathname;
  const onAuthScreen = path === "/login" || path === "/signup";

  // Try Telegram first — a successful exchange drops a session cookie so
  // the following /auth/me comes back 200 and skips the login screen.
  await _telegramAutoLogin();

  let authStatus = 0;
  let networkError = false;
  try {
    // credentials:"include" is belt-and-suspenders for Telegram WebView
    // where default "same-origin" has occasionally been observed to drop
    // the session cookie on back/forward restores.
    const res = await fetch("/auth/me", { credentials: "include" });
    authStatus = res.status;
    // M18.4: stash the email so the Settings sheet can show the user
    // which account they're logged into without a second fetch.
    if (res.ok) {
      try {
        const body = await res.json();
        state.userEmail = body.email || null;
      } catch (_e) { /* body parse failure is non-fatal */ }
    }
  } catch (_e) {
    networkError = true;
  }

  if (networkError || authStatus >= 500) {
    setState({ view: "error", error: "Нет соединения" });
    return;
  }
  if (authStatus === 401) {
    if (!onAuthScreen) {
      navigate("/login");
      return;
    }
    // M17.3: direct-land on /signup opens the signup form, /login stays login.
    const parsed = parseRoute(path);
    const patch = { route: path, view: "login" };
    if (parsed.authMode) patch.authMode = parsed.authMode;
    setState(patch);
    return;
  }
  if (authStatus !== 200) {
    setState({ view: "error", error: "Нет соединения" });
    return;
  }
  if (onAuthScreen) {
    navigate("/");
    return;
  }

  // Authenticated: consult the current-book pointer so re-opening the
  // tab lands directly in the reader. Fetch failures are swallowed —
  // we just fall through to the library.
  let bookId = null;
  try {
    const data = await apiGet("/api/me/current-book");
    if (data && data.book_id != null) bookId = data.book_id;
  } catch (_e) { /* no pointer */ }
  if (bookId && location.pathname === "/") {
    navigate(`/books/${bookId}`);
    return;
  }
  const finalPath = location.pathname;
  const { view } = parseRoute(finalPath);
  const patch = { route: finalPath, view };
  if (view === "error") patch.error = `Unknown route: ${finalPath}`;
  setState(patch);
}
bootstrap();
