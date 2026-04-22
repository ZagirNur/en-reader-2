// Minimal wrapper around fetch that injects Bearer token and server base URL
// from chrome.storage.local. Used by background/service_worker.js, the popup,
// the options page, and (indirectly, via message passing) content scripts.
//
// The base URL is user-configurable in the options page. Content scripts
// cannot read chrome.storage directly across origins in all cases, so the
// service worker brokers all API calls via chrome.runtime.sendMessage.

const DEFAULT_BASE_URL = "https://enreader.zagirnur.dev";

export async function getConfig() {
  const { baseUrl, token } = await chrome.storage.local.get(["baseUrl", "token"]);
  return {
    baseUrl: (baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, ""),
    token: token || null,
  };
}

export async function setConfig({ baseUrl, token }) {
  const patch = {};
  if (baseUrl !== undefined) patch.baseUrl = baseUrl;
  if (token !== undefined) patch.token = token;
  await chrome.storage.local.set(patch);
}

export class ApiError extends Error {
  constructor(message, { status, body } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = "GET", body, headers = {}, signal } = {}) {
  const { baseUrl, token } = await getConfig();
  if (!token) {
    throw new ApiError("not authenticated", { status: 401 });
  }
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      "Authorization": `Bearer ${token}`,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    data = await res.json().catch(() => null);
  } else {
    data = await res.text().catch(() => null);
  }
  if (!res.ok) {
    const detail = (data && typeof data === "object" && data.detail) || res.statusText;
    throw new ApiError(`${method} ${path} → ${res.status}: ${detail}`, { status: res.status, body: data });
  }
  return data;
}

export const api = {
  // Auth: no token required
  async login({ email, password, baseUrl }) {
    const url = `${(baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, "")}/auth/token`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "password", email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new ApiError(data.detail || `login failed (${res.status})`, { status: res.status, body: data });
    }
    return data; // { access_token, refresh_token, expires_at }
  },

  async me() {
    return request("/auth/me");
  },

  async importArticle({ url, title, text, author }) {
    return request("/api/articles/import", {
      method: "POST",
      body: { url, title, author: author || null, text },
    });
  },

  async listArticles() {
    return request("/api/articles");
  },

  async deleteArticle(id) {
    return request(`/api/articles/${id}`, { method: "DELETE" });
  },

  async translate({ unitText, lemma, sentence, prevSentence, nextSentence, sourceBookId, mode = "translate" }) {
    return request("/api/translate", {
      method: "POST",
      body: {
        unit_text: unitText,
        lemma,
        sentence,
        prev_sentence: prevSentence ?? null,
        next_sentence: nextSentence ?? null,
        source_book_id: sourceBookId,
        mode,
      },
    });
  },
};

export { DEFAULT_BASE_URL };
