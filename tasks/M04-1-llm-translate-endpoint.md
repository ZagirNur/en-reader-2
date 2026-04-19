# Задача M4.1 — LLM-интеграция и translate endpoint

**Размер.** M (~2 дня)
**Зависимости.** M3.1 (FastAPI), `.env` поддержка.
**Что строится поверх.** M4.2 (фронт вызывает этот эндпоинт), M6.1 (кэш), M6.2 (skip LLM при hit).

---

## О проекте (контекст)

**en-reader** — веб-читалка. MVP-перевод намеренно тупой: один вызов LLM = один запрос на одно слово или выражение в контексте его предложения. Никаких JSON-массивов, merge-правил, sense-ярлыков — это V2. Сейчас ответ LLM — простая русская строка.

LLM — Google Gemini (`gemini-2.5-flash-lite` по умолчанию — быстрая, дешёвая). Промпт подробно описан ниже.

Split phrasal verb: если клик по глаголу `look` в `look the word up`, мы посылаем в LLM как `unit_text="look up"` + предложение. LLM возвращает русский перевод phrasal. На фронте (задача 4.2) частица в DOM скрывается. В этой задаче ты не должен знать про фронт — просто корректно принимать `unit_text` любого вида.

---

## Что нужно сделать

Реализовать серверный контракт перевода: принять `{unit_text, sentence}`, вернуть `{ru}` через LLM с валидацией и ретраями.

---

## Что входит

### 1. Зависимости и конфиг

- В `pyproject.toml` добавить `google-genai`, `python-dotenv`.
- Файл `.env.example` в корне:
  ```
  GEMINI_API_KEY=your-key-here
  GEMINI_MODEL=gemini-2.5-flash-lite
  ```
- В `app.py` на старте загружать `.env` через `python-dotenv` (`load_dotenv()` в начале модуля). Добавить `.env` в `.gitignore`.

### 2. Модуль `src/en_reader/translate.py`

**Функция `translate_one(unit_text: str, sentence: str) -> str`.**

Системный промпт:
```
You are a professional English-to-Russian literary translator.
You receive a single English word or short phrase and the sentence it appears in.
Return ONLY the best Russian translation of the word/phrase, in context.
Rules:
- One short translation, no variants, no explanations.
- Preserve capitalization (lowercase common words, Title Case for proper nouns).
- For a phrasal verb given as a whole (e.g. "look up"), return a single Russian verb or expression.
- If the phrase is the verb part of a split phrasal verb (particle is elsewhere in the sentence),
  still return the full Russian translation including what the particle contributes.
- No punctuation except what belongs to the translation. No quotes, no parentheses.
- Max 60 characters.
```

Пользовательский промпт:
```
Word: <unit_text>
Sentence: <sentence>
```

Вызов Gemini SDK:
```
from google import genai
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
resp = client.models.generate_content(
    model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
    contents=user_prompt,
    config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.2},
)
text = resp.text.strip()
```

### 3. Валидация ответа

Отвергаем ответ, если:
- пустой / только whitespace,
- содержит `<`, `>` (тег),
- длина > 60 символов,
- содержит переводы строк (LLM иногда добавляет).

Если невалиден — считаем попытку неуспешной.

### 4. Ретраи

- 3 попытки.
- Между попытками — экспоненциальный backoff (0.5 s, 1 s, 2 s).
- Ретраим при:
  - Валидационной ошибке (LLM вернула мусор).
  - Исключении при вызове SDK.
  - HTTP-таймауте (SDK обычно их сам бросает как экспшн).

После всех неуспешных попыток — поднять `TranslateError` (класс в `translate.py`).

### 5. Роут `POST /api/translate`

В `app.py`:
```
class TranslateRequest(pydantic.BaseModel):
    unit_text: str = Field(min_length=1, max_length=100)
    sentence: str = Field(min_length=1, max_length=2000)

class TranslateResponse(pydantic.BaseModel):
    ru: str

@app.post("/api/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    try:
        ru = translate_one(req.unit_text, req.sentence)
    except TranslateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return TranslateResponse(ru=ru)
```

### 6. Логирование

Для каждого вызова `translate_one`:
- На входе: `logger.info("translate request: unit=%r sentence=%r", unit_text, sentence[:100])`.
- На выходе (успех): `logger.info("translate ok: unit=%r ru=%r latency=%.2fs attempts=%d", ...)`.
- На выходе (fail): `logger.warning("translate failed after 3 attempts: unit=%r", unit_text)`.

Не логируй `GEMINI_API_KEY` и целые тела запросов к LLM.

### 7. Тесты `tests/test_translate.py`

Мокаем Gemini — **никаких реальных вызовов** в тестах.

- Мок возвращает валидный `"зловещий"` → `translate_one("ominous", "She whispered an ominous warning.")` возвращает `"зловещий"`.
- Мок возвращает пустую строку на первом вызове, валидный на втором → после ретрая возвращается валидный ответ.
- Мок всегда возвращает мусор → через 3 попытки поднимается `TranslateError`.
- `POST /api/translate` возвращает 200 с валидным ответом через TestClient с замоканным Gemini.
- `POST /api/translate` возвращает 502 при `TranslateError`.
- Pydantic-валидация: `unit_text=""` → 422 (FastAPI уже так делает).

---

## Технические детали и ловушки

- **Gemini SDK.** `google-genai` — новая версия (`from google import genai`). НЕ путай с устаревшим `google-generativeai`. Сигнатуры различны.
- **Temperature.** `0.2` — чтобы переводы были стабильнее. Не 0 (иногда LLM деградирует), не 0.7 (вариабельность).
- **`system_instruction`.** В новой SDK передаётся через `config={"system_instruction": ...}`.
- **Таймаут.** SDK по умолчанию достаточен, но можно задать 15 s explicit.
- **Плейсхолдер при прогрессе.** Логи не должны содержать ключ API, потому что `/debug/logs` будет публично доступен.
- **Сетевые ошибки в тестах.** Мок на `translate.translate_one` (`monkeypatch.setattr(...)`) или на более низкий уровень `genai.Client`.

---

## Acceptance

- [ ] `POST /api/translate` работает end-to-end при наличии `GEMINI_API_KEY`.
- [ ] Ручной `curl -X POST -H "Content-Type: application/json" -d '{"unit_text": "ominous", "sentence": "She whispered an ominous warning."}' http://localhost:8000/api/translate` возвращает `{"ru": "..."}` за < 2 с (p50).
- [ ] При отсутствии сети / кривом ключе — 502, не 500.
- [ ] Все тесты в `test_translate.py` зелёные с мокнутым SDK.
- [ ] Логи содержат latency и число попыток.
- [ ] `.env.example` в репо, `.env` в .gitignore.

---

## Что сдавать

- Ветка `task/M4-1-llm-translate-endpoint`, PR в main.
- В описании — пример curl + пример ответа.

---

## Что НЕ делать

- Не кэшируй в этой задаче (M6.1/6.2).
- Не строй JSON-массив перевода целой страницы (это V2).
- Не вызывай LLM реально в тестах.
- Не хардкодь `GEMINI_API_KEY` в коде.
- Не лезь во фронт — он в 4.2.
