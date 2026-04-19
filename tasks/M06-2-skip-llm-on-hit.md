# Задача M6.2 — Skip LLM при hit в словаре

**Размер.** S (~0.5 дня)
**Зависимости.** M6.1 (персистентный словарь).
**Что строится поверх.** Экономия денег/времени на LLM. Кросс-книжный эффект «перевёл раз — знаю везде».

---

## О проекте (контекст)

**en-reader** — веб-читалка. До этой задачи клик по уже известному слову мог всё ещё дёргать LLM — потому что фронт просто не смотрит на словарь, а бэк на `/api/translate` не проверяет кэш. Логика из M5.1 пометила Unit как `auto_unit_ids` только на странице при рендере, но если пользователь кликнул на слове, которого у нас _ещё_ не было в словаре на момент рендера (а оно могло оказаться добавленным через клик на другой странице), — LLM дёрнется лишний раз.

Цель — в `POST /api/translate` на сервере первым делом смотреть в словарь. Hit → вернуть закэшированное. Miss → LLM + сохранение.

---

## Что нужно сделать

На сервере до вызова LLM — lookup по lemma. Добавить логирование hit/miss.

---

## Что входит

### 1. Изменение `POST /api/translate`

В `app.py`:
```python
@app.post("/api/translate")
def translate(req: TranslateRequest):
    cached = storage.dict_get(req.lemma)
    if cached:
        logger.info("translate HIT: lemma=%r", req.lemma)
        return {"ru": cached}
    logger.info("translate MISS: lemma=%r", req.lemma)
    try:
        ru = translate_one(req.unit_text, req.sentence)
    except TranslateError as e:
        raise HTTPException(502, str(e))
    storage.dict_add(req.lemma, ru)
    return {"ru": ru}
```

### 2. Метрики

Добавь два счётчика в память (module-level в `app.py` или `metrics.py`):
```python
class Counters:
    translate_hit = 0
    translate_miss = 0
```

Инкремент на каждом вызове. Вывод — пока только в логах, на `/debug/health` в M14.1.

### 3. Тесты `tests/test_translate_cache.py`

Мок `translate_one`:
- Первый `POST /api/translate` для нового lemma → `translate_one` вызвана один раз.
- Второй `POST` с тем же lemma → `translate_one` НЕ вызвана; ответ тот же.
- `DELETE /api/dictionary/{lemma}` → третий `POST` → `translate_one` вызвана снова.

Проверь через `unittest.mock.Mock` с `assert_called_once()` / `assert_not_called()`.

### 4. Дополнительные сценарии (негативные)

- Пустой lemma в запросе → 422 (pydantic).
- Lemma существует в словаре, но LLM не нужен → 200, latency < 50 ms.

---

## Технические детали и ловушки

- **Нормализация lemma**. Убедись, что клиент и сервер согласованы: нижний регистр везде, strip.
- **Lemma не из разметки.** Если клиент прислал lemma, которой нет в словаре, но она эквивалентна (`"ominous"` vs `"Ominous"`) — `.lower()` на сервере.
- **Race condition.** Два одновременных клика на одно и то же слово — вариант: оба зайдут в MISS, оба вызовут LLM. Через write-through и UNIQUE — второй INSERT IGNORE. Ручной тест: быстро два клика подряд по одному слову — ок, что 2 LLM-вызова (в будущем можно дедуп-gate, но не сейчас).

---

## Acceptance

- [ ] Повторный клик по уже переведённому слову (через DELETE → POST) не дёргает LLM, если слово в словаре.
- [ ] Логи содержат `translate HIT:` и `translate MISS:` соответственно.
- [ ] Тесты `test_translate_cache.py` зелёные.
- [ ] Ответ на hit — < 50 мс (ручная проверка).

---

## Что сдавать

- Ветка `task/M6-2-skip-llm-on-hit`, PR в main.

---

## Что НЕ делать

- Не заводи отдельную таблицу `translation_cache` — словарь и есть кэш.
- Не подменяй логику в `translate_one` — логика skip должна быть в роуте, чтобы `translate_one` оставалась чистым LLM-вызовом.
- Не делай «умного кэша с TTL» — lemma навсегда, пока пользователь её не удалит.
