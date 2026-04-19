# Задача M3.3 — Рендер страниц + translatable + типографика ридера

**Размер.** M (~2 дня)
**Зависимости.** M3.2 (SPA-скелет), `/api/demo` с реальной разметкой, **M16.1** (design tokens — должны быть готовы к этой задаче).
**Что строится поверх.** M4.2 (клик → перевод-замена), M10 (lazy-scroll и resume), M7 (inline-картинки).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Ядро UX: «достойные перевода» слова подчёркнуты, клик по английскому слову **заменяет его** русским переводом прямо на месте. Не добавляет рядом, не вставляет после — **заменяет**. Это основа продукта, не деталь (см. `tasks/_assets/design/design-spec.md`).

На этой задаче — только рендер и стейты. Обработчик клика (замена + sheet) — M4.2. Но чтобы не переделывать потом, структура DOM сразу готова к замене.

---

## Что нужно сделать

Реализовать рендер одной страницы: пройти по токенам, собрать DOM, создать `<span class="word">` для каждой переводимой единицы. На этой стадии — все как английские; клик пока логирует.

---

## Что входит

### 1. View `renderReader()`

- Загружает `/api/demo` (ленивая загрузка, через api.js).
- Для каждой страницы в `state.demo.pages` — рендерит `<section class="page" data-page-index="N">` внутри `<main class="reader">`.
- Page:
  - `.uplabel` «Chapter N / Стр. N» сверху (опционально — глава берётся из будущего TOC, пока можно просто «Page N»).
  - Контейнер `.page-body` с параграфами.

### 2. Алгоритм рендера страницы

Для страницы с `tokens` и `units`:
1. Построить map `token_index → unit_id` (один проход по units).
2. Идти по токенам по порядку:
   - Если токен в Unit и **первый** токен своего Unit → открыть один `<span class="word">` с атрибутами:
     - `data-unit-id="<id>"`,
     - `data-lemma="<lemma>"`,
     - `data-kind="<word|mwe|phrasal|split_phrasal>"`,
     - `data-pair-id="<pair_id>"` (если есть — для split_phrasal),
     - `textContent = <английский текст всех токенов Unit + whitespace между ними>`.
   - Если токен в Unit и **не первый** — уже выведен, пропустить.
   - Если токен НЕ в Unit и `translatable=true` — один `<span class="word">` с `data-lemma` и английским текстом.
   - Если токен НЕ в Unit и `translatable=false` — текстовая нода `token.text + whitespace`.
3. Параграфы (`<p>`) — на основе полей `is_paragraph_start` если в разметке есть, либо просто одного `<p>` на страницу. В MVP — один `<p>`, паттерн абзацев можно детектить по двойному `\n` в тексте — сверься с разметкой и выбирай простейший рабочий вариант.

### 3. Стили word

Из дизайн-спеки, коротко:
```css
.word {
  cursor: pointer;
  padding: 0 2px;
  border-radius: 3px;
  transition: background 0.15s;
  border-bottom: 1px dashed color-mix(in oklab, var(--ink) 30%, transparent);
}
.word:hover { background: color-mix(in oklab, var(--accent) 8%, transparent); }
```

Переведённый и highlighted стейты — вводятся в M4.2, стили уже положи:
```css
.word.translated {
  background: color-mix(in oklab, var(--accent) 15%, transparent);
  color: var(--accent);
  border-bottom: 1px solid var(--accent);
  font-weight: 500;
}
.word.highlighted {
  background: color-mix(in oklab, var(--accent) 25%, transparent);
  color: var(--accent);
  font-weight: 600;
}
```

### 4. Типографика (из design-spec)

```css
.reader { max-width: 720px; margin: 0 auto; padding: 2rem 1rem 4rem; }
.page-body {
  font-family: 'Geist', system-ui, -apple-system, sans-serif;
  font-size: 17px;
  line-height: 1.65;
  color: var(--ink);
  text-wrap: pretty;
}
.page-body p { margin: 0 0 14px; }
.page + .page { margin-top: 1.5rem; }
.page .uplabel { margin-bottom: 14px; }
```

Mobile-корректировки:
```css
@media (max-width: 480px) {
  .reader { padding: 1rem 1.25rem 3rem; }
}
```

