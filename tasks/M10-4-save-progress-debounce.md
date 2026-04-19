# Задача M10.4 — Сохранение прогресса с защитой от stale-save

**Размер.** S (~1 день)
**Зависимости.** M10.1 (API), M10.2 (restoring flag), M10.3 (несколько страниц в DOM).
**Что строится поверх.** M10.5 (redirect-flow).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пока пользователь читает — позиция (видимая страница + offset внутри неё) сохраняется в БД с debounce 1.5 с. Это чтобы не дёргать API на каждое событие scroll, но чтобы при закрытии вкладки позиция была актуальной.

Главная ловушка — **stale save**. Сценарий:
1. Я на странице 10, offset 0.3 → таймер на 1.5 с взведён.
2. Я быстро скроллю на страницу 8, offset 0.4. При этом логика «не постить, если значение не изменилось» делает early return, НЕ сбрасывая предыдущий таймер.
3. Таймер срабатывает, постит старое значение (10, 0.3). Новое (8, 0.4) проиграло.

Решение: **всегда clearTimeout перед любым early-return**. Чистый таймер = чистое состояние.

---

## Что нужно сделать

Вычисление видимой страницы и offset, debounced save, защита от stale.

---

## Что входит

### 1. Функция «видимая страница»

```js
function findVisiblePageSection() {
  const sections = document.querySelectorAll(".page");
  let best = null, bestIntersect = 0;
  for (const s of sections) {
    const r = s.getBoundingClientRect();
    const top = Math.max(r.top, 0);
    const bot = Math.min(r.bottom, innerHeight);
    const intersect = Math.max(0, bot - top);
    if (intersect > bestIntersect) { bestIntersect = intersect; best = s; }
  }
  return best;
}
```

### 2. Вычисление offset

```js
function computeOffset(section) {
  const r = section.getBoundingClientRect();
  if (r.height <= 0) return 0;
  const offset = -r.top / r.height;
  return Math.max(0, Math.min(1, offset));
}
```

Логика: `r.top < 0` когда секция частично ушла вверх за viewport. `-r.top` — сколько прокручено.

### 3. Debounced save

```js
let saveTimer = null;
let lastSaved = {pageIndex: null, offset: null};

function scheduleProgressSave() {
  if (state.restoring) return;      // не затираем в окне восстановления

  const section = findVisiblePageSection();
  if (!section) return;
  const pageIndex = parseInt(section.dataset.pageIndex);
  const offset = computeOffset(section);

  // ВАЖНО: clearTimeout ДО early-return
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }

  // Если значение не изменилось значимо — не сохраняем (но таймер уже сброшен).
  if (lastSaved.pageIndex === pageIndex &&
      Math.abs(lastSaved.offset - offset) < 0.02) {
    return;
  }

  saveTimer = setTimeout(async () => {
    try {
      await apiPost(`/api/books/${state.currentBook.id}/progress`, {
        last_page_index: pageIndex,
        last_page_offset: offset,
      });
      lastSaved = {pageIndex, offset};
    } catch (e) {
      // тихо игнорируем — пользователь это не должен чувствовать
    }
    saveTimer = null;
  }, 1500);
}
```

### 4. Подписка на scroll

```js
window.addEventListener("scroll", scheduleProgressSave, {passive: true});
```

При отмонтировании reader — отписаться и `clearTimeout(saveTimer)`.

### 5. Сохранение перед unload

```js
window.addEventListener("beforeunload", () => {
  if (!saveTimer) return;
  clearTimeout(saveTimer);
  // Синхронный send — Beacon API
  const section = findVisiblePageSection();
  if (!section) return;
  const body = JSON.stringify({
    last_page_index: parseInt(section.dataset.pageIndex),
    last_page_offset: computeOffset(section),
  });
  navigator.sendBeacon(`/api/books/${state.currentBook.id}/progress`, new Blob([body], {type: "application/json"}));
});
```

`sendBeacon` — единственный надёжный способ отправить данные при закрытии вкладки.

### 6. Тесты (unit)

Так как это UI-логика, полноценные тесты — в M15.6 (e2e). Здесь — небольшие unit:
- `computeOffset` на моке rect: `{top: 0, height: 100}` → 0; `{top: -50, height: 100}` → 0.5; `{top: -200, height: 100}` → 1 (clamp).
- Ручная проверка scenario: быстрый скролл 10 → 5 → 8 → 10 за 3 секунды → в БД окажется 10 (финальное значение), не промежуточное.

### 7. Ручная проверка «stale-save» сценария

1. POST progress (10, 0.3) через curl.
2. Открываем `/books/1` → restoring → страница 10.
3. Скроллим вверх до страницы 8, останавливаемся на 0.4.
4. Ждём > 1.5 с.
5. Проверяем БД: `progress_get(1)` → (8, 0.4), не (10, что-то).

---

## Технические детали и ловушки

- **`sendBeacon` body**. Для POST JSON — обёртка в Blob с правильным MIME.
- **`passive: true`** на scroll — обязательно для плавности.
- **Порог «значимого изменения»** — 0.02 offset или смена pageIndex. Меньше — не сохраняем (меньше нагрузки на сервер).
- **`parseInt(dataset.pageIndex)`** — не забывай radix или используй `Number()`.
- **Unmount** reader-view — обязательно cleanup, иначе после возврата в библиотеку scroll-listener продолжит срабатывать.

---

## Acceptance

- [ ] Скролл → через 1.5 с POST /progress с актуальными значениями.
- [ ] Stale-save тест: 10 → 5 → 8 → 10 → в БД финальное, не промежуточное.
- [ ] `state.restoring === true` — ни одного POST.
- [ ] Закрытие вкладки (beforeunload) — последняя позиция успевает сохраниться (проверь через Network → Preserve log).
- [ ] Возврат в библиотеку → scroll-listener снят.

---

## Что сдавать

- Ветка `task/M10-4-save-progress-debounce`, PR в main.

---

## Что НЕ делать

- Не отправляй прогресс чаще чем раз в 1.5 с.
- Не спамить лог при каждом save.
- Не переизобретай логику «видимой страницы» — используй ту же функцию, что в M9.3 для прогресс-бара.
