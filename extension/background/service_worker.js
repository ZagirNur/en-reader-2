// Service worker brokers API calls for content scripts and opens the options
// page on first install. Content scripts sit on arbitrary web pages — they
// can't reliably do cross-origin fetch to the en-reader server without the
// extension's host permission, so they message the service worker instead.
//
// Messages:
//   { type: "activate" }          → injects content script into the active tab
//   { type: "api", name, args }   → proxied to lib/api.js method with same name
//   { type: "getConfig" }         → returns current baseUrl (no token)
//   { type: "openOptions" }       → opens options page

import { api, getConfig, DEFAULT_BASE_URL } from "../lib/api.js";

chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    chrome.runtime.openOptionsPage();
  }
});

chrome.action.onClicked.addListener((_tab) => {
  // `action` has default_popup set, so this fires only if popup is absent
  // (e.g. keyboard shortcut). Keep it as a safety net.
});

async function activateOnTab(tabId) {
  // Inject Readability and the content script. They are split into multiple
  // files to keep concerns separated — the host-page DOM manipulation lives
  // in content/content.js while content/reader.js contains the rendering
  // logic.
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: ["styles/reader.css"],
    });
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: false },
      files: [
        "lib/Readability.js",
        "content/dom_map.js",
        "content/content.js",
      ],
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg?.type === "activate") {
        const tab = msg.tabId ?? (await chrome.tabs.query({ active: true, currentWindow: true }))[0]?.id;
        if (!tab) {
          sendResponse({ ok: false, error: "no active tab" });
          return;
        }
        const res = await activateOnTab(tab);
        sendResponse(res);
        return;
      }
      if (msg?.type === "getConfig") {
        const cfg = await getConfig();
        sendResponse({ ok: true, baseUrl: cfg.baseUrl || DEFAULT_BASE_URL, hasToken: !!cfg.token });
        return;
      }
      if (msg?.type === "openOptions") {
        chrome.runtime.openOptionsPage();
        sendResponse({ ok: true });
        return;
      }
      if (msg?.type === "api") {
        const fn = api[msg.name];
        if (typeof fn !== "function") {
          sendResponse({ ok: false, error: `unknown api method: ${msg.name}` });
          return;
        }
        const result = await fn.apply(api, msg.args || []);
        sendResponse({ ok: true, result });
        return;
      }
      sendResponse({ ok: false, error: `unknown message: ${msg?.type}` });
    } catch (e) {
      sendResponse({ ok: false, error: e?.message || String(e), status: e?.status });
    }
  })();
  return true; // keep channel open for async sendResponse
});
