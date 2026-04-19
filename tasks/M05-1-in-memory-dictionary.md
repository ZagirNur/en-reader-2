# Задача M5.1 — In-memory словарь + API + авто-подсветка

**Размер.** M (~2 дня)
**Зависимости.** M4.1, M4.2.
**Что строится поверх.** M6.1 (персистенция того же словаря в SQLite), M6.2 (skip LLM при hit).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь перевёл слово `ominous` → система должна запомнить и на всех следующих страницах (и будущих книгах) `ominous` сразу подсвечивать и сразу показывать «зловещий», не прося повторного клика.

На этой стадии хранилище — **в памяти процесса** (нет БД, нет пользователей; один глобальный словарь). В M6.1 переедет в SQLite, в M11.1 получит `user_id`. Контракт API на фронт не меняется — он готовится сразу правильно.

Ключ словаря — **lemma**. Не оригинальный текст: `ominous`, `Ominous`, `ominous,` — это одна запись `ominous`.

---

## Что нужно сделать

Серверный in-memory словарь, API чтения/удаления, авто-подсветка уже известных слов на странице при её рендере.

---

## Что входит

### 1. Модуль `src/en_reader/dictionary.py`

```python
_dict: dict[str, str] = {}   # lemma -> translation

def add(lemma: str, translation: str) -> None: ...
def remove(lemma: str) -> None: ...
def get(lemma: str) -> str | None: ...
def all_items() -> dict[str, str]: ...
```

Простейшая реализация. Потокобезопасность не обязательна (uvicorn single-process).

### 2. Интеграция с `POST /api/translate`

После успешного перевода:
- Получить lemma единицы. Клиент не знает lemma — её знает сервер. Значит:
  - **Вариант А**: клиент передаёт `{unit_text, sentence, lemma}`. Плохо — клиент сам должен знать, как нормализовать.
  - **Вариант Б** (лучше): клиент передаёт `{unit_id, page_index, book_id?}`, сервер достаёт lemma из разметки. Но на M5 нет БД.
  - **Вариант В** (MVP-совместимый): клиент передаёт `{unit_text, sentence, lemma}`, где lemma взята из `data-lemma` атрибута span.
- На этом этапе используем **вариант В**: в рендере (3.3) ты уже прокидываешь `data-lemma`. В `build_demo.py` нужно передавать lemma Unit (а не только составляющих токенов). Сделай это в рамках этой задачи, если не сделано в 3.3.
- Сервер: `_dict[req.lemma] = ru` после успешного перевода.

Обновлённый контракт:
```
POST /api/translate
body: {unit_text, sentence, lemma}
response: {ru}
```

### 3. API словаря

- `GET /api/dictionary` → `{lemma: translation, ...}`.
- `DELETE /api/dictionary/{lemma}` → 204.
- (POST не нужен на этом этапе — записи создаются только через `/api/translate`.)

### 4. Обогащение `/api/demo`

Добавить в ответ `/api/demo`:
- `user_dict: {lemma: translation}` — текущий словарь.
- Для каждой страницы — `auto_unit_ids: list[int]` — ids Units, чьи lemma ∈ user_dict.

Формат:
```
{
  "total_pages": 12,
  "pages": [
    {"page_index": 0, "text": ..., "tokens": ..., "units": ..., "auto_unit_ids": [3, 7]},
    ...
  ],
  "user_dict": {"ominous": "зловещий", "whisper": "шептать"}
}
```

### 5. Рендер-изменение на фронте

- При рендере страницы: если `unit.id ∈ auto_unit_ids` → span рендерится сразу с классом `.translated` и перевод из `user_dict[unit.lemma]` вставляется как `.ru-tag`.
- Для split PV: если глагол в auto → скрыть частицу.

### 6. Хендлер клика с пополнением словаря

- onTranslatableClick:
  - Если уже `.translated` — вызвать `untranslate(span)` + `DELETE /api/dictionary/{lemma}`.
  - Иначе — `POST /api/translate` + локально обновить `state.userDict[lemma] = ru` + применить `.translated` + пометить на всех страницах (не только текущей).

### 7. Глобальное применение словаря

Когда lemma `ominous` переведена — на **всех** отрендеренных страницах нужно пометить соответствующие Units как translated. Алгоритм:
- Пройти по всем `.translatable[data-lemma="ominous"]:not(.translated)` → применить `applyTranslation` с известным переводом.

Это важный cross-page эффект: пользователь на странице 1 кликнул — на странице 5 уже тоже переведено.

### 8. Тесты

#### Бэк `tests/test_dictionary.py`:
- `POST /api/translate` с мокнутым LLM → `GET /api/dictionary` возвращает lemma с переводом.
- `DELETE /api/dictionary/{lemma}` → `GET` больше не содержит её.
- `GET /api/demo` содержит user_dict и auto_unit_ids для страниц, где lemma встречается.

#### Фронт (ручная проверка):
- Кликнул `ominous` на стр. 1 → скроллю до стр. 5 (если есть то же слово) → оно уже `.translated` с переводом.
- Клик по `.ru-tag` → все вхождения на всех страницах снимают translation одновременно.

---

## Технические детали и ловушки

- **Lemma нормализация.** spaCy даёт `token.lemma_` в lowercase обычно. Но может быть `"be"` vs `"Be"` на именах. Нормализуй `.lower()` перед ключом.
- **Lemma для Unit.** У MWE lemma = `"in order to"` (как в словаре). У phrasal — `"look up"`. У split_phrasal — `"look up"` (та же, что у contiguous). У одиночного translatable — lemma токена. В `/api/translate` клиент передаёт эту lemma.
- **Thread safety.** In-memory dict, uvicorn --workers 1 (по умолчанию). Не думай про locks.
- **Перезапуск сервера** обнуляет словарь — это ожидаемо в M5; M6 это исправит.

---

## Acceptance

- [ ] `POST /api/translate` пополняет словарь.
- [ ] `GET /api/dictionary` возвращает словарь.
- [ ] `DELETE /api/dictionary/{lemma}` удаляет запись.
- [ ] `GET /api/demo` возвращает `user_dict` и `auto_unit_ids` для страниц.
- [ ] Авто-подсветка: после клика `ominous` → на других страницах этот Unit `.translated` сразу.
- [ ] Клик по `.ru-tag` снимает перевод со всех страниц одновременно.
- [ ] Рестарт сервера обнуляет словарь (ожидаемо, пофиксит M6).
- [ ] Тесты зелёные.

---

## Что сдавать

- Ветка `task/M5-1-in-memory-dictionary`, PR в main.

---

## Что НЕ делать

- Не подключай SQLite (**M6.1**).
- Не реализуй `user_id` (**M11.1**).
- Не делай page-level cache — ключ словаря это lemma, не набор Unit на странице.
- Не меняй контракт `/api/translate` без `lemma` — она нужна (иначе сервер не знает, что сохранять).
