# en-reader — Design Spec (Light Editorial + Dark Editorial)

Оригинальный кликабельный прототип: [`prototype.html`](./prototype.html). Транскрипт обсуждения с дизайнером: [`chat.md`](./chat.md). Эталон визуала — прототип: если в задаче нет конкретного значения, смотри в прототип и бери оттуда.

Тема дизайна — **Editorial**: серый лёгкий фон бумаги, тёмный ink, оранжевый акцент. Основная — светлая, тёмная — «ночная» с тем же языком.

---

## Палитра

### Light
```css
--bg: #f6f4ef; --bg-2: #ecebe5; --card: #ffffff;
--ink: #14141a; --ink-2: #5c5c66; --ink-3: #9a9aa5;
--line: #e1dfd5; --accent: #e85d2c; --accent-2: #ff7a45;
--soft: #ecebe5;
/* body вокруг телефона */
background: #d8d3c7;
```

### Dark
```css
--bg: #0e0e10; --bg-2: #17171a; --card: #17171a;
--ink: #ebebef; --ink-2: #9a9aa5; --ink-3: #5c5c66;
--line: #27272e; --accent: #ff7a45; --accent-2: #ffa88a;
--soft: #1f1f24;
/* body вокруг телефона */
background: #1a1a1e;
```

Переключение по классу `.dark` на `<html>` или `<body>`. Хранение выбора — `localStorage.theme`. Авто — по `prefers-color-scheme`.

---

## Типографика

- Google Fonts: **Geist** (300–700) и **Instrument Serif**.
- Основной шрифт UI/текста: `'Geist', system-ui, -apple-system, sans-serif`.
- Акцентный serif (обложки книг, большие цифры): `'Instrument Serif', Georgia, serif`, `font-weight: 400`.

Размерная шкала:
- `h1`: 30 px, `letter-spacing: -0.02em`, `font-weight: 600`.
- `h3` (sheet-заголовок): 20 px, 600.
- Body (`.page-body` в ридере): **17 px, line-height 1.65**, `text-wrap: pretty`.
- Word popup headword: 34 px, 600, `letter-spacing: -0.02em`.
- Mode-карточки: 15 px, 600; подпись 12 px `var(--ink-2)`.
- `.uplabel` (подзаголовки секций): **10 px**, `letter-spacing: 0.14em`, `text-transform: uppercase`, `color: var(--ink-2)`, `font-weight: 500`.
- Мелкий meta: 10–12 px `var(--ink-2)`.

Reader settings: размеры шрифта S/M/L/XL на выбор (16/17/19/21 px — ориентир).

---

## Компоненты

### Buttons
```
.btn { padding: 14px 20px; border-radius: 12px; font-size: 15px; font-weight: 600; }
.btn.primary { background: var(--ink); color: var(--bg); }
.btn.accent  { background: var(--accent); color: #fff; }
.btn.ghost   { background: var(--bg-2); color: var(--ink); }
.btn.sm      { padding: 10px 14px; font-size: 13px; border-radius: 10px; }
.btn.full    { width: 100%; }
.btn:active { transform: scale(0.97); }
```

### Chips (фильтры, уровни, FSE)
```
.chip { padding: 6px 12px; border-radius: 8px; font-size: 12px;
        background: var(--bg-2); color: var(--ink-2); }
.chip.on { background: var(--ink); color: var(--bg); }
.chip .n { opacity: 0.5; margin-left: 2px; }
```

### Card
```
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; }
```

### Progress bar
```
.pbar { height: 4px; border-radius: 2px; background: var(--line); overflow: hidden; }
.pbar > i { display: block; height: 100%; background: var(--accent); }
```
В тренировке прогресс — сегменты по `total` вместо непрерывной полоски: каждый `3px`, завершённые — `accent`, текущий — `ink`, будущие — `line`.

### Bottom sheet + scrim + handle
```
.scrim { inset: 0; background: rgba(0,0,0,0.32);
         transition: opacity 0.2s; }
.scrim.show { opacity: 1; }

.sheet { border-top-left-radius: 28px; border-top-right-radius: 28px;
         background: var(--card); padding: 16px 22px 28px;
         transform: translateY(100%); transition: transform 0.28s cubic-bezier(.2,.9,.3,1); }
.sheet.show { transform: translateY(0); }
.sheet .handle { width: 40px; height: 4px; border-radius: 2px; background: var(--line);
                 margin: 0 auto 16px; }
```

