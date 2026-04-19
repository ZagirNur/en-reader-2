# Задача M9.2 — Экран библиотеки

**Размер.** M (~2 дня)
**Зависимости.** M9.1 (GET /api/books, DELETE /api/books/{id}).
**Что строится поверх.** M9.3 (шапка читалки с кнопкой назад), M12.4 (реальный upload через карточку +), M10.5 (redirect с `/` в книгу).

---

## О проекте (контекст)

**en-reader** — веб-читалка. Главный экран — сетка обложек «как магазин книг»: 2 колонки на мобильном, 3 на планшете, 4 на десктопе. Последняя карточка всегда — большая пунктирная «+ Добавить книгу». Удаление — через контекстное меню карточки.

На M9 кнопка «+» делает `console.log` или показывает placeholder — реальный upload будет в M12.4.

---

## Что нужно сделать

Сверстать экран библиотеки, подключить к API, ручная проверка на разных экранах.

---

## Что входит

### 1. View `renderLibrary()`

- Загружает `/api/books`.
- Рендерит `<main class="library"><div class="grid">...</div></main>`.
- Карточки:
  - Обложка или заглушка (`<div class="cover-placeholder">`).
  - Title (2 строки с ellipsis).
  - Author (1 строка).
- Последняя карточка — `<button class="card add-card">+<br>Добавить книгу</button>`.
- Если книг нет — только add-card по центру + подсказка.

### 2. CSS

```css
.library { max-width: 1200px; margin: 0 auto; padding: 2rem 1rem; }
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}
@media (min-width: 768px) { .grid { grid-template-columns: repeat(3, 1fr); } }
@media (min-width: 1200px) { .grid { grid-template-columns: repeat(4, 1fr); } }

.card {
  aspect-ratio: 2 / 3;
  background: #f4f1ea;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  position: relative;
}
.card:hover { transform: translateY(-2px); transition: transform 120ms; }
.card .cover { width: 100%; flex: 1; object-fit: cover; }
.card .cover-placeholder { flex: 1; display: flex; align-items: center; justify-content: center; color: #aaa; font-size: 2rem; }
.card .meta { padding: 0.5rem; background: white; }
.card .title {
  font-weight: bold; font-size: 0.9rem;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.card .author { color: #666; font-size: 0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.add-card {
  aspect-ratio: 2 / 3;
  border: 2px dashed #bbb;
  background: transparent;
  font-size: 1.5rem;
  color: #777;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  cursor: pointer;
}
.add-card:hover { border-color: #555; color: #333; }

.library-empty { min-height: 60vh; display: flex; align-items: center; justify-content: center; }
```

### 3. Клик по карточке книги

- `navigate(`/books/${book.id}`)` — переход на reader.
- До M10.5 — просто переход; в M10.5 добавится set-current-book.

### 4. Клик по карточке `+`

- На M9 — `console.log("upload placeholder")` или показать toast «upload coming soon».
- В M12.4 — откроет file picker.

### 5. Контекстное меню на карточке книги

- **Desktop**: правый клик (`contextmenu`) на карточке → popup с «Удалить».
- **Mobile**: долгий тап (≥ 500 мс) → тот же popup.
- Popup: simple absolute div с одной кнопкой «Удалить». Клик по кнопке → `confirm("Удалить книгу?")` → `DELETE /api/books/{id}` → обновить state (убрать из списка).
- Клик вне popup — закрыть popup.

### 6. Обновление `index.html`

- Поменять `<title>` на «Библиотека — en-reader».
- Убрать старые заглушки из M3.2.

### 7. Ручная проверка

- На чистой БД → экран «пусто, + по центру».
- После seed 3 книг → сетка из 3 + `+` (четвёртая ячейка).
- На 360 px — 2 колонки. На 768 — 3. На 1400 — 4.
- Контекстное меню + удаление работает.
- Удаление последней книги возвращает empty state.

---

## Технические детали и ловушки

- **`aspect-ratio: 2/3`** — стандартное соотношение книжной обложки. Поддерживается во всех современных браузерах.
- **`-webkit-line-clamp`** — Chrome/Safari/Firefox 91+. Для совместимости — оставь.
- **Долгий тап mobile**. `touchstart` → таймер 500 мс → если за это время не было `touchmove` / `touchend` — показать меню.
- **Обложки отсутствуют до M12.** Рендери placeholder пока.
- **`navigate()` из M3.2** — использовать его, не `location.href =` (чтобы не перезагружалось).

---

## Acceptance

- [ ] Сетка на 360/768/1200 px — 2/3/4 колонки.
- [ ] Карточка книги ведёт на `/books/{id}`.
- [ ] Карточка `+` — placeholder (console.log).
- [ ] Контекстное меню удаляет книгу (desktop и mobile).
- [ ] Empty state — большая `+` по центру.
- [ ] После удаления карточка исчезает без перезагрузки.

---

## Дизайн

Эталон — [`tasks/_assets/design/prototype.html`](./_assets/design/prototype.html), функция `ScreenLibrary`. Токены — [`design-spec.md`](./_assets/design/design-spec.md).

Что обязательно из дизайна:
- Header: маленький `.uplabel "Вторник · 9:41"` → `h1 "Моя полка"` 30 px 600 letter-spacing -0.02em + аватарка-буква (38×38, `.card` с `border-radius: 20px`).
- **Streak-card** (огонь-иконка 32×32 на акцентом фоне + «N дней подряд» + counters) — отдельная задача M19.1, но место в вёрстке предусмотри.
- Block «Продолжить чтение»: большая `.card` со скруглением 18 px, обложка 86 px, title 19 px 600, author 12 px `var(--ink-2)`, мета «гл. N · XX % прочитано», `.pbar`, кнопка `btn primary sm` «Читать дальше».
- `.uplabel "Библиотека"` + счётчик книг.
- Grid **3 колонки** (не 2/3/4 как я раньше писал): `grid-template-columns: repeat(3, 1fr); gap: 14px; rowGap: 22px`. Обложки маленькие, под каждой мелкий title + `level · %` + tiny pbar (height 2 px).
- Обложки — градиентные пресеты из design-spec (M16.1).
- Карточка `+ Добавить` — см. M12.4. В дизайне отдельного тайла `+` не показано: add-flow уведём в action-кнопку; согласуй с M12.4.

Mobile-first: вся вёрстка считается на 390 px viewport, на десктопе max-width 720 px centered (как телефон-рамка в прототипе).

---

## Что сдавать

- Ветка `task/M9-2-library-screen`, PR в main.
- Скриншоты light/dark на двух размерах — в описании PR.

---

## Что НЕ делать

- Не реализуй upload (**M12.4**).
- Не добавляй sort/filter/search.
- Не пиши backend — он в M9.1.
- Не изобретай статусы «непрочитано / в процессе / дочитано» — позже.
