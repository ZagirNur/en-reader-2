# Задача M1.2 — STOP_WORDS + правило `translatable`

**Размер.** S (~1 день)
**Зависимости.** M1.1 (токенизатор + `Token`).
**Что строится поверх.** M1.3 (MWE) и M1.4 (phrasal verbs) уважают твой `translatable`. M3.3 (фронт) рендерит подчёркивание только для `translatable=True`.

---

## О проекте (контекст)

**en-reader** — веб-читалка английских книг для русскоязычных учащихся. В тексте подчёркиваются «достойные перевода» слова; клик вставляет русский перевод inline. Разметка делается один раз при загрузке книги на spaCy (без LLM).

«Достойное перевода» = слово, которое учащийся B1–C1 реально может не знать. Артикли, частотные местоимения и служебные глаголы подчёркивать бессмысленно — это шум.

---

## Что нужно сделать

Добавить детерминированное правило: какие токены `translatable = True`, какие `= False`. Критерий — POS-фильтр + курируемый STOP_WORDS + спец-обработка AUX.

---

## Что входит

### 1. Файл `data/stop_words.txt`

Курируемый список ~300 английских лемм, которые **никогда** не подчёркиваются. По лемме на строку, строчными буквами.

Категории, которые точно должны быть включены:
- Артикли: `a`, `an`, `the`.
- Быть/иметь/делать как леммы: `be`, `have`, `do`.
- Местоимения: `i`, `you`, `he`, `she`, `it`, `we`, `they`, `me`, `him`, `her`, `us`, `them`, `my`, `your`, `his`, `our`, `their`, `this`, `that`, `these`, `those`, `who`, `whom`, `which`, `what`, `whose`.
- Частотные A1-глаголы: `go`, `come`, `get`, `make`, `take`, `know`, `see`, `think`, `want`, `use`, `find`, `give`, `tell`, `work`, `call`, `try`, `ask`, `need`, `feel`, `become`, `leave`, `put`, `mean`, `keep`, `let`, `begin`, `seem`, `help`, `show`, `hear`, `play`, `run`, `move`, `live`, `believe`, `bring`, `happen`, `write`, `sit`, `stand`, `lose`, `pay`, `meet`, `include`, `continue`, `set`, `learn`, `change`, `lead`, `understand`, `watch`, `follow`, `stop`, `create`, `speak`, `read`, `spend`, `grow`, `open`, `walk`, `win`, `offer`, `remember`, `love`, `consider`, `appear`, `buy`, `wait`, `serve`, `die`, `send`, `expect`, `build`, `stay`, `fall`, `cut`, `reach`, `kill`, `remain`.
- Частотные существительные-слова общего употребления: `man`, `woman`, `day`, `time`, `year`, `thing`, `way`, `life`, `hand`, `place`, `part`, `case`, `point`, `group`, `number`, `world`, `area`, `problem`, `fact`, `month`, `lot`, `right`, `study`, `book`, `eye`, `job`, `word`, `issue`, `side`, `kind`, `head`, `house`, `service`, `friend`, `father`, `hour`, `game`, `line`, `end`, `member`, `law`, `car`, `city`, `community`, `name`, `president`, `team`, `minute`, `idea`, `kid`, `body`, `information`, `back`, `parent`, `face`, `others`, `level`, `office`, `door`, `health`, `person`, `art`, `war`, `history`, `party`, `result`, `morning`, `reason`, `research`, `girl`, `guy`, `moment`, `air`, `teacher`, `force`, `education`.
- Модальные и связки: `can`, `could`, `may`, `might`, `shall`, `should`, `will`, `would`, `must`, `ought`.
- Союзы, предлоги, частицы: `and`, `or`, `but`, `if`, `then`, `so`, `because`, `while`, `as`, `than`, `though`, `although`, `when`, `where`, `why`, `how`, `of`, `in`, `on`, `at`, `to`, `from`, `by`, `for`, `with`, `about`, `into`, `through`, `over`, `under`, `between`, `after`, `before`, `during`, `without`, `within`, `up`, `down`, `out`, `off`, `above`, `below`.
- Числа словами: `one`, `two`, `three`, ..., `twenty`, `hundred`, `thousand`, `million`.
- Дни / месяцы (строчные): `monday`...`sunday`, `january`...`december`.
- Частотные наречия: `not`, `no`, `yes`, `very`, `too`, `also`, `just`, `only`, `even`, `still`, `already`, `again`, `now`, `here`, `there`, `well`, `often`, `always`, `never`, `sometimes`, `maybe`, `perhaps`, `actually`, `really`.

