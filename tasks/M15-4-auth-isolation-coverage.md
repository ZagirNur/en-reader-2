# Задача M15.4 — Покрытие auth и изоляции

**Размер.** S (~1 день)
**Зависимости.** M11.2, M11.3, M14.3.
**Что строится поверх.** Защита от регрессий в мультипользовательской модели.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Auth-слой — самый чувствительный к регрессиям: один кривой коммит, и книги одного пользователя видит другой. Нужно систематическое покрытие.

---

## Что нужно сделать

Полные тесты signup/login/logout/me + session persistence + rate-limit + изоляция.

---

## Что входит

### 1. test_auth.py (расширить из M11.2)

- **signup happy**: 200, session cookie, `/auth/me` возвращает email.
- **signup с занятым email**: 409.
- **signup с пустым email**: 422.
- **signup с password < 8**: 422.
- **signup с кривым email** (`"notanemail"`): 422.
- **signup нормализует email**: `TEST@EXAMPLE.COM` → сохраняется как `test@example.com`, повторный signup с `test@example.com` → 409.
- **login happy**.
- **login неверный пароль**: 401.
- **login несуществующий email**: 401 (timing одинаковый).
- **logout очищает сессию**: `/auth/me` → 401 после.
- **bcrypt 72-byte truncate**: пароль 100+ символов → login работает.
- **placeholder hash** (seed-user из M11.1) → check_password всегда False.

### 2. test_session_persistence.py

- Создать app 1, signup, получить cookie.
- Создать app 2 с тем же SECRET_KEY (через monkeypatch на `_secret_key()`).
- Послать запрос с cookie из app 1 в app 2 → `/auth/me` возвращает email.
- Проверяет «сессия переживает рестарт».

### 3. test_isolation.py (из M11.3 расширить)

- Юзеры A, B.
- A не видит книги B: `GET /api/books` A не содержит B-книг.
- A не читает content B: `GET /api/books/{B_id}/content` → 404.
- A не удаляет B: `DELETE /api/books/{B_id}` → 404.
- A не видит словарь B: `GET /api/dictionary` A не содержит B-слов.
- A не пишет словарь B: (CSRF через POST translate неявно — переведённое A не попадает в B-dict).
- A не пишет прогресс B: `POST /api/books/{B_id}/progress` → 404.
- A не видит current-book B.
- A не качает cover B: 404.
- A не качает images B: 404.

### 4. test_ratelimit.py (из M14.3)

- 10 login за минуту с одного IP — 11-й 429.
- После минуты окна — снова разрешено (monkeypatch `time.time`).
- 60 translate за минуту одним user — 61-й 429.
- Разные юзеры — каждый свой счётчик.
- 5 uploads за час одним user — 6-й 429.

### 5. Ковёр coverage

≥ 90% для `auth.py`, ratelimit-модуля, auth-роутов в `app.py`.

---

## Технические детали и ловушки

- **X-Forwarded-For в тестах**. `TestClient` не шлёт XFF по умолчанию. Для rate-limit-тестов с разными IP — устанавливай заголовок вручную: `client.post(..., headers={"X-Forwarded-For": "1.2.3.4"})`.
- **ProxyHeadersMiddleware** должен быть активен, чтобы тест видел поддельный IP.
- **Монотонное время**. `monkeypatch.setattr("time.time", lambda: NEXT_TICK[0])` где `NEXT_TICK` — list (nonlocal).

---

## Acceptance

- [ ] Coverage auth ≥ 90%.
- [ ] Все isolation-тесты зелёные.
- [ ] Session-persistence тест зелёный.
- [ ] Rate-limit тесты зелёные с mocked time.

---

## Что сдавать

- Ветка `task/M15-4-auth-isolation-coverage`, PR в main.

---

## Что НЕ делать

- Не тестируй bcrypt внутренности.
- Не реализуй real-time мониторинг сессий.
