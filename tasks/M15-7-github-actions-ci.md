# Задача M15.7 — GitHub Actions CI

**Размер.** S (~1 день)
**Зависимости.** M15.1–M15.6.
**Что строится поверх.** Автоматический прогон всех тестов на каждый PR + блокировка merge в main при красном.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Без CI красные тесты не ловятся — автор думает «я же локально прогнал», а оказывается локально pytest-config отличался. Nice-to-have → must-have: CI в GitHub Actions, required check для merge в main.

---

## Что нужно сделать

Workflow с lint + unit + integration + e2e, ветка branch protection.

---

## Что входит

### 1. `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: black --check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: python -m spacy download en_core_web_sm
      - run: pytest tests/ --ignore=tests/e2e -v --cov=src/en_reader --cov-report=term-missing

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: python -m spacy download en_core_web_sm
      - run: playwright install --with-deps chromium
      - run: pytest tests/e2e -v
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: e2e-artifacts
          path: |
            test-results/
            videos/
```

### 2. pyproject dev-extra

```toml
[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
    "pytest-playwright",
    "ruff",
    "black",
]
```

### 3. Branch protection

В GitHub settings → Branches → main:
- Require pull request before merging.
- Require status checks to pass: `lint`, `test`, `e2e`.
- Require branches to be up to date before merging.

(Делает админ репозитория; в задачу входит документация в `CONTRIBUTING.md`.)

### 4. Badge в README

```markdown
[![CI](https://github.com/YOUR_ORG/en-reader/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_ORG/en-reader/actions/workflows/ci.yml)
```

### 5. `CONTRIBUTING.md`

```markdown
# Contributing

1. Создай ветку `task/Mx-y-название`.
2. Делай PR в main.
3. CI должен быть зелёным. Если красный — исправляй до merge.
4. Ветка должна быть up-to-date с main.
5. Review: один аппрув от тимлида.

## Локальный запуск тестов

    pip install -e ".[dev]"
    python -m spacy download en_core_web_sm
    pytest tests/ --ignore=tests/e2e
    playwright install --with-deps chromium
    pytest tests/e2e
```

### 6. Ручная проверка

- Создай ветку с заведомо красным тестом → PR → CI красный → merge заблокирован.
- Исправь → CI зелёный → merge доступен.

---

## Технические детали и ловушки

- **Кеш pip**. `cache: pip` в setup-python — ускоряет повторные запуски.
- **spaCy модель кешировать сложно** — быстрее просто скачивать (~5 с).
- **Playwright install --with-deps** — ставит все нужные системные библиотеки для Chromium.
- **Time budget CI**. Цель ≤ 8 минут. Lint ~30 с; test ~2 мин; e2e ~3–5 мин.
- **Concurrency cancel**. Добавь для экономии compute:
  ```yaml
  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true
  ```

---

## Acceptance

- [ ] Workflow запускается на каждый push / PR.
- [ ] Все 3 job'а (lint, test, e2e) зелёные на main.
- [ ] Branch protection настроен.
- [ ] Badge в README.
- [ ] CONTRIBUTING.md.
- [ ] Время прогона ≤ 8 минут.

---

## Что сдавать

- Ветка `task/M15-7-github-actions-ci`, PR в main.
- В описании — ссылка на успешный CI-run.

---

## Что НЕ делать

- Не настраивай self-hosted runners.
- Не автоматизируй deploy — у нас autopull.
- Не публикуй в PyPI.
