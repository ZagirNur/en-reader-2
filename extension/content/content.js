// Main content script: extracts article, sends to backend, injects token
// spans directly into the live DOM, wires up click-to-translate.
//
// Runs once per tab — activation is guarded by a global flag so repeated
// clicks on the extension icon are idempotent.

(function () {
  if (window.__enrActivated) {
    __enrToast("Already active on this page", "info");
    return;
  }
  window.__enrActivated = true;

  const dm = window.__enrDomMap;
  if (!dm) {
    __enrToast("dom_map.js didn't load", "err");
    return;
  }

  // --- helpers -----------------------------------------------------------

  function sendMessage(msg) {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(msg, (response) => {
          const err = chrome.runtime.lastError;
          if (err) reject(new Error(err.message));
          else resolve(response);
        });
      } catch (e) {
        reject(e);
      }
    });
  }

  function pageTitle() {
    const og = document.querySelector('meta[property="og:title"]')?.content;
    if (og && og.trim()) return og.trim().slice(0, 500);
    const h1 = document.querySelector("article h1, main h1, h1")?.innerText;
    if (h1 && h1.trim()) return h1.trim().slice(0, 500);
    return (document.title || "Untitled").slice(0, 500);
  }

  // Walk a page's tokens and assemble token records with absolute offsets
  // in the article's full text. Also groups tokens by unit_id so the
  // click handler can mutate every span of a split phrasal verb together.
  //
  // Pages are matched to the full text by substring search — the backend's
  // TXT parser only normalises line endings, so JS-derived fullText and
  // server-stored page.text should agree byte-for-byte. If they don't, the
  // page is skipped with a warning rather than throwing.
  function buildTokens(fullText, pages, userDict) {
    const tokens = [];
    const unitsById = new Map(); // unit_id → { lemma, tokenSpans, unit_text, pair_id, kind }
    let searchFrom = 0;
    const dictKeys = new Set(Object.keys(userDict || {}).map((k) => k.toLowerCase()));

    for (const page of pages) {
      const pageText = page.text || "";
      const pageStart = fullText.indexOf(pageText, searchFrom);
      if (pageStart === -1) {
        console.warn("[enr] page text not found in fullText; skipping page", page);
        continue;
      }
      searchFrom = pageStart + pageText.length;

      // Index units so tokens can attach to the right group.
      const pageUnits = new Map();
      for (const u of page.units || []) {
        pageUnits.set(u.id, u);
      }

      // Compute sentence strings via is_sent_start boundaries.
      const pageTokens = page.tokens || [];
      const sentStarts = [];
      for (let i = 0; i < pageTokens.length; i++) {
        if (pageTokens[i].is_sent_start) sentStarts.push(i);
      }
      // Ensure first token is a sentence start even if flag is missing.
      if (sentStarts.length === 0 || sentStarts[0] !== 0) sentStarts.unshift(0);

      function sentenceTextFor(tokenIdx) {
        // Find the largest sentStart <= tokenIdx and the smallest > tokenIdx.
        let startIdx = 0;
        for (const s of sentStarts) {
          if (s <= tokenIdx) startIdx = s;
          else break;
        }
        let endIdx = pageTokens.length; // exclusive
        for (const s of sentStarts) {
          if (s > tokenIdx) { endIdx = s; break; }
        }
        const startTok = pageTokens[startIdx];
        const lastTok = pageTokens[endIdx - 1];
        if (!startTok || !lastTok) return "";
        return pageText.slice(startTok.idx_in_text, lastTok.idx_in_text + (lastTok.text || "").length);
      }

      function sentenceIdxFor(tokenIdx) {
        let sIdx = 0;
        for (let k = 0; k < sentStarts.length; k++) {
          if (sentStarts[k] <= tokenIdx) sIdx = k; else break;
        }
        return sIdx;
      }

      for (let i = 0; i < pageTokens.length; i++) {
        const t = pageTokens[i];
        if (!t.translatable) continue;
        const unit = pageUnits.get(t.unit_id);
        const sentence = sentenceTextFor(i);
        const sIdx = sentenceIdxFor(i);
        const prevSentence = sIdx > 0 ? sentenceForStart(sentStarts[sIdx - 1], pageTokens, sentStarts, sIdx - 1, pageText) : "";
        const nextSentence = sIdx < sentStarts.length - 1 ? sentenceForStart(sentStarts[sIdx + 1], pageTokens, sentStarts, sIdx + 1, pageText) : "";

        const tokStart = pageStart + t.idx_in_text;
        const tokEnd = tokStart + (t.text || "").length;
        const unitLemma = unit?.lemma || t.lemma || (t.text || "").toLowerCase();
        const known = dictKeys.has(unitLemma.toLowerCase());

        // Compute the unit's canonical surface form (tokens of the unit,
        // joined by single spaces). Token.token_ids are zero-based indices
        // into the page's own tokens list.
        let unitText = "";
        if (unit) {
          const parts = (unit.token_ids || [])
            .map((tid) => pageTokens[tid])
            .filter(Boolean)
            .map((pt) => pt.text);
          unitText = parts.join(" ");
        }
        if (!unitText) unitText = t.text || "";

        tokens.push({
          start: tokStart,
          end: tokEnd,
          lemma: unitLemma,
          unit_id: t.unit_id ?? null,
          pair_id: t.pair_id ?? null,
          unit_text: unitText,
          sentence,
          prev_sentence: prevSentence,
          next_sentence: nextSentence,
          known,
        });
      }
    }

    return tokens;
  }

  function sentenceForStart(startIdx, pageTokens, sentStarts, myIdx, pageText) {
    const endIdx = myIdx < sentStarts.length - 1 ? sentStarts[myIdx + 1] : pageTokens.length;
    const a = pageTokens[startIdx];
    const b = pageTokens[endIdx - 1];
    if (!a || !b) return "";
    return pageText.slice(a.idx_in_text, b.idx_in_text + (b.text || "").length);
  }

  // Pre-fill known units with their cached translation. The user dictionary
  // maps lemma → Russian, so any span whose lemma is in the dict flips to
  // its translated form immediately.
  function prefillKnown(spans, userDict) {
    if (!userDict) return;
    const byLemma = {};
    for (const [k, v] of Object.entries(userDict)) byLemma[k.toLowerCase()] = v;

    // Group spans by unit_id so a split phrasal verb flips as a unit.
    const byUnit = new Map();
    for (const s of spans) {
      const uid = s.token.unit_id ?? `lemma:${s.token.lemma}`;
      if (!byUnit.has(uid)) byUnit.set(uid, []);
      byUnit.get(uid).push(s);
    }
    for (const group of byUnit.values()) {
      const lemma = (group[0].token.lemma || "").toLowerCase();
      const ru = byLemma[lemma];
      if (!ru) continue;
      applyTranslation(group, ru);
      for (const s of group) s.el.classList.add("enr-token--known");
    }
  }

  // Replace the text of every span in a unit group with `ru`. For
  // multi-span units we keep the first span's text as the full translation
  // and clear the rest so the sentence reads cleanly. Clearing is
  // conservative — we set textContent to "" rather than removing the
  // element so DOM layout is preserved.
  function applyTranslation(group, ru) {
    group.sort((a, b) => a.token.start - b.token.start);
    group.forEach((s, i) => {
      s.el.classList.add("enr-token--translated");
      s.el.classList.remove("enr-token--loading", "enr-token--error");
      if (i === 0) s.el.textContent = ru;
      else s.el.textContent = "";
    });
  }

  function resetTranslation(group) {
    for (const s of group) {
      s.el.textContent = s.el.dataset.original || "";
      s.el.classList.remove("enr-token--translated", "enr-token--loading", "enr-token--error", "enr-token--known");
    }
  }

  // --- click handler -----------------------------------------------------

  let spansByUnit = new Map(); // unit_id → [{el, token}]
  let articleId = null;

  function onTokenClick(event) {
    const el = event.target.closest?.(".enr-token");
    if (!el) return;
    event.preventDefault();
    event.stopPropagation();

    const unitId = el.dataset.unitId || `lemma:${el.dataset.lemma}`;
    const group = spansByUnit.get(unitId);
    if (!group) return;

    // Toggle: if already translated, revert to original on click.
    if (el.classList.contains("enr-token--translated")) {
      resetTranslation(group);
      return;
    }

    for (const s of group) s.el.classList.add("enr-token--loading");

    const t = group[0].token;
    sendMessage({
      type: "api",
      name: "translate",
      args: [{
        unitText: t.unit_text,
        lemma: t.lemma,
        sentence: t.sentence,
        prevSentence: t.prev_sentence,
        nextSentence: t.next_sentence,
        sourceBookId: articleId,
        mode: "translate",
      }],
    }).then((resp) => {
      if (!resp?.ok) {
        for (const s of group) {
          s.el.classList.remove("enr-token--loading");
          s.el.classList.add("enr-token--error");
        }
        __enrToast(resp?.error || "translate failed", "err");
        return;
      }
      const ru = resp.result?.ru;
      if (!ru) {
        for (const s of group) {
          s.el.classList.remove("enr-token--loading");
          s.el.classList.add("enr-token--error");
        }
        return;
      }
      applyTranslation(group, ru);
    }).catch((e) => {
      for (const s of group) {
        s.el.classList.remove("enr-token--loading");
        s.el.classList.add("enr-token--error");
      }
      __enrToast(String(e), "err");
    });
  }

  // --- badge -------------------------------------------------------------

  function addBadge(articleTitle) {
    const badge = document.createElement("div");
    badge.id = "enr-badge";
    const label = document.createElement("span");
    label.textContent = "en-reader active";
    const close = document.createElement("button");
    close.textContent = "×";
    close.title = "Close (reload to restore)";
    close.addEventListener("click", () => location.reload());
    badge.appendChild(label);
    badge.appendChild(close);
    document.documentElement.appendChild(badge);
  }

  // --- main --------------------------------------------------------------

  (async function main() {
    __enrToast("Extracting article…", "info");
    const articleRoot = dm.findArticleRoot();
    if (!articleRoot) {
      __enrToast("Could not find article content on this page", "err");
      return;
    }

    const { fullText, nodeMap } = dm.collectText(articleRoot);
    if (fullText.trim().length < 100) {
      __enrToast("Article too short (or not detected)", "err");
      return;
    }

    __enrToast("Importing…", "info");

    let resp;
    try {
      resp = await sendMessage({
        type: "api",
        name: "importArticle",
        args: [{ url: location.href, title: pageTitle(), text: fullText }],
      });
    } catch (e) {
      __enrToast(`Import failed: ${e.message || e}`, "err");
      return;
    }
    if (!resp?.ok) {
      if (resp?.status === 401) {
        __enrToast("Not authenticated — open extension options to log in", "err");
      } else {
        __enrToast(`Import failed: ${resp?.error || "unknown"}`, "err");
      }
      return;
    }

    const result = resp.result || {};
    articleId = result.article_id;
    const pages = result.pages || [];
    const userDict = result.user_dict || {};

    const tokens = buildTokens(fullText, pages, userDict);
    if (tokens.length === 0) {
      __enrToast("No translatable words found", "err");
      return;
    }

    const created = dm.injectTokens(nodeMap, tokens);

    // Group spans by unit id for the click handler.
    spansByUnit = new Map();
    for (const s of created) {
      const uid = s.token.unit_id != null ? String(s.token.unit_id) : `lemma:${s.token.lemma}`;
      if (!spansByUnit.has(uid)) spansByUnit.set(uid, []);
      spansByUnit.get(uid).push(s);
    }

    prefillKnown(created, userDict);

    document.addEventListener("click", onTokenClick, { capture: true });
    addBadge();
    __enrToast(`Loaded ${tokens.length} words — click to translate`, "ok");
  })();

  // --- toast -------------------------------------------------------------

  function __enrToast(text, kind = "info") {
    let el = document.getElementById("enr-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "enr-toast";
      document.documentElement.appendChild(el);
    }
    el.textContent = text;
    el.style.background = kind === "err"
      ? "#8a2020"
      : kind === "ok"
      ? "#1d5a2c"
      : "#111";
    el.classList.add("enr-toast--show");
    clearTimeout(__enrToast._t);
    __enrToast._t = setTimeout(() => {
      el.classList.remove("enr-toast--show");
    }, 2600);
  }
  window.__enrToast = __enrToast;
})();
