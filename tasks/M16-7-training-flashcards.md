# Задача M16.7 — Тренировка: карточки (flashcards, EN→RU flip)

**Размер.** S (~1 день)
**Зависимости.** M16.6 (home + API).
**Что строится поверх.** Полный training-flow.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Второй режим тренировки — классические карточки: показывается английское слово, пользователь пытается вспомнить перевод, флипом открывается ответ, затем отмечает «Знал» / «Не знал». На основе этого — та же прогрессия статуса (M16.3).

---

## Что нужно сделать

Экран сессии flashcards + flip-анимация + actions «Знал» / «Не знал» + done screen (общий с M16.6).

---

## Что входит

### 1. Вход в режим

Из `ScreenLearn` — клик по «🧠 Карточки» → `state.screen = 'learnFlash'`. Пул берётся тем же `GET /api/dictionary/training?limit=10`.

### 2. State

```js
state.flash = {
  pool: [...],
  idx: 0,
  flipped: false,
  correct: 0,
  done: false,
};
```

### 3. Layout

Похож на MC, но в центре — карточка с двумя сторонами.

#### 3a. Back button + idx/total + сегменты

Как в M16.6.

#### 3b. Flashcard 3D flip

```html
<div class="flashcard ${flipped ? 'flipped' : ''}">
  <div class="fc-front">
    <div class="uplabel">Вспомни перевод</div>
    <h2 class="fc-headword">${word.lemma}</h2>
    <div class="fc-ipa">${word.ipa} · ${word.pos}</div>
  </div>
  <div class="fc-back">
    <div class="uplabel">Перевод</div>
    <h2 class="fc-headword">${word.translation}</h2>
    <div class="fc-example">"${example_with_bold_word}"</div>
    <div class="fc-source">${word.source_book.title}</div>
  </div>
</div>
```

CSS:
```css
.flashcard {
  position: relative; min-height: 280px;
  perspective: 1200px;
}
.fc-front, .fc-back {
  position: absolute; inset: 0;
  background: var(--card); border: 1px solid var(--line);
  border-radius: 20px; padding: 36px 22px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  backface-visibility: hidden;
  transition: transform 0.5s cubic-bezier(.3, .9, .3, 1);
}
.fc-front { transform: rotateY(0deg); }
.fc-back  { transform: rotateY(180deg); }
.flashcard.flipped .fc-front { transform: rotateY(-180deg); }
.flashcard.flipped .fc-back  { transform: rotateY(0deg); }
.fc-headword { font-size: 42px; font-weight: 600; letter-spacing: -0.02em; text-align: center; }
.fc-ipa { font-size: 13px; color: var(--ink-2); font-style: italic; }
.fc-example { font-size: 14px; line-height: 1.55; text-align: center; color: var(--ink); }
.fc-source { font-size: 10px; color: var(--ink-2); letter-spacing: 0.04em; }
```

### 4. Actions

- Пока `!flipped`:
  - `btn primary full` «Показать перевод» → `flipped = true`.
- Когда `flipped`:
  - Row из двух кнопок:
    - `btn ghost` «Не знал» (flex:1) → POST result {correct: false} → advance.
    - `btn primary` «Знал» (flex:1) → POST result {correct: true} → advance.
- Advance: idx += 1, flipped = false; если idx === total → done.

### 5. Footer

- «Пропустить» слева.
- Status: "перевод скрыт" / "нажми что помнишь".

### 6. Done screen

Переиспользуй компонент/секцию из M16.6. Отличие в тексте:
- «Готово!» 28 px.
- «Помнил N из M».

### 7. Тесты

- Пул пуст → заглушка.
- Flip работает (class toggle).
- «Знал» → POST {correct: true} + advance.
- «Не знал» → POST {correct: false} + advance.
- Done после всех.

---

## Acceptance

- [ ] Flip-анимация плавная в обоих темах.
- [ ] «Знал» / «Не знал» шлют правильные correct.
- [ ] Прогресс сегменты.
- [ ] Done screen.
- [ ] `prefers-reduced-motion` — без flip-анимации (мгновенный toggle).

---

## Дизайн

В прототипе flashcard mode не показан детально (только карточка mode в `ScreenLearn`). Стиль согласован с MC (`ScreenLearnCard` — базовая структура card + headword + example + footer).

---

## Что сдавать

- Ветка `task/M16-7-training-flashcards`, PR в main.

---

## Что НЕ делать

- Не добавляй SM-2 интервалы — простая progression из M16.3.
- Не тащи карточки вправо/влево по свайпу — клик-кнопки достаточно.
- Не делай «оцени себя: 1-5» — только бинарный ответ.
