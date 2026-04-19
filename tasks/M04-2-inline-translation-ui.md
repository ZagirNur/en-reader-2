# Задача M4.2 — Замена слова переводом + bottom sheet

**Размер.** M (~2 дня)
**Зависимости.** M3.3 (рендер `.word`), M4.1 (`POST /api/translate`), M16.1 (токены/темы), M16.2 (bottom-sheet/toast компоненты).
**Что строится поверх.** M5.1 (словарь + авто-подсветка) — клик начнёт ещё и пополнять словарь; M17-x (detail sheet — расширенная версия).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Ядро UX: клик по английскому слову **заменяет его** русским переводом. Не вставка рядом. Клик по уже переведённому (русскому) слову — открывает **bottom sheet** с деталями (IPA, часть речи, перевод, пример из книги, действия «В словарь» / «Оригинал»).

Перевод применяется ко **всем вхождениям** слова в книге. Поскольку словарь на уровне пользователя (M5.1 + M6.1), при подгрузке следующих страниц уже известные слова приходят с пометкой `auto_unit_ids` и сразу рендерятся как переведённые.

Viewport при клике не должен прыгать — даже если высота строки чуть изменилась из-за замены.

---

## Что нужно сделать

Хендлер клика по `.word`: если EN — запрос перевода + замена textContent + подсветка всех вхождений + короткая вспышка. Если RU (`.translated`) — открыть bottom sheet с деталями и действиями.

---

## Что входит

### 1. Хендлер клика

Делегирование на `.reader`:
```js
async function onWordTap(e) {
  const span = e.target.closest(".word");
  if (!span) return;
  if (span.classList.contains("translated")) {
    openWordSheet(span);
    return;
  }
  await translateAndReplace(span);
}
```

### 2. Подготовка контекста

```js
function getSentenceFor(span) {
  // Находим предложение, в котором лежит span. Опирайся на сохранённые границы
  // предложений из seed (см. design-spec + реализация M3.1).
  return span.closest("[data-sentence]")?.textContent
      ?? span.closest(".page-body").textContent.slice(0, 300);
}
```

Рекомендуется в seed-пайплайне обернуть каждое предложение `<span data-sentence-id="..."></span>`. Если ещё нет — сделай в этой задаче, иначе контекст будет кривой.

### 3. `translateAndReplace(span)`

```js
async function translateAndReplace(span) {
  const lemma = span.dataset.lemma;
  const pairId = span.dataset.pairId;
  const unitText = span.textContent.trim();
  const sentence = getSentenceFor(span);

  span.classList.add("loading");

  let ru;
  try {
    const r = await apiPost("/api/translate", {unit_text: unitText, sentence, lemma});
    ru = r.ru;
  } catch (e) {
    span.classList.remove("loading");
    toast("Не удалось перевести");
    return;
  }

  withScrollAnchor(() => {
    // 1. Пополнить локальный словарь пользователя (state.userDict).
    state.userDict[lemma] = ru;

    // 2. Заменить всех с тем же data-lemma на всех загруженных страницах.
    document.querySelectorAll(`.word[data-lemma="${CSS.escape(lemma)}"]`).forEach(w => {
      replaceWithTranslation(w, ru);
    });
    // Для split_phrasal — также заменить парные (тот же pair_id), если есть.
    if (pairId) {
      document.querySelectorAll(`.word[data-pair-id="${CSS.escape(pairId)}"]`).forEach(w => {
        if (!w.classList.contains("translated")) replaceWithTranslation(w, ru);
      });
    }

    // 3. Вспышка .highlighted на текущем span 800 ms.
    span.classList.add("highlighted");
    setTimeout(() => span.classList.remove("highlighted"), 800);
  });

  showToast("В словарь ✓");
}

function replaceWithTranslation(span, ru) {
  span.dataset.originalText = span.textContent;   // для возможности отката
  span.textContent = ru;
  span.classList.remove("loading");
  span.classList.add("translated");
}
```

### 4. Отмена перевода

При возврате к оригиналу:
```js
function revertTranslation(lemma) {
  document.querySelectorAll(`.word.translated[data-lemma="${CSS.escape(lemma)}"]`).forEach(w => {
    w.textContent = w.dataset.originalText;
    delete w.dataset.originalText;
    w.classList.remove("translated");
  });
  delete state.userDict[lemma];
}
```

### 5. `openWordSheet(span)`

