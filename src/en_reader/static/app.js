// en-reader SPA (M3.3): state + router + reader render (tokens → translatable spans).
// XSS discipline: token text goes via document.createTextNode / textContent only.

// --- state ---
const state = { view: "loading", error: null, route: "/", demo: null };

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

// --- views ---
function renderLibrary() {
  const root = document.getElementById("root");
  root.innerHTML = `<h1>Library</h1><button id="open-demo">Open demo</button>`;
  document.getElementById("open-demo").onclick = () => navigate("/reader");
}

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

  const appendGap = (gap) => {
    if (!gap) return;
    // split on double-newline to start a new <p>; single \n collapses.
    const parts = gap.split(/\n\n+/);
    for (let k = 0; k < parts.length; k++) {
      if (parts[k]) para.appendChild(document.createTextNode(parts[k]));
      if (k < parts.length - 1) {
        para = document.createElement("p");
        body.appendChild(para);
      }
    }
  };

  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    const unit = unitByToken.get(i);

    if (unit && unit.token_ids[0] === i) {
      // MWE / phrasal / split_phrasal / word unit: one span spanning all unit tokens.
      const span = document.createElement("span");
      span.className = "word";
      span.dataset.unitId = String(unit.id);
      span.dataset.lemma = unit.lemma;
      span.dataset.kind = unit.kind;
      if (unit.pair_id) span.dataset.pairId = String(unit.pair_id);

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
      para.appendChild(span);

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
      para.appendChild(span);
    } else if (!unit) {
      para.appendChild(document.createTextNode(tok.text));
    } else {
      // Token inside a unit but not the first — already emitted.
    }

    const nextTok = tokens[i + 1];
    const gap = nextTok
      ? text.slice(tok.idx_in_text + tok.text.length, nextTok.idx_in_text)
      : text.slice(tok.idx_in_text + tok.text.length);
    appendGap(gap);
    i += 1;
  }

  return section;
}

function renderReader() {
  const root = document.getElementById("root");
  if (state.demo === null) {
    root.innerHTML = `<div class="loader">Loading…</div>`;
    apiGet("/api/demo")
      .then((data) => {
        if (state.view === "reader") setState({ demo: data });
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

  for (const page of state.demo.pages) {
    main.appendChild(buildPageSection(page));
  }

  const backBottom = document.createElement("button");
  backBottom.id = "back-bottom";
  backBottom.textContent = "← Back";
  backBottom.onclick = () => navigate("/");
  main.appendChild(backBottom);

  main.addEventListener("click", (e) => {
    const span = e.target.closest(".word");
    if (!span) return;
    console.log("clicked", span.dataset.unitId, span.dataset.lemma, span.textContent);
  });

  root.appendChild(main);
}

function renderLoading() {
  document.getElementById("root").innerHTML = `<div class="loader">Loading…</div>`;
}

function renderError() {
  const root = document.getElementById("root");
  const msg = state.error ?? "Unknown error";
  root.innerHTML = `<div class="error">${msg}</div><p><a id="go-home" href="/">Go home</a></p>`;
  const link = document.getElementById("go-home");
  link.onclick = (ev) => {
    ev.preventDefault();
    navigate("/");
  };
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
