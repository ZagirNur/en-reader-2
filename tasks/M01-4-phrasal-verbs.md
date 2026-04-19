# Задача M1.4 — Фразовые глаголы (contiguous + split)

**Размер.** M (~2 дня)
**Зависимости.** M1.1, M1.2, M1.3.
**Что строится поверх.** M1.5 (golden-тесты), M3.3/M4.2 (фронт знает про `pair_id` чтобы скрывать частицу разрывного PV).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Фразовые глаголы — одна из самых важных вещей для пользователя: `look up` (поискать) значит не то же, что `look` + `up` отдельно. Kindle не справляется с этим; мы обязаны.

Фразовые глаголы бывают двух форм:
- **Contiguous**: `look up the word` — глагол и частица рядом.
- **Split**: `look the word up` — между ними слова, но частица синтаксически привязана к глаголу (dependency-парсер видит связь `prt`).

Для UX: при клике по глаголу в split-форме мы показываем русский перевод и **скрываем частицу в DOM** (она уже покрыта переводом). Это возможно только если разметка сразу связывает разнесённые части через `pair_id`.

---

## Что нужно сделать

Реализовать детекцию фразовых глаголов в обеих формах. Создавать `Unit` с корректным `kind`, проставлять `pair_id` для разнесённых форм.

---

## Что входит

### 1. Файл `data/phrasal_verbs.txt`

Курируемый словарь, ~1500–2500 записей. По одной на строку, формат `verb particle`, нижний регистр.

Частые частицы: `up`, `down`, `in`, `out`, `on`, `off`, `over`, `through`, `away`, `back`, `around`, `along`, `by`.

Категории (не исчерпывающе):
- `look up`, `look over`, `look after`, `look for`, `look into`.
- `give up`, `give away`, `give back`, `give in`, `give out`.
- `put up`, `put off`, `put on`, `put out`, `put down`, `put away`.
- `take off`, `take on`, `take out`, `take over`, `take back`, `take down`.
- `turn on`, `turn off`, `turn up`, `turn down`, `turn around`, `turn into`.
- `make up`, `make out`, `make over`.
- `break down`, `break up`, `break in`, `break out`, `break through`.
- `get up`, `get down`, `get off`, `get over`, `get through`, `get by`, `get away`.
- И десятки других: `find out`, `hand over`, `hold on`, `hold up`, `set up`, `call off`, `call up`, `carry out`, ...

Curated — качай из одного-двух открытых источников, потом сам проходишь и выкидываешь мусор.

### 2. Загрузка словаря

- `_load_phrasal_verbs() -> set[tuple[str, str]]` — из `data/phrasal_verbs.txt`.

### 3. Детекция contiguous формы

- Идём по токенам по порядку. Если `tokens[i].pos == "VERB"` и `tokens[i+1]` подходит под «частицу» и пара `(tok[i].lemma, tok[i+1].lemma)` в словаре → создать `Unit kind="phrasal"` с двумя token_ids.
- «Подходит под частицу»: `tokens[i+1].pos in {"ADP", "ADV", "PART"}` или dep_ в `{"prt", "prep", "advmod"}`. Для контига главное — сам лексический матч, dep можно не проверять.

### 4. Детекция split формы

- Это случай: между глаголом и частицей есть другие токены, но частица синтаксически привязана к глаголу.
- spaCy дает `token.dep_ == "prt"` для verb particle, и `token.head` указывает на глагол.
- Логика:
  1. Для каждого токена `t` с `dep_ == "prt"`: пусть `v = t.head`.
  2. Если `t.i > v.i + 1` (не соседний справа) **и** `(v.lemma, t.lemma)` ∈ словаре → split PV.
  3. Создать **две Unit** (`kind="split_phrasal"`):
     - Unit1: token_ids=[v.i], lemma=`v.lemma + " " + t.lemma`, is_split_pv=True, pair_id=N.
     - Unit2: token_ids=[t.i], lemma=`v.lemma + " " + t.lemma`, is_split_pv=True, pair_id=N.
  4. `pair_id` — общий инкрементируемый int (отдельный счётчик для pair_id).

Почему две Unit, а не одна: потому что они разнесены в тексте и каждая имеет свой непрерывный token range. Unit в нашей модели покрывает один непрерывный диапазон.

### 5. Приоритеты

Если MWE, phrasal и split одновременно претендуют на те же токены:
1. MWE > phrasal > split_phrasal.
2. Внутри одного приоритета — greedy longest, затем по позиции.

На практике MWE не будут пересекаться с phrasal (у нас разные словари), но на всякий случай закрепи порядок в коде.

### 6. Интеграция в `analyze(text)`

В функции `analyze()` (из 1.3) после MWE-прохода:
1. Пройти contiguous phrasal.
2. Пройти split phrasal.
3. Не затрагивать токены, уже помеченные `unit_id`.

### 7. Тесты `tests/test_phrasal_verbs.py`

- `"He looked up the word."` → один Unit kind="phrasal", token_ids=[1,2] (looked, up).
- `"He looked the word up."` → два Unit kind="split_phrasal" с одинаковым pair_id.
- `"He gave up smoking."` → один Unit phrasal.
- `"He gave it up."` → два Unit split_phrasal с pair_id.
- `"He looked at the book."` → **не** phrasal (at — предлог, не particle; dep_="prep", не "prt"). Ни одного Unit kind phrasal/split_phrasal.
- Приоритет: `"in order to look up the word"` — MWE `in order to` + phrasal `look up`, оба Unit, не пересекаются.
- Инвариант: для каждой split-пары — оба Unit имеют одинаковый pair_id и `is_split_pv=True`, эти pair_id уникальны по парам.

---

## Технические детали и ловушки

- **dep_=="prt"** — основной сигнал. spaCy парсер проставляет его точно (особенно для глаголов с явной частицей).
- **«Соседство»**: contig матчится по индексам токенов `tokens[i], tokens[i+1]`. Пробельные токены бывают? В en_core_web_sm нет — пробелы не токены.
- **Предлог vs частица**: в `look at` — `at` это prep, dep_="prep", head=look. Это **не** phrasal для наших целей. Строго `dep_=="prt"`.
- **Формы глагола**: `looked`, `looking`, `looks` — всё это lemma `look`. Сравнение в словаре — по **lemma**, не по тексту.
- **Не создавай Unit для одиночных тех же глаголов**: если `look` встретился без частицы — он может быть обычный translatable, это поведение уже из 1.2.
- **pair_id — отдельный счётчик** от Unit.id.

---

## Acceptance

- [ ] `data/phrasal_verbs.txt` в репо, 1500–2500 записей.
- [ ] Contiguous PV создают один Unit.
- [ ] Split PV создают два Unit с общим pair_id.
- [ ] `look at` не создаёт phrasal Unit.
- [ ] MWE имеют приоритет над phrasal при конфликте.
- [ ] Все тесты `test_phrasal_verbs.py` зелёные.
- [ ] Инварианты (Units не пересекаются, каждый token в ≤1 Unit) зелёные на объединённой фикстуре.
- [ ] Тесты из 1.1–1.3 не сломаны.

---

## Что сдавать

- Ветка `task/M1-4-phrasal-verbs`, PR в main.

---

## Что НЕ делать

- Не включай в словарь «полу-phrasal» типа `look at` — это ломает качество разметки.
- Не пытайся объединить две split Unit в одну с двумя диапазонами — модель Unit = один диапазон, это намеренное упрощение.
- Не трогай фронт, LLM, БД.
