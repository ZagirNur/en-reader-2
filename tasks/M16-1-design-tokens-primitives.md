# Задача M16.1 — Design tokens + primitives + theme toggle

**Размер.** M (~2 дня)
**Зависимости.** M3.2 (SPA-скелет).
**Что строится поверх.** Все UI-задачи: M3.3, M4.2, M9.2, M9.3, M11.3, M12.4, все M16.x, M17.x, M18.x.

> Эта задача должна быть сделана **до** M3.3 и M9.2 (перенести её в расписание соответствующе — она блокер для всего UI).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь заказал дизайн в Claude Design — получилась editorial-тема, светлая основная + тёмная. Эталон — [`tasks/_assets/design/prototype.html`](./_assets/design/prototype.html), справка — [`design-spec.md`](./_assets/design/design-spec.md).

Эта задача — **фундамент визуала**. Все последующие UI-задачи зависят от одного набора CSS-переменных, шрифтов и базовых классов. Без этого каждая задача будет изобретать токены заново.

---

## Что нужно сделать

Сверстать `style.css` с палитрой light/dark, подключить шрифты Geist + Instrument Serif, реализовать базовые классы (`btn`, `chip`, `card`, `pbar`, `uplabel`, `word`), theme-toggle с persist в localStorage и `prefers-color-scheme`.

---

## Что входит

### 1. Подключение шрифтов