Не сотни тысяч слов — ~300–350 осмысленных. Курируй руками, не выкачивай чужой список целиком.

### 2. Загрузка STOP_WORDS в `nlp.py`

- Функция `_load_stop_words() -> frozenset[str]` читает `data/stop_words.txt`, нормализует `strip().lower()`, фильтрует пустые и комментарии `#...`.
- Кеш в module-level переменную, загрузка ленивая.

### 3. Правило `translatable`

В `tokenize()` (или в отдельной функции `mark_translatable(tokens) -> None`, которая мутирует токены):

Токен `translatable = True`, если выполнены **все** условия:
1. `pos in {"VERB", "NOUN", "ADJ", "ADV", "PROPN"}`;
2. `lemma.lower() not in STOP_WORDS`;
3. **Спец-правило для AUX**: если `lemma in {"be", "have", "do"}` и `pos == "AUX"` → `translatable = False` (это дублирующая страховка, потому что spaCy обычно и так даёт им `POS=AUX`, но иногда ошибается и ставит `VERB`).

### 4. Тесты в `tests/test_translatable.py`

- `"The cat sat on the mat."` — translatable только `cat`, `sat`, `mat` (и ничего больше). `the`, `on`, `.` — нет.
- `"She whispered an ominous warning."` — translatable `whispered`, `ominous`, `warning`. `she`, `an` — нет.
- **AUX-дедупликация:** `"I have eaten."` — `have` не translatable (AUX), `eaten` translatable.
- `"I have a book."` — `have` **translatable** (здесь оно с смыслом «иметь», POS=VERB, lemma `have` в STOP_WORDS? — **да**, мы держим `have` в STOP_WORDS как шумное слово; убедись что это консистентно с списком).
  - Важно: `have` всегда в STOP_WORDS, чтобы не подчёркивалось в обоих ролях. Это сознательная упрощённая стратегия MVP.
- `"was walking"` — `was` не translatable, `walking` translatable.

---

## Технические детали и ловушки

- **spaCy отличает AUX от VERB самостоятельно** в большинстве случаев. Спец-правило нужно именно как подстраховка от случаев, где модель ошиблась. Не пытайся переизобрести определение AUX через dep_.
- **Регистр**: сравнение в STOP_WORDS — по `lemma.lower()`. Спецсимволы (апостроф) в леммах spaCy уже нормализует.
- **Не усложняй.** Никаких «умных» правил вроде «если слово встречается в тексте > N раз — не переводимо». Только детерминированный фильтр POS + STOP_WORDS + AUX.
- **STOP_WORDS в git.** Файл курируется вручную, под контролем версий.
- **Не меняй контракты `Token` и `tokenize` из 1.1.** Только заполняй `translatable`.

---

## Acceptance

- [ ] `data/stop_words.txt` есть в репо, содержит ~300 лемм, без дублей.
- [ ] `tokenize()` (или сопутствующая функция) проставляет `translatable` согласно правилам.
- [ ] Все тесты из раздела «4. Тесты» зелёные.
- [ ] Существующие тесты из 1.1 не сломаны.
- [ ] `ruff`/`black` зелёные.

---

## Что сдавать

- Ветка `task/M1-2-stop-words-translatable`, PR в main.
- В описании PR — что сделано, команды проверки.

---

## Что НЕ делать

- Никаких MWE (1.3) и phrasal verbs (1.4) — их пишут отдельно.
- Не трогай контракты `Token`, `Unit`.
- Не добавляй эндпоинты, БД, фронт.
- Не разрастайся в 3000-строчный STOP_WORDS — нужен курируемый список, а не «все a1-a2 слова интернета». Короткий и осознанный.