### Toast
```
.toast { top: 60px; background: var(--ink); color: var(--bg);
         padding: 10px 16px; border-radius: 999px;
         font-size: 13px; transition: opacity/transform 0.2s; }
.toast.show { opacity: 1; transform: translate(-50%, 0); }
```
Пример: `«В словарь ✓»`, `«Вернули оригинал»`, `«Удалено»`.

### Book covers (градиенты — fallback когда реальной обложки нет)
```
.cover { aspect-ratio: 2/3; border-radius: 6px; padding: 12px 10px; color: #fff; }
.cover .ct { font-family: 'Instrument Serif'; font-size: 16px; line-height: 1.05; }
.cover .ca { margin-top: auto; font-size: 8px; letter-spacing: 0.14em;
             text-transform: uppercase; opacity: 0.78; }
/* Пресеты Light (Dark свои, см. prototype.html): */
.cover.c-olive   { background: linear-gradient(150deg, #6a7a42, #3d4826); }
.cover.c-clay    { background: linear-gradient(150deg, #c85a38, #7a2a18); }
.cover.c-ink     { background: linear-gradient(150deg, #2a3342, #0f141c); }
.cover.c-mauve   { background: linear-gradient(150deg, #8c5a6b, #4a2a35); }
.cover.c-mustard { background: linear-gradient(150deg, #c9a253, #7a5a1c); color: #14141a; }
.cover.c-sage    { background: linear-gradient(150deg, #8a9a6c, #4a5836); }
.cover.c-rose    { background: linear-gradient(150deg, #c8685a, #6f2e24); }
```

Алгоритм выбора пресета при загрузке книги без обложки — детерминированный hash(book_id or title) → один из 7 пресетов.

### Translated word (ядро)
```
.word { cursor: pointer; padding: 0 2px; border-radius: 3px; transition: background 0.15s; }
.word.translated {
  background: color-mix(in oklab, var(--accent) 15%, transparent);
  color: var(--accent);
  border-bottom: 1px solid var(--accent);
  font-weight: 500;
}
.word.highlighted {                     /* 800ms вспышка после перевода */
  background: color-mix(in oklab, var(--accent) 25%, transparent);
  color: var(--accent); font-weight: 600;
}
```

**Важно.** `.word.translated` показывает **русский** (textContent заменён), не английский с тегом.

### Tab bar
```
.tabbar { padding: 8px 10px 30px; background: color-mix(in oklab, var(--bg) 88%, transparent);
          backdrop-filter: blur(14px); border-top: 1px solid var(--line); }
.tab { font-size: 10px; font-weight: 500; color: var(--ink-3); }
.tab.on { color: var(--ink); }
.tab.on .tab-dot { width:4px; height:4px; border-radius:50%; background: var(--accent); bottom:-8px; }
.tab svg { width: 22px; height: 22px; }
```

Четыре вкладки: **Мои книги / Каталог / Словарь / Учить**. Иконки из prototype.html — книжка / компас / словарь / мозг. В reader вкладки **скрыты**.

---

## Экраны

Полный рабочий код каждого — в `prototype.html`. Здесь — только назначение и ключевые элементы.

### Library («Мои книги»)
- Sticky-header: дата/время + `h1 "Моя полка"` + аватарка-буква.
- Streak-card: огонь-иконка + «7 дней подряд» + counters + «+12» тренд.
- Block «Продолжить чтение»: большая карточка с обложкой 86×129, title/автор, чаптер + %, `.pbar`, кнопка `primary sm` «Читать дальше».
- Shelf `.uplabel "Библиотека"` + счётчик книг.
- Grid 3 колонки, мелкие обложки + title + level + % + mini pbar.
- Карточка `+` при загрузке не показана отдельным тайлом — add-flow из шапки (см. M12).

### Catalog («Что почитать»)
- `h1 "Что почитать"` + `.uplabel "Каталог"`.
- Row of level chips `A1 A2 B1 B2 C1` (B1 выбран по умолчанию).
- Секции «По твоему уровню» / «Короткое — за выходные» и т. д. — `.uplabel` + горизонтальный скролл карточек 110 px шириной.

