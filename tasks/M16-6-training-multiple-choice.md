# Задача M16.6 — Тренировка: выбор перевода (multiple choice)

**Размер.** M (~2 дня)
**Зависимости.** M16.1, M16.2, M16.3 (progression + training API).
**Что строится поверх.** M16.7 (карточки), M16.8 (streak).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Вкладка «Учить» имеет два режима; первый — **выбор перевода**: показывается английское слово и 4 русских варианта, правильный — один. На основе результата слово переходит между статусами (M16.3).

Сессия — до 10 слов. Пул — в приоритете review, потом new/learning. После финала — экран «Готово» со статистикой.

---

## Что нужно сделать

Экран «Учить» (home + сессия + готово), логика выбора и feedback'а, сеть к API прогрессии.

---

## Что входит

### 1. Экран Learn Home (`/learn`)

Структура (см. `ScreenLearn` в прототипе):
- `.uplabel "Тренировка"` + `h1 "Что учим сегодня"`.
- Daily-goal card (если M16.8 готов — включит; иначе placeholder): огонь-иконка 32×32 на accent, «Цель дня: 10 слов», «N/10 сделано», `.pbar`.
- `.uplabel "Режимы"`.
- Карточка «⚡ Выбор перевода» (44×44 emoji-box с `.soft` фоном + title 15 px 600 + desc 12 px `ink-2` + counter N слов + chevR).
- Карточка «🧠 Карточки» (M16.7 — пока заглушка с «скоро»).

Клик «Выбор перевода» → `state.screen = 'learnCard'` + начать сессию.

### 2. Экран Learn Card (`/learn/card`)

#### 2a. Подготовка сессии

При входе на экран: `GET /api/dictionary/training?limit=10` → массив слов. Если пул пуст — экран «Нечего учить, возвращайся позже».

State:
```js
state.learn = {
  pool: [...],       // max 10
  idx: 0,
  correct: 0,
  feedback: null,    // 'ok' | 'wrong' | null
  pickedWrong: null, // для подсветки
};
```

#### 2b. Header + progress

- `btn ghost sm` back (chevL).
- Центр: `${idx+1} / ${total}` 12 px `ink-2`.
- Placeholder 34×34 справа (для симметрии).
- Под header — сегментированный прогресс:
  ```css
  .segments { display: flex; gap: 4px; margin-bottom: 20px; }
  .segments > div { flex: 1; height: 3px; border-radius: 2px; }
  ```
  i < idx → `var(--accent)`, i === idx → `var(--ink)`, else → `var(--line)`.

#### 2c. Flashcard

`.card` (borderRadius 20 px, padding 30px/20px/24px, min-height 260 px):
- `.uplabel` center «Какой перевод?».
- Headword 42 px 600 letter-spacing -0.02em center.
- IPA/POS italic 12 px `ink-2` center.
- `.soft` box (borderRadius 12 px, padding 14px 16px) с примером — слово обёрнуто `<b style="color:var(--accent)">`, 14 px line-height 1.55.
- source 10 px `ink-2` letter-spacing 0.04em center.

#### 2d. Grid 2×2 ответов

4 кнопки: правильный перевод + 3 distractors (другие русские переводы из словаря пользователя + fallback-список).

```js
function buildOptions(currentWord, pool) {
  const distractors = pool.filter(w => w.lemma !== currentWord.lemma).map(w => w.translation);
  const fallback = ['внушительный', 'странный', 'тёплый', 'острый', 'лёгкий', 'прилежный', 'хрупкий'];
  const picks = [currentWord.translation, ...distractors.concat(fallback)].slice(0, 4);
  return shuffle(picks, currentWord.lemma);  // детерминированный shuffle по лемме
}
```

Стили кнопок:
```css
.mc-option {
  padding: 16px 14px; border-radius: 14px;
  font-size: 15px; font-weight: 500; text-align: left;
  background: var(--card); color: var(--ink);
  border: 1.5px solid var(--line);
  cursor: pointer; transition: background 0.2s, border 0.2s;
}
.mc-option.right { background: color-mix(in oklab, #6b8a4a 25%, var(--card));
                   border-color: #6b8a4a; }
.mc-option.wrong { background: color-mix(in oklab, var(--accent) 18%, var(--card));
                   border-color: var(--accent); }
```

#### 2e. Логика клика

```js
onClick(option):
  if state.learn.feedback !== null: return;
  const right = option === current.translation;
  if right:
    state.learn.feedback = 'ok';
    state.learn.correct += 1;
    rerender();
    POST /api/dictionary/training/result {lemma, correct: true}
    setTimeout(advance, 700);
  else:
    state.learn.feedback = 'wrong';
    state.learn.pickedWrong = option;
    rerender();
    POST /api/dictionary/training/result {lemma, correct: false}
    setTimeout(advance, 1200);
```

`advance()` — инкремент idx, reset feedback, rerender. Если idx === total — `state.learn.done = true`.

#### 2f. Footer

- «Пропустить» (ink-2 12 px cursor: pointer) — инкремент idx без API-вызова.
- Справа — статус: "verify нажми любой вариант" / "✓ верно" / "правильный вариант подсвечен".

### 3. Done screen

Если `state.learn.done`:
- Emoji 56 px «✨».
- `h1 "Готово!"` 28 px 600 center.
- «N из M верно» 14 px `ink-2` center.
- `.soft` card: «Серия» + streak (если M16.8 готов) + «+XX XP».
- `btn primary full` «Вернуться» → `/learn`.

### 4. Таббар

В `/learn` — таббар показан, активен `learn`. В `/learn/card` — таббар **скрыт** (как в ридере — убирает отвлечения). Back-btn возвращает на `/learn`.

### 5. Тесты

- Пул пуст → показан заглушка.
- Правильный ответ → счётчик +1, через 700 мс — следующее слово.
- Неправильный → подсветка + правильный, через 1200 мс — следующее.
- Завершение сессии → done screen.
- POST результата на каждый ответ.

### 6. Acceptance-сценарии

- Seed пользователя с 10 словами в `new/learning/review`, открыть «Учить» → «Выбор перевода» → ответить на все.
- После сессии в API `GET /api/dictionary` проверить, что статусы изменились по правилам (M16.3).
- Counter «N / 10 сегодня» обновляется на экране «Учить».

---

## Дизайн

Эталон — [`prototype.html`](./_assets/design/prototype.html), функции `ScreenLearn` и `ScreenLearnCard`.

---

## Acceptance

- [ ] «Выбор перевода» работает, счёт корректный.
- [ ] POST result отправляется на каждый ответ.
- [ ] Прогресс-сегменты + счётчик номеров.
- [ ] Feedback цвета верны в light/dark.
- [ ] Пропустить работает.
- [ ] Done screen отображается.
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M16-6-training-multiple-choice`, PR в main.

---

## Что НЕ делать

- Не делай flashcard режим (M16.7).
- Не делай streak-анимации (M16.8).
- Не храни результаты тренировки локально — только на сервере.
- Не показывай explanation/пример повторно — один экран один cycle.
