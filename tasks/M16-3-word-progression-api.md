# Задача M16.3 — Прогрессия слов (new / learning / review / mastered)

**Размер.** M (~2 дня)
**Зависимости.** M6.1 (user_dictionary в SQLite), M11.1 (user_id).
**Что строится поверх.** M16.4 (Словарь-экран), M16.6 (тренировки), M16.8 (streak).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Дизайн ввёл важное расширение: слова в словаре не просто «есть/нет», а имеют **статус прогресса**:
- `new` — только что добавлено, ни разу не тренировалось.
- `learning` — уже прошло 1+ тренировку, отвечаем правильно, но надо закрепить.
- `review` — давно не вспоминали, пора повторить (spaced repetition).
- `mastered` — стабильно отвечаем правильно несколько раз подряд.

Это позволяет:
- На экране «Словарь» показать фильтры и статистики.
- Тренировки брать слова приоритетно из `review`, потом `learning`, потом `new`.
- Показывать стрик/стату «выучено».

Это **не** полноценный SRS (Anki) — упрощённая прогрессия, чтобы был осмысленный экран «Словарь» и «Учить». Формулы простые и детерминированные.

---

## Что нужно сделать

Расширить `user_dictionary`, добавить логику перехода между статусами, API stats, агрегация `review_due`.

---

## Что входит

### 1. Миграция v5 → v6

```sql
ALTER TABLE user_dictionary ADD COLUMN status TEXT NOT NULL DEFAULT 'new';
-- Возможные значения: 'new' | 'learning' | 'review' | 'mastered'
ALTER TABLE user_dictionary ADD COLUMN correct_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_dictionary ADD COLUMN wrong_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_dictionary ADD COLUMN last_reviewed_at TEXT;
ALTER TABLE user_dictionary ADD COLUMN next_review_at TEXT;  -- когда слово должно всплыть в review
-- example и source — для sheet-экранов
ALTER TABLE user_dictionary ADD COLUMN example TEXT;         -- предложение из книги, в котором слово было встречено
ALTER TABLE user_dictionary ADD COLUMN source_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL;
-- ipa и pos — будут подтягиваться из wordlist (не БД)
```

### 2. Заполнение при переводе

В `POST /api/translate` после успешного LLM:
- `status = 'new'`.
- `example = sentence` (первое предложение, в котором слово встречено).
- `source_book_id` — если передано в запросе (или выведено на сервере из context).
- `next_review_at = NOW() + 1 day` (первый review через сутки).

### 3. Переход между статусами

Простые правила:
- **new → learning**: любой правильный ответ в тренировке.
- **learning → review**: 2 правильных подряд; `next_review_at = NOW() + 3 дня`.
- **review → learning**: любой неправильный.
- **review → mastered**: 2 правильных подряд, когда уже был `review`; `next_review_at = NOW() + 14 дней`.
- **mastered → review**: неправильный или прошёл > 30 дней; `next_review_at = NOW() + 1 день`.

Реализовать в функции:
```python
def record_training_result(user_id: int, lemma: str, correct: bool) -> None:
    # грузим слово
    # применяем переходы согласно правилам
    # обновляем correct_streak, wrong_count, last_reviewed_at, next_review_at, status
```

### 4. Due-слова для тренировки

```python
def pick_training_pool(user_id: int, limit: int = 10) -> list[Word]:
    # Приоритет:
    # 1. status='review' AND next_review_at <= NOW()
    # 2. status='learning'
    # 3. status='new'
    # Всего не больше limit; unique по lemma.
```

### 5. Stats-агрегация

```python
def dict_stats(user_id: int) -> dict:
    return {
        "total": count,
        "review_today": count where status='review' AND next_review_at <= tomorrow,
        "active": count where status in ('new', 'learning'),
        "mastered": count where status='mastered',
        "new": count where status='new',
        "learning": count where status='learning',
        "review": count where status='review',
    }
```

### 6. API

- `GET /api/dictionary?status=<all|new|learning|review|mastered>` — список слов, расширенный формат:
  ```
  [
    {
      "lemma": "ominous",
      "translation": "зловещий",
      "status": "learning",
      "example": "She whispered an ominous warning.",
      "source_book": {"id": 1, "title": "The Great Gatsby"},
      "first_seen_at": "2026-04-10T...",
      "last_reviewed_at": "2026-04-18T...",
      "days_since_review": 3
    }, ...
  ]
  ```
- `GET /api/dictionary/stats` — см. раздел 5.
- `GET /api/dictionary/training?limit=10` — тренировочный пул.
- `POST /api/dictionary/training/result` — `{lemma, correct: bool}` → 204.
- `DELETE /api/dictionary/{lemma}` — уже есть из M5.1; каскад по status/progress тривиальный.

### 7. Тесты `tests/test_progression.py`

- new + правильный → learning, streak=1.
- learning + 2 правильных подряд → review, streak=2, next_review_at > NOW().
- review + неправильный → learning, streak=0.
- review + 2 правильных подряд → mastered, streak ≥ 2, next_review_at через ~14 дней.
- pick_training_pool возвращает review сначала, потом new.
- stats возвращают корректные счётчики.

### 8. Ipa/POS — откуда

На M16.3 — **не заполняем**. В M4.2 / sheet этой детали пока нет. В будущей задаче (или одновременно здесь — по возможности) добавь:
- Мини-словарь IPA/POS для частых английских слов (json-файл ~5000 записей). При переводе lookup по lemma. Если нет — пусто.
- Альтернатива — спросить у LLM одним дополнительным вызовом. Дорого на каждый перевод; отложим.

В этой задаче добавь поля `ipa: str | null`, `pos: str | null` в ответе API, но не заполняй их. Поля появятся — клиент их спокойно рисует.

---

## Acceptance

- [ ] Миграция v5→v6 проходит.
- [ ] Новый перевод создаёт запись со `status='new'`.
- [ ] Правила переходов работают (тесты).
- [ ] Training pool возвращает приоритеты корректно.
- [ ] `GET /api/dictionary/stats` отдаёт правильные агрегаты.
- [ ] `POST /api/dictionary/training/result` обновляет статус.
- [ ] Существующие тесты словаря не сломаны.

---

## Что сдавать

- Ветка `task/M16-3-word-progression-api`, PR в main.

---

## Что НЕ делать

- Не имплементируй полный SM-2 / Anki — простые правила достаточны.
- Не реализуй UI (M16.4, M16.6).
- Не тащи IPA как обязательное — оно опциональное.
