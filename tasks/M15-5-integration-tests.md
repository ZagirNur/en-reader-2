# Задача M15.5 — Integration-тесты ключевых сценариев

**Размер.** S (~1 день)
**Зависимости.** M15.2, M15.3, M15.4.
**Что строится поверх.** Отлов регрессий на стыках модулей (API + NLP + storage + LLM-мок).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Unit-тесты покрывают модули по отдельности. Integration-тесты проверяют, что модули работают вместе: signup → upload → clicking word → получение перевода inline.

Без E2E-браузера (это M15.6). Здесь — через TestClient, но цепочка запросов полная.

---

## Что нужно сделать

2–3 больших сценария от signup до inline-translation, кросс-книжный перенос словаря.

---

## Что входит

### 1. test_integration_happy_path.py

Сценарий «загрузил и перевёл слово»:

```python
def test_upload_translate_cache(client, mock_llm):
    # 1. Signup.
    r = client.post("/auth/signup", json={"email": "u@u.com", "password": "12345678"})
    assert r.status_code == 200

    # 2. Upload txt.
    txt = "She whispered an ominous warning."
    r = client.post(
        "/api/books/upload",
        files={"file": ("test.txt", txt.encode(), "text/plain")},
    )
    assert r.status_code == 200
    book_id = r.json()["book_id"]

    # 3. Получить content.
    r = client.get(f"/api/books/{book_id}/content?offset=0&limit=1")
    data = r.json()
    assert data["total_pages"] == 1
    # Найти unit с lemma "ominous".
    page = data["pages"][0]
    ominous_unit = next(u for u in page["units"] if u["lemma"] == "ominous")

    # 4. Перевести.
    mock_llm.return_value = "зловещий"
    r = client.post("/api/translate", json={
        "unit_text": "ominous", "sentence": "She whispered an ominous warning.", "lemma": "ominous",
    })
    assert r.status_code == 200
    assert r.json()["ru"] == "зловещий"
    assert mock_llm.call_count == 1

    # 5. Второй раз — без LLM.
    r = client.post("/api/translate", json={
        "unit_text": "ominous", "sentence": "...", "lemma": "ominous",
    })
    assert r.status_code == 200
    assert mock_llm.call_count == 1   # не дёрнули снова

    # 6. Dictionary содержит слово.
    r = client.get("/api/dictionary")
    assert "ominous" in r.json()
```

### 2. test_integration_cross_book.py

Сценарий «словарь работает между книгами»:

```python
def test_cross_book_dictionary(client, mock_llm):
    # signup
    client.post("/auth/signup", json={"email": "u@u.com", "password": "12345678"})

    # upload book A
    mock_llm.return_value = "зловещий"
    book_a = _upload(client, "Text A contains ominous warning.")
    # перевести в книге A
    client.post("/api/translate", json={"unit_text": "ominous", "sentence": "...", "lemma": "ominous"})

    # upload book B
    book_b = _upload(client, "Book B has ominous too.")
    # content книги B
    r = client.get(f"/api/books/{book_b}/content?offset=0&limit=1")
    page = r.json()["pages"][0]
    ominous_unit = next(u for u in page["units"] if u["lemma"] == "ominous")
    # он в auto_unit_ids
    assert ominous_unit["id"] in page["auto_unit_ids"]
    # user_dict содержит перевод
    assert r.json()["user_dict"]["ominous"] == "зловещий"
```

### 3. test_integration_resume.py

Сценарий «закрыл → открыл → продолжил»:

```python
def test_resume_flow(client):
    client.post("/auth/signup", json={"email": "u@u.com", "password": "12345678"})
    book_id = _upload_multipage_book(client)

    # Задать позицию.
    client.post(f"/api/books/{book_id}/progress", json={
        "last_page_index": 3, "last_page_offset": 0.4,
    })
    client.post("/api/me/current-book", json={"book_id": book_id})

    # «Перезапуск» — новый клиент с теми же cookies не нужен, просто GET.
    r = client.get("/api/me/current-book")
    assert r.json()["book_id"] == book_id

    r = client.get(f"/api/books/{book_id}/content?offset=3&limit=1")
    data = r.json()
    assert data["last_page_index"] == 3
    assert data["last_page_offset"] == 0.4
```

### 4. Фикстуры

`client` — TestClient (не authed, но свежая БД).
`mock_llm` — monkeypatch `translate.translate_one`.
`_upload(client, text)` — helper: POST txt файла, возвращает book_id.
`_upload_multipage_book(client)` — текст с ≥ 5 страниц (много предложений).

---

## Технические детали и ловушки

- **Вся цепочка через HTTP**. Никаких прямых вызовов storage — только через API.
- **mock_llm через pytest-mock** или `monkeypatch.setattr`.
- **Порядок запросов важен**. Integration-тест — последовательный сценарий.

---

## Acceptance

- [ ] 3 integration-теста зелёные.
- [ ] Каждый проверяет цепочку ≥ 4 шагов.
- [ ] Никаких реальных LLM-вызовов.
- [ ] Время прогона ≤ 10 с для всех.

---

## Что сдавать

- Ветка `task/M15-5-integration-tests`, PR в main.

---

## Что НЕ делать

- Не делай E2E через Playwright (**M15.6**).
- Не копируй unit-тесты — интеграция это другое.
- Не дёргай реальную Gemini.
