# Задача M3.2 — Скелет SPA + state + роутинг

**Размер.** S (~1 день)
**Зависимости.** M3.1 (есть `/api/demo`, есть `index.html`-заглушка).
**Что строится поверх.** M3.3 (рендер страниц), M4.2 (клик → LLM), M9 (библиотека), M10 (resume).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Фронт — один HTML + один JS-бандл + один CSS. Никаких React/Vue: ванильный JS достаточен (проект небольшой, команда не боится ручного DOM). Важно собрать правильный скелет — наблюдаемый state, ручной роутер, явные мутации — иначе последующие задачи увязнут в спагетти.

Реальный рендер страниц книги — 3.3, здесь только фундамент.

---

## Что нужно сделать

Сверстать заготовку SPA: state-контейнер, переключение экранов, лоадер, базовый роутер.

---

## Что входит

### 1. `static/index.html`

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>en-reader</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div id="root"></div>
  <script src="/static/app.js" type="module"></script>
</body>
</html>
```

### 2. `static/app.js`

**Модули** (можно в одном файле, секции комментариями):
- `state.js` — один глобальный объект и функции мутации.
- `router.js` — pushState + popstate.
- `render.js` — главный render-dispatcher.
- `api.js` — fetch-обёртки.
- `views/library.js`, `views/reader.js` — заглушки.

В одном файле с чёткими секциями это тоже ок.

**Структура state:**
```
state = {
  view: "loading",   // "loading" | "library" | "reader" | "error"
  error: null,
  route: "/",
  demo: null,        // позже заменится на currentBook/pages
}
```

**Функции:**
- `setState(patch)` — мелкая поверхностная мержит → `render()`.
- `render()` — смотрит на `state.view`, вызывает соответствующий view.
- `navigate(path)` — `history.pushState`, парсит path, `setState({route, view})`.
- `onPopState()` — подписан на `popstate`, тоже обновляет state по URL.

### 3. Роутер

**Маршруты** (пока два):
- `/` → `view="library"`.
- `/reader` → `view="reader"` (пока без id; id появится с библиотекой в M9).

`parseRoute(path)` → `{view}`. На неизвестном пути — `view="error"`.

### 4. Views (заглушки)

- `renderLibrary()`: в `#root` — один `<h1>Library</h1>` и кнопка «Open demo», при клике — `navigate("/reader")`.
- `renderReader()`: запросить `/api/demo` (если ещё не загружен), показать `<div>loaded ${pages.length} pages</div>`. Кнопка «← Back» → `navigate("/")`.
- `renderLoading()`: `<div class="loader">Loading…</div>`.
- `renderError()`: `<div class="error">${state.error}</div>`.

### 5. API-обёртки `api.js`

```
async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
async function apiPost(path, body) { ... }
```

### 6. CSS `static/style.css`

- `body { font-family: Georgia, serif; margin: 0; }`
- `.loader, .error { padding: 2rem; text-align: center; }`
- На этом этапе типографика книги — не здесь, а в 3.3.

### 7. Bootstrap

В конце `app.js`:
```
window.addEventListener("popstate", onPopState);
setState({route: location.pathname, view: parseRoute(location.pathname).view});
```

### 8. Ручная проверка

- Открываешь `/` → видишь «Library» + кнопку.
- Клик по «Open demo» → URL меняется на `/reader`, видно число страниц из `/api/demo`.
- Кнопка «← Back» → возврат на `/`, URL обновляется.
- Кнопка браузера «Назад» тоже работает (через popstate).
- Перезагрузка на `/reader` — остаёшься на `/reader`.
- Dev Tools Console — без ошибок.

---

## Технические детали и ловушки

- **Без фреймворков.** Никакого React/Vue/Svelte/Lit. Бандлер тоже не нужен.
- **`type="module"`** на `<script>` — иначе ES-модули не поедут (если разобьёшь на файлы). С одним файлом можно и без module.
- **Перерендер.** В этом скелете можно полностью замещать `#root.innerHTML` — тяжёлые экраны появятся в 3.3, там уже не выйдет. На этом этапе упрощает жизнь.
- **Страница при прямом открытии URL.** FastAPI `GET /` отдаёт `index.html`. А `/reader` — отдаст 404. Решение: добавить `@app.get("/{full_path:path}")` catch-all, который тоже отдаёт `index.html`. Только убедись что `/api/*` и `/static/*` роуты определены **до** catch-all.
- **CORS не нужен** — фронт и бэк на одном origin.
- **AbortController** для fetch при смене view — в этой задаче не нужно, добавится в M4.

---

## Acceptance

- [ ] `index.html`, `app.js`, `style.css` в `src/en_reader/static/`.
- [ ] Открытие `http://localhost:8000/` → экран library (заглушка).
- [ ] Клик по «Open demo» → `/reader`, число страниц из `/api/demo` видно.
- [ ] Back-кнопка браузера работает.
- [ ] Перезагрузка на `/reader` не даёт 404 (catch-all в FastAPI).
- [ ] Console без ошибок.
- [ ] `setState` / `render` / `navigate` — единственные точки мутации (нет разбросанного `root.innerHTML = ...` в хендлерах).

---

## Что сдавать

- Ветка `task/M3-2-spa-skeleton`, PR в main.

---

## Что НЕ делать

- Не рендери токены страницы — это **3.3**.
- Не добавляй LLM, БД, auth.
- Не подключай сборщики (webpack/vite/esbuild) — ванильный JS, ES modules.
- Не тащи сторонние UI-библиотеки.
