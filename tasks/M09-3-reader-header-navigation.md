# Задача M9.3 — Шапка читалки + навигация

**Размер.** S (~1 день)
**Зависимости.** M9.2 (библиотека + роутинг).
**Что строится поверх.** M10.5 (кнопка «← Библиотека» очищает current-book).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь хочет всегда видеть название книги и уметь вернуться в библиотеку одним тапом. Но шапка не должна отвлекать при чтении — она должна скрываться при скролле вниз и появляться при скролле вверх.

Также в шапке — прогресс-бар: тонкая полоска, визуализирующая `page_index / total_pages`.

---

## Что нужно сделать

Sticky-header с кнопкой «← Библиотека», заголовком книги и прогресс-баром; auto-hide при скролле вниз.

---

## Что входит

### 1. Разметка шапки

В `renderReader()`:
```html
<header class="reader-header">
  <button class="back-btn" aria-label="Назад">← Библиотека</button>
  <span class="book-title">${title}</span>
  <div class="progress-bar"><div class="progress-fill" style="width: ${percent}%"></div></div>
</header>
```

`book-title` — с ellipsis на overflow.

### 2. CSS

```css
.reader-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid #e0e0e0;
  padding: 0.5rem 1rem;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 0.5rem;
  transition: transform 200ms ease-out;
}
.reader-header.hidden { transform: translateY(-100%); }

.back-btn {
  background: none; border: none; cursor: pointer;
  font-size: 1rem; color: #333;
}
.book-title {
  text-align: center;
  font-size: 0.9rem;
  color: #555;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.progress-bar {
  position: absolute;
  left: 0; right: 0; bottom: 0; height: 2px;
  background: transparent;
}
.progress-fill {
  height: 100%;
  background: #3b82f6;
  transition: width 200ms;
}
```

### 3. Auto-hide при скролле

```js
let lastY = 0;
window.addEventListener("scroll", () => {
  const y = window.scrollY;
  const header = document.querySelector(".reader-header");
  if (!header) return;
  const delta = y - lastY;
  if (y > 100 && delta > 0) header.classList.add("hidden");
  else if (delta < 0) header.classList.remove("hidden");
  lastY = y;
}, {passive: true});
```

Порог 100 px: пока пользователь в самом верху — шапка не прячется.

### 4. Кнопка «← Библиотека»

```js
backBtn.addEventListener("click", () => {
  navigate("/");
});
```

На M9 — просто переход. В M10.5 — также `POST /api/me/current-book {book_id: null}`.

### 5. Прогресс-бар

- `percent = Math.round((page_index / total_pages) * 100)`.
- Определение `page_index` — какая страница сейчас видна (центр viewport ближе всего к центру секции). Переиспользуй/заранее напиши функцию `findVisiblePageIndex()` — она пригодится в M10.
- Обновляй на scroll (через throttle/RAF, не на каждое событие).

### 6. Ручная проверка

- Скроллю вниз — шапка уезжает через 100 px.
- Скроллю вверх — возвращается.
- Кнопка «← Библиотека» возвращает в `/`.
- Прогресс-бар растёт по мере скролла.
- На mobile — то же поведение.

---

## Технические детали и ловушки

- **`backdrop-filter: blur(8px)`** — красиво, но может тормозить на слабых Android. Можно заменить на сплошной фон.
- **`passive: true`** на scroll-listener — важно для плавности.
- **`translateY(-100%)`** — только шапка. Контент под ней остаётся на месте; мы не меняем padding-top.
- **Если header «хочет» вернуться, когда пользователь вверху** — тривиально получается из правила `delta < 0`.
- **Прогресс-бар**: находится **внутри** header'а, на его нижней кромке. При скрытии header'а — прогресс уходит с ним (ок; пользователь скроллит и не смотрит на прогресс).

---

## Acceptance

- [ ] Шапка sticky сверху, содержит back, title, progress.
- [ ] При скролле вниз после 100 px — шапка скрывается; при скролле вверх — возвращается.
- [ ] Клик по «← Библиотека» возвращает в `/`.
- [ ] Прогресс-бар заполняется по мере чтения.
- [ ] Ellipsis для длинных заголовков работает.
- [ ] Нет jank'а при скролле.

---

## Дизайн

Эталон — [`prototype.html`](./_assets/design/prototype.html), секция `ScreenReader` top chrome и `openReaderSettings`. Токены — [`design-spec.md`](./_assets/design/design-spec.md).

Ключевые отличия от «обычной шапки»:
- Top chrome ридера состоит из **трёх** блоков: иконка `chevL` (back), центр — двухстрочный (book title 12 px 600 + `chapter · page N из M` 10 px `var(--ink-2)`), справа — иконка `settings` (три-горизонтальных с кружками). Обе кнопки — `btn ghost sm` с прозрачным фоном.
- Нижняя часть ридера — `.pbar` 4 px с заливкой по прогрессу. В дизайне **это отдельный элемент на дне body** (не часть шапки). Решай сам по вкусу UX, главное `pbar` виден.
- Auto-hide шапки при скролле вниз — да, через `.hidden { transform: translateY(-100%) }`.
- **Settings sheet** (клик по иконке настроек): секции Тема (Светлая/Тёмная/Авто — chips), Размер шрифта (S/M/L/XL — chips) и Перевод (кнопка `btn ghost full «Показать все оригиналы»` — сбрасывает весь `state.userDict` и делает POST `DELETE /api/dictionary` массово для всех lemma, либо один bulk-endpoint в будущем). На MVP — кнопку добавь, сброс делай по одному DELETE на lemma.

В ридере таб-бар **скрыт** — в `renderReader` не показываем компонент `TabBar`.

---

## Что сдавать

- Ветка `task/M9-3-reader-header-navigation`, PR в main.

---

## Что НЕ делать

- Не добавляй меню настроек / изменения шрифта — отдельная задача в будущем.
- Не реализуй clear current-book (M10.5).
- Не делай sidebar с оглавлением.
