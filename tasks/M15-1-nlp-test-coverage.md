# Задача M15.1 — Полное покрытие NLP

**Размер.** M (~2 дня)
**Зависимости.** M1.1–M1.5.
**Что строится поверх.** Регрессионная страховка ядра продукта.

---

## О проекте (контекст)

**en-reader** — веб-читалка. NLP-разметка — сердце продукта; любая регрессия там скрыта за тысячами токенов. Нужно систематически покрыть все правила, инварианты и edge cases.

Часть тестов уже написана в M1.1–M1.5 — в этой задаче добавляем недостающее и поднимаем coverage ≥ 90%.

---

## Что нужно сделать

Аудит существующих NLP-тестов, добавить недостающие, добиться coverage ≥ 90% модулей `nlp.py`, `models.py`, phrasal/mwe-логики.

---

## Что входит

### 1. Coverage-отчёт

Добавить `coverage` и `pytest-cov` в dev-зависимости. Запуск:
```bash
pytest --cov=src/en_reader --cov-report=term-missing
```

### 2. Недостающие тесты

#### test_tokenizer (из M1.1 расширить):
- `is_sent_start` при нестандартной пунктуации (`"Hello!" He said.`).
- Инвариант concat на 10 000-словном тексте.
- Пробелы-табы-переносы — корректный `idx_in_text`.

#### test_translatable (из M1.2 расширить):
- Параметризованный тест на 50+ слов — проверить каждое правило.
- POS=PROPN (имена): `"Harry whispered"` — Harry и whispered translatable.
- Числа: `"He was 42"` — `42` не translatable (POS=NUM, не в whitelist).

#### test_mwe (из M1.3 расширить):
- Два MWE в одной фразе без пересечения.
- MWE в начале предложения (после sent_start).
- Неполный матч: `"in order"` (без `to`) — не MWE.

#### test_phrasal (из M1.4 расширить):
- Все 10+ частиц (up, down, in, out, on, off, over, through, away, back).
- Split с глаголом в прошедшем времени: `"looked the word up"`.
- Split с герундием: `"looking the word up"`.
- Несколько split PV в одном предложении.
- Приоритет MWE > phrasal — на фикстуре.

#### test_invariants (из M1.5 расширить):
- На всех golden-фикстурах + long.txt: Unit не пересекаются, token.unit_id валиден, каждое предложение имеет ровно один is_sent_start.

### 3. Golden-тесты

В M1.5 уже есть. Убедись, что:
- 5+ фикстур разного типа.
- Golden-файлы в git.
- `--update-golden` работает.

### 4. Performance-бейслайн

Простой тест:
```python
def test_analyze_performance():
    text = Path("tests/fixtures/long.txt").read_text()
    start = time.time()
    tokens, units = analyze(text)
    duration = time.time() - start
    assert duration < 5.0, f"analyze took {duration}s"
```

Цель: ловить внезапные регрессии скорости (если кто-то случайно добавил O(n²)).

### 5. Пропущенные ветки

После coverage-отчёта:
- Найти `pragma: no cover` и оправдать каждый случай.
- Для uncovered строк — написать тест или удалить код как недостижимый.

---

## Технические детали и ловушки

- **spaCy-tests медленные**. Загрузка модели ~2 с. Используй `session`-scope фикстуру:
  ```python
  @pytest.fixture(scope="session")
  def nlp():
      from en_reader.nlp import get_nlp
      return get_nlp()
  ```
- **Параметризация через YAML/JSON**. Для 50+ кейсов — не хардкодь в python, грузи из `tests/fixtures/translatable_cases.json`.
- **Golden-update в CI**. Не должен быть доступен по умолчанию — иначе тесты сами себя «чинят». Флаг есть только локально.

---

## Acceptance

- [ ] `pytest --cov` показывает ≥ 90% на `src/en_reader/nlp.py` и `src/en_reader/models.py`.
- [ ] Все новые параметризованные тесты зелёные.
- [ ] Golden-тесты зелёные.
- [ ] Performance-baseline < 5 с на 10 000 слов.
- [ ] Никаких `pragma: no cover` без комментария-оправдания.

---

## Что сдавать

- Ветка `task/M15-1-nlp-test-coverage`, PR в main.
- В описании PR — скриншот coverage-отчёта.

---

## Что НЕ делать

- Не пиши тесты ради тестов (100% coverage — миф); 90% с явным вниманием к edge cases лучше, чем 99% тривиальных.
- Не тестируй внутренности spaCy.
