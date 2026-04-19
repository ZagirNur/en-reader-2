# Задача M15.6 — E2E через Playwright

**Размер.** M (~2 дня)
**Зависимости.** M12.4 (upload UI), M10.5 (resume).
**Что строится поверх.** Реальный браузерный тест критических сценариев.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Unit/integration тесты проверяют API, но не проверяют, что кнопки кликаются, скролл работает, перевод появляется inline. Для двух самых критичных сценариев нужен настоящий браузер.

**Playwright** поверх Chromium и WebKit — наш выбор. Python API, интегрируется в pytest через `pytest-playwright`.

---

## Что нужно сделать

Два E2E-теста: (1) signup → upload → read → click → inline, (2) resume-flow.

---

## Что входит

### 1. Установка

```
pip install pytest-playwright
playwright install chromium webkit
```

В pyproject — `dev` группа deps.

### 2. Инфраструктура

`tests/e2e/conftest.py`:
```python
import subprocess, time
import pytest
import requests

@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """Поднимает uvicorn на 8765, с изолированной БД."""
    db_path = tmp_path_factory.mktemp("e2e") / "e2e.db"
    env = os.environ.copy()
    env["DB_PATH"] = str(db_path)
    env["GEMINI_API_KEY"] = "fake"
    # стаб translate_one через env переменную или pre-seeded словарь
    env["E2E_MOCK_LLM"] = "1"

    proc = subprocess.Popen(
        ["uvicorn", "en_reader.app:app", "--host", "127.0.0.1", "--port", "8765"],
        env=env,
    )
    # wait until ready
    for _ in range(20):
        try:
            if requests.get("http://127.0.0.1:8765/debug/health").ok:
                break
        except: pass
        time.sleep(0.5)
    yield "http://127.0.0.1:8765"
    proc.terminate()
```

В приложении: если `E2E_MOCK_LLM=1` — `translate_one` возвращает `f"RU:{unit_text}"` без реального вызова.

### 3. Тест 1: signup → upload → read → click → inline

```python
def test_e2e_full_flow(page, live_server):
    page.goto(f"{live_server}/login")

    # signup
    page.click("#auth-switch")
    page.fill("[name=email]", "e2e@test.com")
    page.fill("[name=password]", "12345678")
    page.click("button[type=submit]")
    expect(page).to_have_url(f"{live_server}/")

    # upload (через file chooser)
    with page.expect_file_chooser() as fc_info:
        page.click(".add-card")
    fc = fc_info.value
    fc.set_files("tests/fixtures/parsers/sample_utf8.txt")

    # ждём появления reader
    page.wait_for_selector(".page-body", timeout=15000)

    # клик по translatable
    first_tr = page.locator(".translatable").first
    word = first_tr.inner_text()
    first_tr.click()

    # появился .ru-tag
    ru_tag = first_tr.locator(".. >> .ru-tag").first   # sibling — уточни селектор
    expect(ru_tag).to_be_visible(timeout=5000)
    assert ru_tag.inner_text().startswith("RU:")
```

### 4. Тест 2: resume

```python
def test_e2e_resume(page, live_server):
    # signup
    page.goto(f"{live_server}/login")
    page.click("#auth-switch")
    page.fill("[name=email]", "e2e2@test.com")
    page.fill("[name=password]", "12345678")
    page.click("button[type=submit]")

    # upload текст на 10+ страниц
    with page.expect_file_chooser() as fc_info:
        page.click(".add-card")
    fc_info.value.set_files("tests/fixtures/e2e/long_book.txt")

    page.wait_for_selector(".page-body")

    # проскроллить на середину
    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
    page.wait_for_timeout(2000)   # debounce save

    # закрыть страницу, открыть заново
    page.goto(f"{live_server}/")

    # проверить — редирект в книгу, скролл не в начале
    page.wait_for_selector(".page-body", timeout=5000)
    scroll_y = page.evaluate("window.scrollY")
    assert scroll_y > 500, f"expected resume, got scrollY={scroll_y}"
```

### 5. Прогон в CI

Matrix на Chromium + WebKit.
- Chromium — обязательно.
- WebKit (Safari) — nice-to-have; часто ловит iOS-специфичные баги.

### 6. Артефакты при падении

`--video=retain-on-failure`, `--screenshot=only-on-failure`. Загружать в CI-артефакты при падении.

---

## Технические детали и ловушки

- **Uvicorn subprocess**. Убедись, что останавливается в teardown (не осталось висячих процессов).
- **Headless режим** — по умолчанию. Для локальной отладки `HEADED=1 pytest` с `page.pause()`.
- **Селекторы**. Используй `data-testid` там, где надо стабильности. Добавь нужные `data-testid` во фронт в рамках этой задачи.
- **Флаки из-за animation**. `--reduce-motion` прописать в CSS prod или добавить `@media (prefers-reduced-motion)` в transitions.

---

## Acceptance

- [ ] Оба теста зелёные локально.
- [ ] Оба теста проходят в CI.
- [ ] При падении — скриншот и видео в артефактах.
- [ ] Время обоих тестов ≤ 60 с суммарно.

---

## Что сдавать

- Ветка `task/M15-6-e2e-playwright`, PR в main.
- В описании — видео прохождения.

---

## Что НЕ делать

- Не покрывай все сценарии E2E — это дорого и хрупко. Только два критичных.
- Не дёргай реальный Gemini.
