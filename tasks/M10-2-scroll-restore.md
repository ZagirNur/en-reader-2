# Задача M10.2 — Восстановление скролла при открытии книги

**Размер.** M (~2 дня)
**Зависимости.** M10.1 (progress API в /content), M8.2 (content API).
**Что строится поверх.** M10.3 (lazy-подгрузка вверх/вниз), M10.5 (редирект с `/`).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь закрыл книгу в середине 37-й страницы. Открывает заново — **сразу** должен быть в середине 37-й. Не начало книги, не верх 37-й, не «прыжок» через секунду.

Главная ловушка — восстанавливать скролл по таймеру. Приложение может быть не готово: шрифт догружается, картинка приезжает через 200 мс, высота страницы меняется, и наш scrollTo уже не точный. Решение — восстанавливать **по событиям** (document fonts ready, images loaded, ResizeObserver), а не по `setTimeout`.

Второй важный принцип: **рендерим только target-страницу**. Если сразу рендерить все 100 — браузер повиснет, и мы будем пытаться восстановить скролл в 40 000 пикселей. Рендерим одну, подгрузим соседей по скроллу (задача M10.3).

---

## Что нужно сделать

При открытии книги грузить ровно одну страницу (target), точно скроллить в `section.top + section.height * offset`, дождавшись готовности высоты.

---

## Что входит

### 1. Логика открытия книги

В `renderReader(bookId)`:

1. Установить `state.view = "loading"`.
2. `GET /api/books/{id}/content?offset=${last_page_index}&limit=1` → получили страницу + `last_page_offset` + `total_pages` + `user_dict`.
3. Заполнить state: `{currentBook: {id}, targetPageIndex: last_page_index, targetOffset: last_page_offset, totalPages, pages: [page], loadedFirstIndex: last_page_index, loadedLastIndex: last_page_index, userDict, restoring: true}`.
4. Рендерить read-view: шапка + одна `<section class="page">`.
5. Запустить процедуру восстановления скролла.

### 2. Процедура восстановления скролла

```js
async function restoreScroll() {
  const targetIdx = state.targetPageIndex;
  const section = document.querySelector(`.page[data-page-index="${targetIdx}"]`);
  if (!section) return;

  // 1. Первый скролл — сразу.
  scrollToOffset(section, state.targetOffset);

  // 2. Дождаться document.fonts.ready.
  await document.fonts.ready;
  scrollToOffset(section, state.targetOffset);

  // 3. Дождаться всех картинок (.inline-image) в этой секции.
  const imgs = section.querySelectorAll("img");
  await Promise.all(Array.from(imgs).map(img => {
    if (img.complete) return Promise.resolve();
    return new Promise(res => { img.addEventListener("load", res); img.addEventListener("error", res); });
  }));
  scrollToOffset(section, state.targetOffset);

  // 4. Подписаться на ResizeObserver — если высота меняется дальше, подправлять.
  const ro = new ResizeObserver(() => scrollToOffset(section, state.targetOffset));
  ro.observe(section);

  // 5. Через 2 секунды — отключить ResizeObserver (окно восстановления закрыто).
  setTimeout(() => {
    ro.disconnect();
    state.restoring = false;
  }, 2000);
}

function scrollToOffset(section, offset) {
  const rect = section.getBoundingClientRect();
  const currentTop = rect.top + window.scrollY;
  window.scrollTo(0, currentTop + section.offsetHeight * offset);
}
```

### 3. Гарантия «не затираем прогресс пока restoring»

- В M10.4 появится сохранение прогресса по scroll. Пока `state.restoring === true` — ничего не сохранять. Это критично: наш же scrollTo не должен триггерить save, иначе мы перезапишем реальный прогресс значением 0 (в момент до scrollTo видимая страница — target с offset 0).

### 4. Loader до рендера

Пока идёт `GET /content` — экран `view="loading"`, простой индикатор.

### 5. Ручная проверка

Seed книгу. Вручную через curl:
```
curl -X POST http://localhost:8000/api/books/1/progress \
  -H "Content-Type: application/json" -d '{"last_page_index": 37, "last_page_offset": 0.5}'
```
Открыть `/books/1` → видим середину 37-й страницы **без** промежуточного скачка. Dev Tools: за 2 секунды могут быть 2-4 подстроек scrollTo — это ок, они не должны быть видны глазу (визуально — одна финальная позиция).

### 6. Тесты

- E2E — в M15.6. В этой задаче — ручная проверка + unit-тесты на чистые функции (если разбил `scrollToOffset` на чистую формулу).

---

## Технические детали и ловушки

- **`document.fonts.ready`** — promise, готов когда все @font-face загружены. Почти мгновенно для системных шрифтов, но при загрузке внешнего шрифта (Georgia обычно системный) — может быть заметно.
- **IMG load promise**. Если картинка уже в кэше — `img.complete === true`, promise резолвится немедленно.
- **ResizeObserver** отслеживает любые изменения высоты секции (lazy image resize, reflow). Работает во всех современных браузерах.
- **Порог 2 секунды** — эмпирический. Если документ ещё догружается после — ничего страшного, пользователь уже читает. Поверх этого — `state.restoring` защищает от ошибочного save.
- **Safari iOS** и тач-скролл: `window.scrollTo` работает, но во время «pull-to-refresh» может вести себя странно. В практике — не критично.

---

## Acceptance

- [ ] POST progress (37, 0.5) → открыть `/books/1` → viewport в середине 37-й страницы (±5% высоты).
- [ ] При открытии на странице 0, offset 0 — видно начало книги, без дёргания.
- [ ] Dev Tools — нет видимого пользователю «прыжка» во время восстановления.
- [ ] Только одна страница загружена в DOM (target). Network tab подтверждает.
- [ ] `state.restoring` возвращается в `false` через 2 секунды.

---

## Что сдавать

- Ветка `task/M10-2-scroll-restore`, PR в main.
- GIF в описании PR: как открытие книги выглядит глазами пользователя.

---

## Что НЕ делать

- Не реализуй lazy-подгрузку соседей (**M10.3**).
- Не реализуй save (**M10.4**).
- Не реализуй current-book (**M10.5**).
- Не трогай save-ожидающий прогресс из консоли до M10.4 — он ещё не реализован.
