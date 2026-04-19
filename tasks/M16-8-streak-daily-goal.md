# Задача M16.8 — Дневная цель и серия (streak)

**Размер.** S (~1 день)
**Зависимости.** M16.3 (training records), M16.6 (MC), M16.7 (flashcards).
**Что строится поверх.** Мотивационные элементы в Library и Learn Home.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Для удержания добавляем два классических элемента:
- **Серия** (streak): сколько дней подряд пользователь делал хотя бы одну тренировку (или переводил хотя бы N слов).
- **Дневная цель**: 10 слов в день (тренировать правильно). Заполняется по мере ответов.

Оба элемента видимы на экранах Library и Learn Home.

---

## Что нужно сделать

БД-таблица для учёта дней активности, API streak/goal, UI-карточки на двух экранах.

---

## Что входит

### 1. Миграция v7 → v8

```sql
CREATE TABLE daily_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,               -- 'YYYY-MM-DD' (UTC)
  words_trained_correct INTEGER NOT NULL DEFAULT 0,
  words_trained_total INTEGER NOT NULL DEFAULT 0,
  UNIQUE(user_id, date)
);
CREATE INDEX idx_daily_user_date ON daily_activity(user_id, date);
```

### 2. Logging в тренировках

В `POST /api/dictionary/training/result`:
```python
today = datetime.utcnow().date().isoformat()
UPSERT daily_activity (user_id, date)
  ON CONFLICT DO UPDATE SET
    words_trained_total = words_trained_total + 1,
    words_trained_correct = words_trained_correct + (1 if correct else 0)
```

### 3. Streak algorithm

```python
def compute_streak(user_id: int) -> int:
    # Считаем consecutive дней (UTC), включая сегодня, где words_trained_total >= 1.
    # Идём назад от сегодня: если в дне есть запись — streak++; иначе break.
    # Вчерашний день считается (today-1 = валид).
    # Сегодня тоже считается. Если сегодня пуст — streak = вчера_включительно (пусть день ещё не окончен).
```

Правило «сегодня пуст — streak не сбрасывается»: важно, чтобы утренний открытие не обнулило вчерашнюю работу.

### 4. Goal

Дефолтная цель — 10 правильных ответов в день. Простое значение, можно в будущем сделать настраиваемым.

```python
def today_goal(user_id: int) -> dict:
    target = 10
    today = datetime.utcnow().date().isoformat()
    row = SELECT words_trained_correct FROM daily_activity WHERE user_id AND date=today
    done = row["words_trained_correct"] if row else 0
    return {"target": target, "done": done, "percent": min(100, done*100//target)}
```

### 5. API

- `GET /api/me/streak` → `{streak: int, today: {target, done, percent}}`.

Этот один endpoint — достаточно для двух экранов.

### 6. UI на Library

См. design-spec / prototype `ScreenLibrary` — streak-card после header. Разметка:
- `.card` без border, `background: var(--soft)`, padding 12x14, flex с gap 12.
- Слева — иконка-огонь 32×32 в quadro (accent bg, white icon).
- Центр: «7 дней подряд» 13 px 600 + «8 слов сегодня · 42 за неделю» 11 px `ink-2`.
- Справа: «+12» + иконка trend (12×12) 11 px `ink-2` — тренд за неделю (опционально, если API даёт).

### 7. UI на Learn Home

См. `ScreenLearn` — Goal-card. `.soft`, padding 18 px, без border:
- Row: иконка-огонь 32×32 accent + «Цель дня: 10 слов» 14 px 600 + «8 / 10 сделано» 11 px `ink-2`.
- `.pbar` 80 % заливка.

### 8. Hook

В `POST /api/dictionary/training/result` вызывается update логика. В `renderLibrary()` и `renderLearn()` — вызвать `GET /api/me/streak` и подставить в карточку.

### 9. Тесты

- Сделать 1 result сегодня → streak = 1, goal.done = 1.
- Сделать 5 results сегодня → streak = 1, goal.done = 5, percent = 50.
- Моделировать результат вчера → streak = 2.
- Пропустить позавчера → streak = 1 (сегодня).

---

## Acceptance

- [ ] Миграция v7→v8 проходит.
- [ ] `GET /api/me/streak` отдаёт правильные значения.
- [ ] Library и Learn Home обновляют streak-card.
- [ ] Streak корректно считается через границу суток (UTC).
- [ ] Тесты зелёные.

---

## Дизайн

Эталон — [`prototype.html`](./_assets/design/prototype.html): `ScreenLibrary` (streak-card после header) и `ScreenLearn` (goal-card).

---

## Что сдавать

- Ветка `task/M16-8-streak-daily-goal`, PR в main.

---

## Что НЕ делать

- Не мотивационные push-уведомления (браузер notifications) — позже.
- Не сложные weekly graphs — MVP.
- Не настраиваемая цель — фиксированно 10.