Bottom sheet (использует компонент из M16.2) с содержимым:
- Headword — `span.dataset.originalText` (оригинал), 34 px 600.
- Под headword: `${ipa} · ${pos}` — IPA/POS приходят из `/api/word-info/{lemma}` (задача M17 если вводим расширенную модель слов) **или** отсутствуют в MVP. На M4.2 оставь fallback — «—» для IPA и пустую POS, чтобы не блокироваться.
- `.soft`-card «Перевод» + текст `state.userDict[lemma]`.
- Секция «Из книги» с предложением, в котором переведённое слово обёрнуто `<b style="color:var(--accent)">`.
- Actions:
  - `btn primary` «В словарь» / «Убрать из словаря» (зависит от того, сохранено ли — на MVP всё, что переведено, уже в словаре, поэтому бейдж `✓ В словаре`).
  - `btn ghost` «Оригинал» — вызывает `revertTranslation(lemma)` + `DELETE /api/dictionary/{lemma}` (из M5.1) + закрывает sheet + toast «Вернули оригинал».

### 6. Scroll anchor

Используй хелпер из M16.1 / M16.2:
```js
async function withScrollAnchor(mutateSync) {
  const anchor = findVisiblePageSection();
  const topBefore = anchor.getBoundingClientRect().top;
  mutateSync();
  const topAfter = anchor.getBoundingClientRect().top;
  window.scrollBy(0, topAfter - topBefore);
}
```

### 7. Loader-стейт на span

```css
.word.loading { opacity: 0.45; }
```

### 8. Ошибки и сеть

- 502 от сервера → toast, состояние span откатывается (никаких изменений в DOM).
- Повторный клик на одно и то же слово пока `loading` — игнорируется.
- Одновременный клик по разным словам — две параллельные операции, каждая с собственным withScrollAnchor. Anchor общий — берём из actual viewport в момент завершения.

### 9. Acceptance-сценарии

- Клик `ominous` → становится «зловещий» оранжевым. Если `ominous` встретился в параграфе 3 раза — все три сразу переведены.
- Клик на уже переведённое «зловещий» → открылась нижняя шторка с деталями.
- В шторке «Оригинал» → все «зловещий» обратно в `ominous` без бейджа.
- Split PV: клик `look` в «look the word up» → оба span стали русскими (`поискать`). Клик на любой → sheet; «Оригинал» — обратно.
- Top видимой `.page` секции до/после клика совпадает ±1 px.
- Network: при клике новый LLM-запрос. При повторном клике по известному слову на другой странице — запрос не делается (HIT через M6.2).

---

## Технические детали и ловушки

- **`CSS.escape`** на значениях селекторов — защита от кавычек в lemma.
- **Перерендер страницы не нужен** — мутируем только нужные span'ы. Это сохраняет все DOM-обработчики, scroll, рисунок ридера.
- **Sheet через компонент из M16.2** — не переизобретай анимацию. Только content.
- **Split PV rendering.** Оба span c pair_id получают один и тот же перевод (LLM вернула одну русскую строку для всего phrasal). Визуально читатель видит, например, `поискать ... поискать` — согласовано с задумкой «pair_id склеивается семантически». Если это резко ломает грамматику — в M4.2 оставь **одно** русское слово на глаголе, а на частице поставь пустой span с `display: none`. Выбор — согласовать с UX-чекером по итогу.
- **`DELETE /api/dictionary/{lemma}`** в «Оригинал» — да, это идёт на сервер, чтобы на следующих страницах/сессиях слово снова было английским.

---

## Acceptance

- [ ] Клик по EN-слову → RU заменяет его на всех видимых страницах (не вставка рядом).
- [ ] Клик по RU-слову → открыт bottom sheet с деталями и actions.
- [ ] «Оригинал» возвращает английский и удаляет из словаря.
- [ ] 0.8-секундная вспышка `.highlighted` на только что кликнутом span'е.
- [ ] Toast «В словарь ✓» / «Вернули оригинал» при соответствующих событиях.
- [ ] Viewport не прыгает (scroll anchor).
- [ ] Split PV: оба span'а переводятся вместе.
- [ ] Ошибка LLM → toast + откат состояния.
- [ ] Повторный клик во время `loading` игнорируется.

---

## Дизайн

Эталон взаимодействия и sheet — [`prototype.html`](./_assets/design/prototype.html), функция `openWordPopup`. Токены — [`design-spec.md`](./_assets/design/design-spec.md), секция «Word sheet».

---

## Что сдавать

- Ветка `task/M4-2-inline-translation-ui`, PR в main.
- GIF: клик → замена; клик снова → sheet; отмена.

---

## Что НЕ делать

- **Не вставляй перевод рядом с английским.** Замена на месте — и только так. См. memory `feedback_inline_replacement_core.md`.
- Не обращайся к `/api/dictionary` вручную при первом клике — сервер сам пополняет его через `/api/translate` (см. M5.1).
- Не грузи IPA/POS как обязательное поле — это расширение в M17.
- Не реализуй full word-detail (историю встреч, счётчики) — это M17.
