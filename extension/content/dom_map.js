// DOM text-collection and token injection.
//
// Glossary:
//   articleRoot  — the Element containing the article body (identified by
//                  Readability or a fallback selector).
//   fullText     — concatenation of all text-node contents inside articleRoot,
//                  with \n\n inserted between block-level boundaries so the
//                  server's sentence segmenter sees paragraph breaks.
//   nodeMap      — ordered list of { node: Text, start, end } describing which
//                  slice of fullText each original text node occupies.
//   token        — { start, end, lemma, unit_id, translatable, sentence } —
//                  came from the server; indices are absolute into fullText.
//
// Script is plain non-module so it can be injected via chrome.scripting
// without `type: module` complications. It exposes a single global
// `window.__enrDomMap` with the helpers used by content.js.

(function () {
  if (window.__enrDomMap) return;

  const SKIP_SELECTORS = [
    "script", "style", "noscript", "template", "iframe", "object", "svg",
    "pre", "code", "kbd", "samp",
    "figure figcaption", // figure captions are usually not part of the article flow
    ".enr-token", "#enr-badge", "#enr-toast",
  ];

  const BLOCK_TAGS = new Set([
    "P", "DIV", "SECTION", "ARTICLE", "H1", "H2", "H3", "H4", "H5", "H6",
    "LI", "UL", "OL", "BLOCKQUOTE", "PRE", "HR", "BR", "TABLE", "TR", "TD", "TH",
    "HEADER", "FOOTER", "ASIDE", "NAV", "MAIN", "FIGURE", "FIGCAPTION", "DL", "DT", "DD",
  ]);

  function shouldSkip(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    if (el.closest && el.closest(SKIP_SELECTORS.join(","))) return true;
    return false;
  }

  // Walk text nodes inside `root` in document order.
  // - Skips subtrees matching SKIP_SELECTORS.
  // - Emits synthetic "\n\n" separators when crossing block-level boundaries,
  //   which never get mapped back to any DOM node (they are pure fullText
  //   scaffolding for the server's sentence segmenter).
  function collectText(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === Node.TEXT_NODE) {
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (shouldSkip(parent)) return NodeFilter.FILTER_REJECT;
          if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
        if (shouldSkip(node)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let fullText = "";
    const nodeMap = [];
    let lastBlockAncestor = null;

    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (n.nodeType === Node.ELEMENT_NODE) continue;

      // Insert block-break separator if this text node's block ancestor differs.
      const block = nearestBlock(n);
      if (lastBlockAncestor && block !== lastBlockAncestor) {
        fullText += "\n\n";
      } else if (fullText.length > 0) {
        fullText += " ";
      }
      lastBlockAncestor = block;

      const value = n.nodeValue;
      const start = fullText.length;
      fullText += value;
      const end = fullText.length;
      nodeMap.push({ node: n, start, end });
    }
    return { fullText, nodeMap };
  }

  function nearestBlock(node) {
    let el = node.parentElement;
    while (el) {
      if (BLOCK_TAGS.has(el.tagName)) return el;
      el = el.parentElement;
    }
    return null;
  }

  // Given an ordered nodeMap and a token with absolute [start, end), find the
  // single text node that contains both ends (tokens don't span multiple DOM
  // nodes since they came from pure text, not HTML). Returns null if the token
  // falls into a synthetic \n\n gap.
  function locateToken(nodeMap, token) {
    // Binary search for the node whose range contains `token.start`.
    let lo = 0, hi = nodeMap.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const m = nodeMap[mid];
      if (token.start < m.start) { hi = mid - 1; continue; }
      if (token.start >= m.end) { lo = mid + 1; continue; }
      // `start` in this node. Check `end` too (can't straddle).
      if (token.end > m.end) return null;
      return mid;
    }
    return null;
  }

  // Wrap tokens as <span class="enr-token"> elements inside the original DOM.
  // Assumes tokens are sorted by `start`. Modifies DOM destructively, but the
  // original text content is preserved — toggling off means simply unwrapping.
  //
  // Returns an array of { el, token, nodeIdx } describing every span created,
  // grouped for later interaction.
  function injectTokens(nodeMap, tokens) {
    const out = [];
    // Group tokens by nodeIdx so we can slice each node in one pass.
    const byNode = new Map();
    for (const t of tokens) {
      const idx = locateToken(nodeMap, t);
      if (idx === null) continue;
      if (!byNode.has(idx)) byNode.set(idx, []);
      byNode.get(idx).push(t);
    }
    for (const [idx, tokensOfNode] of byNode.entries()) {
      tokensOfNode.sort((a, b) => a.start - b.start);
      const entry = nodeMap[idx];
      const originalNode = entry.node;
      const parent = originalNode.parentNode;
      if (!parent) continue;
      const nodeStart = entry.start;
      const fullNodeText = originalNode.nodeValue;
      let cursor = 0; // offset inside fullNodeText
      const frag = document.createDocumentFragment();
      for (const t of tokensOfNode) {
        const localStart = t.start - nodeStart;
        const localEnd = t.end - nodeStart;
        if (localStart < cursor) continue; // overlap, skip
        if (localStart > cursor) {
          frag.appendChild(document.createTextNode(fullNodeText.slice(cursor, localStart)));
        }
        const span = document.createElement("span");
        span.className = "enr-token";
        span.dataset.unitId = String(t.unit_id ?? "");
        span.dataset.pairId = String(t.pair_id ?? "");
        span.dataset.lemma = t.lemma || "";
        span.dataset.unitText = t.unit_text || fullNodeText.slice(localStart, localEnd);
        span.dataset.sentence = t.sentence || "";
        span.dataset.prevSentence = t.prev_sentence || "";
        span.dataset.nextSentence = t.next_sentence || "";
        span.dataset.original = fullNodeText.slice(localStart, localEnd);
        if (t.known) span.classList.add("enr-token--known");
        span.textContent = fullNodeText.slice(localStart, localEnd);
        frag.appendChild(span);
        out.push({ el: span, token: t });
        cursor = localEnd;
      }
      if (cursor < fullNodeText.length) {
        frag.appendChild(document.createTextNode(fullNodeText.slice(cursor)));
      }
      parent.replaceChild(frag, originalNode);
    }
    return out;
  }

  // Try to find the article root using Readability's probe mode. If it
  // returns something with enough text, find the matching element in the
  // live DOM and return that. Otherwise fall back to heuristics.
  function findArticleRoot() {
    const candidates = [];
    if (typeof Readability !== "undefined") {
      try {
        // Readability mutates a clone; we use it to score/choose the root.
        const docClone = document.cloneNode(true);
        const rd = new Readability(docClone, { debug: false, charThreshold: 200 });
        const parsed = rd.parse();
        if (parsed && parsed.content) {
          // We can't directly reuse the parsed fragment (it's from the clone),
          // so score the live DOM for <article>/<main> and pick whichever has
          // the most text that overlaps with parsed.textContent.
          const textSample = (parsed.textContent || "").slice(0, 400).trim();
          if (textSample.length > 100) {
            const match = findByTextSample(textSample);
            if (match) return match;
          }
        }
      } catch (_e) { /* fallthrough */ }
    }
    // Fallbacks, in priority order.
    const fallbacks = ["article", "main", "[role=main]", "[itemprop=articleBody]", ".article-body", ".post-content"];
    for (const sel of fallbacks) {
      const el = document.querySelector(sel);
      if (el && (el.innerText || "").trim().length > 300) return el;
    }
    // Last resort: pick the body subtree with the highest text density.
    return pickByDensity();
  }

  function findByTextSample(sample) {
    // Normalize whitespace for comparison.
    const norm = (s) => s.replace(/\s+/g, " ").trim();
    const target = norm(sample);
    const all = document.body.querySelectorAll("article, main, section, div");
    let best = null;
    let bestScore = 0;
    for (const el of all) {
      if (el.offsetParent === null && el !== document.body) continue;
      const t = norm(el.innerText || "");
      if (t.length < target.length) continue;
      if (!t.includes(target.slice(0, 80))) continue;
      const score = Math.min(t.length, 50000); // longer = more likely container, but cap
      if (score > bestScore) { bestScore = score; best = el; }
    }
    return best;
  }

  function pickByDensity() {
    const all = document.body.querySelectorAll("article, main, section, div");
    let best = document.body;
    let bestScore = 0;
    for (const el of all) {
      if (el.offsetParent === null) continue;
      const text = (el.innerText || "").trim();
      if (text.length < 300) continue;
      const linkText = Array.from(el.querySelectorAll("a"))
        .reduce((n, a) => n + (a.innerText || "").length, 0);
      const density = (text.length - linkText) / Math.max(text.length, 1);
      const score = text.length * density;
      if (score > bestScore) { bestScore = score; best = el; }
    }
    return best;
  }

  window.__enrDomMap = {
    findArticleRoot,
    collectText,
    injectTokens,
  };
})();
