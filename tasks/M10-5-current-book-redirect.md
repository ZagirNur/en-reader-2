# Задача M10.5 — Current-book и redirect-flow

**Размер.** S (~1 день)
**Зависимости.** M10.1 (progress), M10.2 (восстановление), M9.2 (библиотека), M9.3 (кнопка «← Библиотека»).
**Что строится поверх.** M11.1 (миграция `current_book_id` в `users`).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Пользователь закрыл вкладку в середине книги → следующий заход на домен открывает **ту же книгу** на том же месте. Нажал «← Библиотека» → следующий заход открывает **библиотеку** (пользователь явно решил, что закончил читать на сегодня).

Реализация — одна булевская-ишь переменная «current_book_id». Ставится на открытии книги, сбрасывается на клик «назад», не трогается при простом закрытии вкладки.

На M10 её хранилище — таблица `meta` (`key="current_book_id"`). В M11.1 переедет на `users.current_book_id`.

---

## Что нужно сделать

API get/set current-book, интеграция с открытием книги и «← Библиотека», редирект с `/` в книгу при наличии.

---

## Что входит

### 1. Хранение в `meta`

Никакой миграции — таблица `meta` уже есть. Ключ `current_book_id`, value — число как строка или пустая строка (null).

Storage:
```python
def current_book_get() -> int | None:
    conn = get_db()
    row = conn.execute("SELECT value FROM meta WHERE key='current_book_id'").fetchone()
    if not row or not row["value"]:
        return None
    return int(row["value"])

def current_book_set(book_id: int | None) -> None:
    val = str(book_id) if book_id else ""
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('current_book_id', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (val,)
        )
```

### 2. Роуты

```python
@app.get("/api/me/current-book")
def get_current_book():
    return {"book_id": storage.current_book_get()}

class CurrentBookIn(BaseModel):
    book_id: int | None

@app.post("/api/me/current-book", status_code=204)
def set_current_book(p: CurrentBookIn):
    if p.book_id is not None:
        if not storage.book_meta(p.book_id):
            raise HTTPException(404)
    storage.current_book_set(p.book_id)
```

### 3. Фронт — интеграция

#### 3a. Открытие книги

В `renderReader(bookId)` после успешной загрузки первой страницы:
```js
apiPost("/api/me/current-book", {book_id: bookId}).catch(() => {});
```

(Асинхронно, не ждём.)

#### 3b. Кнопка «← Библиотека»

В M9.3 хендлер был просто `navigate("/")`. Заменить на:
```js
backBtn.addEventListener("click", async () => {
  await apiPost("/api/me/current-book", {book_id: null}).catch(() => {});
  navigate("/");
});
```

#### 3c. Редирект с `/`

В главной точке входа SPA (bootstrap после `setState({route: location.pathname})`):

```js
async function bootstrap() {
  setState({view: "loading"});
  const {book_id} = await apiGet("/api/me/current-book");
  if (book_id && location.pathname === "/") {
    navigate(`/books/${book_id}`);
    return;
  }
  // обычная маршрутизация
  setState({view: parseRoute(location.pathname).view, ...});
}
```

Важно: редирект только если `location.pathname === "/"`. Если пользователь пришёл по прямой ссылке `/books/5` — не перенаправляем.

### 4. Clearing current-book в других случаях

- При удалении книги (M9.1 DELETE) — если удалили current-book, `meta.current_book_id` становится null. Добавь это в `book_delete`:
  ```python
  if current_book_get() == book_id:
      current_book_set(None)
  ```

### 5. Acceptance-сценарий resume

1. Seed книгу, открыть `/books/1`, проскроллить на страницу 37 offset 0.5.
2. Закрыть вкладку (крестик).
3. Открыть `localhost:8000/` → моментальный редирект на `/books/1`.
4. После restoring → viewport на странице 37 середине.
5. Нажать «← Библиотека» → library.
6. Обновить `/` → **библиотека**, не книга.

### 6. Тесты `tests/test_current_book.py`

- `POST current-book {book_id: 1}` → `GET` возвращает `{book_id: 1}`.
- `POST {book_id: null}` → `GET` возвращает `{book_id: null}`.
- `POST {book_id: 999}` (несуществующая) → 404.
- Удаление книги, которая current-book → current-book становится null.

---

## Технические детали и ловушки

- **Race при открытии книги**. Если пользователь быстро переключается между книгами — порядок POST-ов может прийти не в том порядке. Для MVP — игнорируем; в проде — опционально добавить монотонный timestamp.
- **Редирект только с `/`**. Не редиректи из `/login`, `/reader`, `/books/X`.
- **`current_book_get()` в /content**. НЕ зависит — этот роут работает по book_id из URL, current-book здесь не участвует.
- **beforeunload**. Не ставь `current_book_id = null` при закрытии вкладки. Важное отличие от M10.4: прогресс пишется всегда, current-book меняется только явными действиями.

---

## Acceptance

- [ ] `POST /api/me/current-book {book_id: N}` ставит, `GET` возвращает.
- [ ] При открытии книги — POST current-book отправляется.
- [ ] При клике «← Библиотека» — POST `null` + переход.
- [ ] При заходе на `/` с установленным current-book — редирект в `/books/{id}`.
- [ ] При заходе на `/` без current-book — библиотека.
- [ ] Удаление current-book обнуляет её.
- [ ] Сценарий resume (шаги 1–6 выше) отработал глазами.
- [ ] Тесты `test_current_book.py` зелёные.

---

## Что сдавать

- Ветка `task/M10-5-current-book-redirect`, PR в main.
- GIF «открыл → проскроллил → закрыл → открыл → на том же месте» — в описании.

---

## Что НЕ делать

- Не мигрируй на `users.current_book_id` (**M11.1**).
- Не реализуй «список недавно открытых» — только одна текущая.
- Не изобретай TTL для current-book (месяц назад открывал — всё равно редиректим).
