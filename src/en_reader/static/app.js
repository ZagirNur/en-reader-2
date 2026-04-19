// en-reader SPA skeleton (M3.2): state container + manual router + view dispatch.
// Mutation discipline: only setState / render / navigate touch #root.innerHTML.

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
  root.innerHTML =
    `<h1>Reader</h1><div>loaded ${state.demo.pages.length} pages</div>` +
    `<button id="back">← Back</button>`;
  document.getElementById("back").onclick = () => navigate("/");
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
window.addEventListener("popstate", onPopState);
{
  const path = location.pathname;
  const { view } = parseRoute(path);
  const patch = { route: path, view };
  if (view === "error") patch.error = `Unknown route: ${path}`;
  setState(patch);
}
