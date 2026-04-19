// en-reader SPA (M3.3 + M4.2): state + router + reader render + inline translation.
// XSS discipline: any text from API responses goes via document.createTextNode / textContent only.

// --- state ---
const state = {
  view: "loading",
  error: null,
  route: "/",
  demo: null,
  userDict: {},
};

function setState(patch) {
  Object.assign(state, patch);
  render();
}

// --- router ---
function parseRoute(path) {
  if (path === "/") return { view: "library" };
  if (path === "/reader") return { view: "reader" };
  return { view: "error" };
}

function navigate(path) {
  history.pushState({}, "", path);
  const { view } = parseRoute(path);
  const patch = { route: path, view };
  if (view === "error") patch.error = `Unknown route: ${path}`;
  setState(patch);
}

function onPopState() {
  const path = location.pathname;
  const { view } = parseRoute(path);
  const patch = { route: path, view };
  if (view === "error") patch.error = `Unknown route: ${path}`;
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

// --- views ---
function renderLibrary() {
  const root = document.getElementById("root");
  root.innerHTML = `<h1>Library</h1><button id="open-demo">Open demo</button>`;
  document.getElementById("open-demo").onclick = () => navigate("/reader");
}

// --- reader render ---
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

  // token local index → unit object
  const unitByToken = new Map();
  for (const unit of units) {
    for (const tid of unit.token_ids) unitByToken.set(tid, unit);
  }

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

  // Literal gap text; \n\n+ starts a new <p>; sentence wrapper continues.
  const appendGap = (gap) => {
    if (!gap) return;
    const parts = gap.split(/\n\n+/);
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
      const gap = nextTok
        ? text.slice(lastTok.idx_in_text + lastTok.text.length, nextTok.idx_in_text)
        : text.slice(lastTok.idx_in_text + lastTok.text.length);
      appendGap(gap);
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
    const gap = nextTok
      ? text.slice(tok.idx_in_text + tok.text.length, nextTok.idx_in_text)
      : text.slice(tok.idx_in_text + tok.text.length);
    appendGap(gap);
    i += 1;
  }

  return section;
}

function applyAutoTranslation(pageSection, unitId, ru) {
  const escaped = CSS.escape(String(unitId));
  pageSection.querySelectorAll(`.word[data-unit-id="${escaped}"]`).forEach((span) => {
    replaceWithTranslation(span, ru);
  });
}

function renderReader() {
  const root = document.getElementById("root");
  if (state.demo === null) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    apiGet("/api/demo")
      .then((data) => {
        if (state.view === "reader") {
          // Seed state.userDict from server, merging over any local state so
          // an in-flight click isn't clobbered by a stale server payload.
          if (data && data.user_dict) {
            state.userDict = { ...data.user_dict, ...state.userDict };
          }
          setState({ demo: data });
        }
      })
      .catch((err) => setState({ view: "error", error: err.message }));
    return;
  }

  root.innerHTML = "";
  const main = document.createElement("main");
  main.className = "reader size-m reader-root";

  const backTop = document.createElement("button");
  backTop.id = "back";
  backTop.textContent = "← Back";
  backTop.onclick = () => navigate("/");
  main.appendChild(backTop);

  const pageSections = [];
  for (const page of state.demo.pages) {
    const section = buildPageSection(page);
    pageSections.push({ page, section });
    main.appendChild(section);
  }

  const backBottom = document.createElement("button");
  backBottom.id = "back-bottom";
  backBottom.textContent = "← Back";
  backBottom.onclick = () => navigate("/");
  main.appendChild(backBottom);

  main.addEventListener("click", onWordTap);

  root.appendChild(main);

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
