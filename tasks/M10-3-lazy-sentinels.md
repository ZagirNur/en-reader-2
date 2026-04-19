# Задача M10.3 — Lazy-подгрузка соседних страниц через sentinels

**Размер.** M (~2 дня)
**Зависимости.** M10.2 (одна страница отрендерена, restoring).
**Что строится поверх.** M10.4 (сохранение позиции зависит от наличия нескольких страниц в DOM).

---

## О проекте (контекст)

**en-reader** — веб-читалка. После восстановления позиции пользователь скроллит вниз — нужно подгрузить страницу 38. Скроллит вверх — страницу 36. Должно быть бесконечно вверх/вниз до границ книги.

Важнейшее требование: **prepend страницы сверху не должен сдвигать viewport**. Если мы просто вставили секцию перед текущей, её высота (скажем, 1200 px) добавится к scrollHeight, и visible-страница уедет вниз на 1200 px. Решение — scroll compensation: запоминаем scrollHeight до вставки, после вставки прибавляем дельту к scrollTop.

---

## Что нужно сделать

Верхний и нижний sentinels, в-flight защита, prepend с compensation, границы.

---

## Что входит

### 1. Sentinel-элементы

После рендера страниц — два невидимых div:
```html
<div class="sentinel sentinel-top"></div>
  ...pages...
<div class="sentinel sentinel-bottom"></div>
```

CSS:
```css
.sentinel { height: 1px; }
```

### 2. IntersectionObserver

```js
const topSentinel = document.querySelector(".sentinel-top");
const bottomSentinel = document.querySelector(".sentinel-bottom");

let loadingTop = false;
let loadingBottom = false;

const topObs = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && !loadingTop && state.loadedFirstIndex > 0) {
    loadAbove();
  }
}, {rootMargin: "400px 0px 0px 0px"});
topObs.observe(topSentinel);

const botObs = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && !loadingBottom && state.loadedLastIndex < state.totalPages - 1) {
    loadBelow();
  }
}, {rootMargin: "0px 0px 400px 0px"});
botObs.observe(bottomSentinel);
```

`rootMargin: "400px"` — триггер срабатывает за 400 px до того, как sentinel реально видим. Даёт запас на подгрузку.

### 3. `loadBelow()`

```js
async function loadBelow() {
  if (loadingBottom) return;
  loadingBottom = true;
  const nextIdx = state.loadedLastIndex + 1;
  try {
    const data = await apiGet(`/api/books/${state.currentBook.id}/content?offset=${nextIdx}&limit=1`);
    const page = data.pages[0];
    appendPage(page);
    state.loadedLastIndex = nextIdx;
  } finally {
    loadingBottom = false;
  }
}
```

`appendPage(page)` — создаёт DOM секции, вставляет **до** `.sentinel-bottom`, применяет auto_unit_ids.

### 4. `loadAbove()` с scroll compensation

```js
async function loadAbove() {
  if (loadingTop) return;
  loadingTop = true;
  const prevIdx = state.loadedFirstIndex - 1;
  try {
    const data = await apiGet(`/api/books/${state.currentBook.id}/content?offset=${prevIdx}&limit=1`);
    const page = data.pages[0];

    const scrollHeightBefore = document.documentElement.scrollHeight;
    const scrollTopBefore = window.scrollY;

    prependPage(page);   // вставка **после** .sentinel-top, **перед** первой .page

    const scrollHeightAfter = document.documentElement.scrollHeight;
    const delta = scrollHeightAfter - scrollHeightBefore;
    window.scrollTo(0, scrollTopBefore + delta);

    state.loadedFirstIndex = prevIdx;
  } finally {
    loadingTop = false;
  }
}
```

### 5. Отключение sentinels на границах

Если `loadedFirstIndex === 0` — верхний sentinel не триггерит. Если `loadedLastIndex === totalPages - 1` — нижний.

### 6. Интеграция с `state.restoring`

Пока `state.restoring === true` — не подгружать соседей. Иначе восстанавливающий ResizeObserver увидит смену высоты и попытается скорректировать scroll. Даём restoring завершиться.

### 7. Ручная проверка

- Seed книгу на 10 страниц. Открыть `/books/1`.
- State: одна страница в DOM (target).
- Скроллю вниз → видно страницу 1, 2, ... — подгружаются по одной.
- Скроллю вверх до начала — подгружается страница, viewport не прыгает.
- На странице 0 — верхний sentinel не срабатывает.
- На странице `total - 1` — нижний не срабатывает.

---

## Технические детали и ловушки

- **`document.documentElement.scrollHeight`** vs `body.scrollHeight` — первое надёжнее.
- **`window.scrollTo` внутри prepend** — должно быть synchronous сразу после DOM-мутации. Если делать в `requestAnimationFrame`, будет визуальный прыжок на один кадр.
- **Overlapping loads**. Если пользователь быстро скроллит вверх — IntersectionObserver может триггерить много раз. Защита — `loadingTop` flag.
- **rootMargin 400px** — эмпирически достаточен для задержки сетевого запроса на 2G. Если станет мало — увеличить.
- **Удаление sentinel-observer** при unmount reader-view.
- **`user_dict`** в ответе на соседей. Игнорируй — он тот же, что был при открытии книги. Если пользователь кликнул новое слово между страницами, `state.userDict` уже обновился локально.

---

## Acceptance

- [ ] При открытии книги в DOM одна `.page` секция.
- [ ] Скролл вниз подгружает страницу 1, 2, ... по одной.
- [ ] Скролл вверх подгружает предыдущие страницы без сдвига viewport (visible rect.top секции — неизменный с точностью ±2 px).
- [ ] На границах sentinels не триггерят.
- [ ] Повторный triger во время активной загрузки игнорируется.

---

## Что сдавать

- Ветка `task/M10-3-lazy-sentinels`, PR в main.
- GIF «бесконечный скролл в обе стороны» — в описании.

---

## Что НЕ делать

- Не реализуй save прогресса (**M10.4**).
- Не грузи батчем по 5 — один запрос = одна страница; простой контракт.
- Не выгружай старые страницы (memory trimming) — откладывается.
- Не используй `scroll-snap` — это навигация по страницам, не наш UX.