### Reader
- Top chrome: back-button (chevron), центр — book title 12 px + `chapter · page N из M` 10 px, справа — gear (настройки).
- Body: `.uplabel "Chapter One"` + параграфы.
- Каждый «translatable» — `<span class="word">`. Не-кликабельные — текстовые ноды.
- Низ body: `42 % · ~18 мин до конца главы` · `{N} новых слов`.
- Внизу экрана — `.pbar` 4 px.
- В reader таббар **скрыт**.
- Settings sheet: секции «Тема» (Светлая/Тёмная/Авто), «Размер шрифта» (S/M/L/XL), «Перевод» (`Показать все оригиналы` — reset).

### Word sheet (первый клик не нужен — он сразу делает перевод; открывается на **повторный** клик по уже переведённому слову)
- Headword 34 px + IPA + POS (italic 13 px var(--ink-2)) + close-btn 36×36 с обводкой `var(--line)`.
- `.soft` card: `.uplabel "Перевод"` + перевод 18 px / 500.
- Секция `.uplabel "Из книги"` + предложение 13 px 1.5 line-height, переведённое слово обёрнуто `<b style="color:var(--accent)">`.
- Accent-info-strip (если только что переведено): «✓ Переведены все вхождения в тексте» — на первом автоматическом клике оно появляется; при повторном клике по `.translated` уже не показывается.
- Row actions: `btn primary "В словарь"` + `btn ghost "Оригинал"`.

### Dictionary
- Header `h1 "Словарь"` + счётчик.
- Stats-card 3×: «На повтор сегодня» (accent color), «Учу сейчас» (ink), «Выучено».
- Filter chips: Все/Повторить/Учу/Новые/Выучено — каждая с бейджем-счётчиком.
- Список карточек слов: headword 19 px + RU перевод + курсив «пример из книги» + source + days-since.
- Справа — бейдж уровня: `new` (accent/white), `learning` (soft/ink), `review` (#c9a253/#2d1a12), `mastered` (#d8e0c0/#2a3f14 light · #2a3f24/#c5d5a0 dark).
- Клик по карточке → Saved-word sheet: те же поля что в Word sheet + actions «Тренировать» (primary) / «Удалить» (ghost).

### Learn home
- `h1 "Что учим сегодня"`.
- Daily-goal-card: «Цель дня: 10 слов», progress 8/10, `.pbar`.
- Режимы: «⚡ Выбор перевода» и «🧠 Карточки» — карточки с иконкой 44×44, title, desc, счётчик `N слов`.

### Learn card (multiple choice)
- Header с back + `idx/total` + сегментированный progress.
- Card: `.uplabel "Какой перевод?"` + headword 42 px + IPA/POS + пример 14 px в `.soft` box со словом в акценте.
- Grid 2×2 кнопок-вариантов. Правильный → зелёная рамка, неправильный → акцентная рамка.
- Footer: «Пропустить» (слева, ink-2) · статус-текст (справа, ink-2).

### Learn done
- Emoji 56 px (`✨`) + `h1 "Готово!"` 28 px 600 + «N из M верно».
- Streak-card.
- `btn primary full "Вернуться"`.

---

## Общие правила

- Mobile-first. Viewport 390 px — контент как на айфоне; на десктоп растёт с max-width 720 px.
- На `@media (max-width: 480px)` рамка-телефон исчезает, приложение занимает весь экран, status-bar и home-bar скрыты.
- Theme toggle (кнопка) live и на десктопе (fixed top-right), на mobile переезжает в настройки ридера.
- Transitions для hover/active короткие: `120–180 ms ease-out`.
- `prefers-reduced-motion`: отключить screen-in, sheet-slide, scale(0.97) на buttons.
- Везде `text-wrap: pretty` для длинного текста (ридер, sheet-example).

---

## Что НЕ брать из прототипа

- `.statusbar` / `.notch` / `.homebar` — это просто макет айфон-рамки. В продакшене их нет.
- `.theme-toggle` в правом верхнем углу — в prod только внутри reader-settings (или глобально в «настройках аккаунта» позже).
- Прошитые данные `LIBRARY`, `CATALOG`, `GATSBY_PAGE`, `WORD_INFO` — это mock. В продакшене берётся из API.