В `index.html`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Instrument+Serif&display=swap" rel="stylesheet"/>
```

### 2. CSS-переменные

```css
:root {
  --bg: #f6f4ef; --bg-2: #ecebe5; --card: #ffffff;
  --ink: #14141a; --ink-2: #5c5c66; --ink-3: #9a9aa5;
  --line: #e1dfd5; --accent: #e85d2c; --accent-2: #ff7a45;
  --soft: #ecebe5;
  --body-bg: #d8d3c7;
}
.dark {
  --bg: #0e0e10; --bg-2: #17171a; --card: #17171a;
  --ink: #ebebef; --ink-2: #9a9aa5; --ink-3: #5c5c66;
  --line: #27272e; --accent: #ff7a45; --accent-2: #ffa88a;
  --soft: #1f1f24;
  --body-bg: #1a1a1e;
}
```

Класс `.dark` — на `<html>` (или `<body>`). Всё остальное наследует переменные.

### 3. Base styles

```css
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; height: 100%; }
body {
  font-family: 'Geist', system-ui, -apple-system, sans-serif;
  background: var(--body-bg);
  color: var(--ink);
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
  transition: background 0.3s, color 0.3s;
}
h1, h2, h3 { font-family: 'Geist', sans-serif; letter-spacing: -0.02em; }
h1 { font-size: 30px; font-weight: 600; margin: 0; }
h2 { font-size: 22px; font-weight: 600; margin: 0; }
h3 { font-size: 20px; font-weight: 600; margin: 0; }
.serif { font-family: 'Instrument Serif', Georgia, serif; font-weight: 400; }
.uplabel {
  font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--ink-2); font-weight: 500;
}
```

### 4. Buttons

```css
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  padding: 14px 20px; border-radius: 12px;
  font-family: inherit; font-size: 15px; font-weight: 600;
  border: none; cursor: pointer;
  transition: transform 0.08s, background 0.15s;
}
.btn:active { transform: scale(0.97); }
.btn.primary { background: var(--ink); color: var(--bg); }
.btn.accent  { background: var(--accent); color: #fff; }
.btn.ghost   { background: var(--bg-2); color: var(--ink); }
.btn.full    { width: 100%; }
.btn.sm      { padding: 10px 14px; font-size: 13px; border-radius: 10px; }
```

### 5. Chips

```css
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 8px;
  font-size: 12px; font-weight: 500;
  background: var(--bg-2); color: var(--ink-2);
  border: 1px solid transparent; cursor: pointer;
  font-family: inherit;
}
.chip.on { background: var(--ink); color: var(--bg); }
.chip .n { opacity: 0.5; font-weight: 400; margin-left: 2px; }
```

### 6. Card

```css
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
}
```

### 7. Progress bar

```css
.pbar { height: 4px; border-radius: 2px; background: var(--line); overflow: hidden; }
.pbar > i { display: block; height: 100%; background: var(--accent); }
```

### 8. Book cover presets (градиенты)

7 пресетов light + 7 dark — см. design-spec.md. Скопируй все `.cover.c-*` и `.dark .cover.c-*` из прототипа. Также:
```css
.cover {
  aspect-ratio: 2/3; border-radius: 6px; overflow: hidden;
  position: relative; display: flex; flex-direction: column;
  padding: 12px 10px; color: #fff;
  box-shadow: inset 0 0 0 1px rgba(0,0,0,0.06), 0 10px 24px -14px rgba(0,0,0,0.3);
}
.cover::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.1), transparent 30%, rgba(0,0,0,0.18));
  pointer-events: none;
}
.cover .ct { font-family: 'Instrument Serif', Georgia, serif; font-size: 16px; line-height: 1.05; }
.cover .ca { margin-top: auto; font-size: 8px; letter-spacing: 0.14em; text-transform: uppercase; opacity: 0.78; font-weight: 500; }
```

Утилита в js:
```js
const COVER_PRESETS = ['c-olive','c-clay','c-ink','c-mauve','c-mustard','c-sage','c-rose'];
function coverPresetFor(bookId) {
  // Простой det. hash: сумма кодов → % 7.
  const id = String(bookId);
  let s = 0; for (const ch of id) s = (s * 31 + ch.charCodeAt(0)) >>> 0;
  return COVER_PRESETS[s % COVER_PRESETS.length];
}
```

### 9. `.word` стили

Базовый, translated, highlighted — из design-spec + M3.3. Положи здесь в глобальный CSS.

### 10. Translatable — стейты loading

```css
.word.loading { opacity: 0.45; pointer-events: none; }
```

### 11. Theme toggle

Простой helper:
```js
const THEME_KEY = 'en-reader.theme';
function currentTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'dark' || saved === 'light') return saved;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function setTheme(t) {
  document.documentElement.classList.toggle('dark', t === 'dark');
  localStorage.setItem(THEME_KEY, t);
}
// На старте:
setTheme(currentTheme());
```

На этом этапе — UI переключателя не нужен. Он появится в reader-settings (M9.3). Но API `setTheme` и класс `.dark` должны работать.

### 12. Utility classes

```css
.h-pad { padding-left: 22px; padding-right: 22px; }
.v-gap-16 > * + * { margin-top: 16px; }
/* если нужно — добавляй по мере необходимости */
```

Не заигрывайся с tailwind-подобием. Проект маленький, утилитные классы — по острой нужде.

### 13. `prefers-reduced-motion`

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

### 14. Mobile-first

- `max-width` контента внутри `.reader`, `.library`, etc. — задаётся в своих задачах.
- Глобально: `body { padding: 0; }`.

### 15. Тесты

Визуальная проверка — вручную. Но добавь smoke-test:
- Подключи `style.css` к странице, где есть кнопки/карточки → визуально корректно.
- Смена класса `.dark` на `<html>` → все цвета переключились.
- `localStorage.theme` сохраняется и при перезагрузке поднимает правильную тему.

---

## Acceptance

- [ ] Шрифты Geist + Instrument Serif загружаются, fallback настроен.
- [ ] Все CSS-переменные light/dark работают.
- [ ] Классы `.btn` (primary/accent/ghost/sm/full), `.chip`, `.card`, `.pbar`, `.uplabel`, `.cover.c-*`, `.word` — в стилях.
- [ ] `setTheme('dark')` / `setTheme('light')` мгновенно переключает.
- [ ] Theme persist в localStorage; на старте учитывает `prefers-color-scheme`.
- [ ] `prefers-reduced-motion` отключает анимации.

---

## Дизайн

Эталон всех значений — [`tasks/_assets/design/design-spec.md`](./_assets/design/design-spec.md) и живой прототип [`prototype.html`](./_assets/design/prototype.html).

---

## Что сдавать

- Ветка `task/M16-1-design-tokens-primitives`, PR в main.
- Скриншот демо-страницы со всеми компонентами в light + dark.

---

## Что НЕ делать

- Не подключай CSS-in-JS, tailwind или другие фреймворки.
- Не тащи UI-kit — всё вручную.
- Не добавляй сюда экран-специфичные стили (library, reader, sheet) — они в своих задачах. Сюда только базовые классы.
