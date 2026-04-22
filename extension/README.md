# en-reader — Chrome extension

Inline English-to-Russian reader that works on the article page itself.
Click any word and it gets replaced with its Russian translation, right
in the original DOM. Articles are saved to the en-reader backend as
hidden `kind='article'` books so translations, MWE detection, split
phrasal verbs, and the user dictionary all work exactly like in the main
web reader.

## Install (unpacked, for development)

1. Open `chrome://extensions`.
2. Toggle **Developer mode** on (top right).
3. Click **Load unpacked** and point at this `extension/` directory.
4. Pin the "en-reader inline" icon to the toolbar.
5. Open the extension's options page (right-click the icon → **Options**).
6. Leave the server as `https://enreader.zagirnur.dev` (or change to your
   dev server) and log in with your en-reader email + password.

## Use

1. Open any English article.
2. Click the extension icon, then **Read this page**.
3. After a second, every translatable word gets a subtle dotted underline.
4. Click a word → it flips to the Russian translation inline. Click again
   to revert to the original.
5. Words you've already learned are auto-translated on load (purple
   underline).

Reload the page to clear the overlay.

## Backend changes required

The extension relies on three endpoints added in the accompanying backend
patch:

* `POST /api/articles/import` — create a hidden `kind='article'` book
  from raw text; response bundles the first page of tokenised content.
* `GET /api/articles` — list your article history.
* `DELETE /api/articles/{id}` — remove an article.

Articles live in the same `books` table as regular books but are filtered
out of `/api/books`, so the web library stays uncluttered.

## Files

```
manifest.json                MV3 manifest
background/service_worker.js Message broker + API proxy
content/content.js           Main content script (runs on activation)
content/dom_map.js           DOM text-collection + token injection helpers
lib/api.js                   Bearer-token fetch wrapper
lib/Readability.js           Mozilla Readability (vendored, Apache-2.0)
popup/                       Toolbar popup (activate button + status)
options/                     Options page (server URL + login)
styles/reader.css            Styles for injected tokens
icons/                       Toolbar icons
```

## Notes / limitations

* Works on light DOM only; pages inside shadow roots (e.g. some SPAs)
  are not currently detected.
* Article detection uses Mozilla Readability + heuristic fallbacks
  (`<article>`, `<main>`, text-density). On unusual layouts detection
  may grab too much or too little; activate again after a page
  navigates to retry.
* Pre-formatted code blocks (`<pre>`, `<code>`) are skipped.
* The server's translate endpoint is rate-limited; clicking dozens of
  words rapidly may see temporary 429s.