Размеры S/M/L/XL ридера (для M9.3 settings): класс на `.reader-root`, `.size-s .page-body { font-size: 16px; }`, `.size-m → 17`, `.size-l → 19`, `.size-xl → 21`. На эту задачу — ставь `.size-m` фиксированно.

### 5. Разделитель страниц

Между `.page` — не нужна крупная плашка «Page N». В дизайн-спеке разделителя как такового нет — страницы идут колонкой. Если хочется визуальной отбивки — тонкий `.uplabel` «Стр. N» над каждой секцией.

### 6. Заглушка onTokenClick

```js
function onTokenClick(e) {
  const span = e.target.closest(".word");
  if (!span) return;
  console.log("clicked", span.dataset.unitId, span.dataset.lemma, span.textContent);
}
reader.addEventListener("click", onTokenClick);
```
Через делегирование на `.reader`. Реальный хендлер — M4.2.

### 7. Ручная проверка на первой главе «Гарри Поттера»

- Открыть `/reader`.
- Страницы идут колонкой, читаются.
- `the / and / I / was / have (aux)` — НЕ оформлены как `.word`.
- `ominous / whispered / look up (как один span) / give away (как один span)` — `.word` с тонким dashed underline.
- Hover — лёгкий оранжевый фон.
- Клик — `console.log` с корректным lemma.
- Вёрстка корректна на 360 px и 1440 px.

---

## Технические детали и ловушки

- **Whitespace в spaCy.** В токене есть `token.whitespace_`. Если seed-пайплайн не клал его — в `build_demo.py` добавь поле `ws` на каждый токен и юзай на фронте. Без этого текст склеится без пробелов.
- **Атомарная Unit.** `textContent` Unit = конкатенация `token.text + token.whitespace` для всех токенов Unit (кроме trailing whitespace последнего — он между Unit и следующим элементом).
- **Split PV.** Два span'а, общий `data-pair-id`, оба `data-kind="split_phrasal"`. Между ними — обычный текст (объект предложения). При переводе оба меняются одновременно (это M4.2).
- **XSS.** textContent + setAttribute для dataset, никаких `innerHTML`.
- **Только один `.page` в DOM** — на этой стадии не делай lazy-лент. Lazy — M10.3.
- **CSS-переменные.** К этой задаче задача M16.1 должна быть готова — `:root { --bg/--ink/--accent/... }` существуют. Если M16.1 ещё не сделано — временно подставь значения из design-spec.md.

---

## Acceptance

- [ ] На 360 px: одна колонка, без горизонтального скролла.
- [ ] На 1440 px: ширина контента 720 px, отцентрирована.
- [ ] Все translatable — `<span class="word">`, у MWE/phrasal один span.
- [ ] Split PV — два span с одинаковым `data-pair-id`.
- [ ] Клик даёт один корректный `data-lemma`.
- [ ] `.word.translated` и `.word.highlighted` стили заложены (визуально ещё не активируются — триггерятся в M4.2, но класс и стиль уже есть).
- [ ] Скриншоты light/dark.

---

## Дизайн

Эталон — [`tasks/_assets/design/prototype.html`](./_assets/design/prototype.html), секция `ScreenReader`. Токены и типографика — [`design-spec.md`](./_assets/design/design-spec.md).

Отличия от прототипа в этой задаче:
- Таб-бар мы ещё не ставим (M9.2).
- Top chrome книги (back, title, chapter, gear) — M9.3.
- Настоящие книги без обложек — M12; пока seed-book.

---

## Что сдавать

- Ветка `task/M3-3-reader-render`, PR в main.
- Скриншот light + dark на mobile и desktop.

---

## Что НЕ делать

- **Не делай `<span class="ru-tag">`** или любую другую вставку перевода рядом с английским. Это принципиально неправильная модель.
- Не подключай LLM — это **4.2**.
- Не делай lazy — **10.3**.
- Не делай header auto-hide / settings — **9.3**.
- Не скрывай частицу split-PV — при переводе заменится весь span на русский, частица (второй span pair_id) тоже заменится на русский (либо на нужный кусок перевода, см. M4.2).
