# Задача M16.2 — Bottom sheet + toast + tab bar (шаред-компоненты)

**Размер.** M (~2 дня)
**Зависимости.** M16.1.
**Что строится поверх.** M4.2, M9.3, M17.x, M18.x — все, кто использует sheet/toast/tabbar.

---

## О проекте (контекст)

**en-reader** — веб-читалка. Дизайн требует нескольких общих компонентов, которые появляются на разных экранах:
- **Bottom sheet** со scrim'ом — для word detail (M4.2), reader settings (M9.3), saved word detail (M17.1).
- **Toast** — для коротких нотификаций («В словарь ✓», «Вернули оригинал», «Удалено»).
- **Tab bar** — 4 вкладки внизу, скрывается на ридере.

Делаем их один раз, чисто, с анимациями из дизайна.

---

## Что нужно сделать

Реализовать три компонента с единым API (`openSheet(content)`, `closeSheet()`, `showToast(msg)`, `renderTabBar(active)`), применить токены из M16.1.

---

## Что входит

### 1. Разметка (общий shell)

Добавить в `index.html` после `#root`:
```html
<div class="scrim" id="scrim"></div>
<div class="sheet" id="sheet"></div>
<div class="toast" id="toast"></div>
<nav class="tabbar" id="tabbar"></nav>
```

### 2. CSS

```css
/* scrim */
.scrim {
  position: fixed; inset: 0; z-index: 90;
  background: rgba(0,0,0,0.32);
  opacity: 0; pointer-events: none;
  transition: opacity 0.2s;
}
.scrim.show { opacity: 1; pointer-events: auto; }

/* sheet */
.sheet {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 100;
  background: var(--card);
  border-top-left-radius: 28px; border-top-right-radius: 28px;
  padding: 16px 22px 28px;
  transform: translateY(100%);
  transition: transform 0.28s cubic-bezier(.2,.9,.3,1);
  box-shadow: 0 -20px 40px -14px rgba(0,0,0,0.35);
  max-width: 720px; margin: 0 auto;
  max-height: 85vh; overflow-y: auto;
}
.sheet.show { transform: translateY(0); }
.sheet .handle {
  width: 40px; height: 4px; border-radius: 2px; background: var(--line);
  margin: 0 auto 16px;
}

/* toast */
.toast {
  position: fixed; top: 20px; left: 50%;
  transform: translate(-50%, -20px);
  background: var(--ink); color: var(--bg);
  padding: 10px 16px; border-radius: 999px;
  font-size: 13px; font-weight: 500;
  opacity: 0; pointer-events: none;
  transition: opacity 0.2s, transform 0.2s;
  z-index: 150;
  box-shadow: 0 10px 24px -8px rgba(0,0,0,0.3);
}
.toast.show { opacity: 1; transform: translate(-50%, 0); }

/* tab bar */
.tabbar {
  position: fixed; bottom: 0; left: 0; right: 0;
  max-width: 720px; margin: 0 auto;
  display: flex; padding: 8px 10px 20px;
  background: color-mix(in oklab, var(--bg) 88%, transparent);
  backdrop-filter: blur(14px);
  border-top: 1px solid var(--line);
  z-index: 80;
}
.tabbar.hidden { display: none; }
.tab {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 8px 0; cursor: pointer; position: relative;
  font-size: 10px; font-weight: 500; color: var(--ink-3);
  background: none; border: none;
  font-family: inherit;
  transition: color 0.15s;
}
.tab.on { color: var(--ink); }
.tab.on .tab-dot {
  position: absolute; bottom: -8px; width: 4px; height: 4px;
  border-radius: 50%; background: var(--accent);
}
.tab svg { width: 22px; height: 22px; }

/* у #root — bottom-padding под tabbar, чтобы последний элемент не резало */
.with-tabbar #root { padding-bottom: 82px; }
```

### 3. API sheet

```js
// components/sheet.js
export function openSheet(contentEl) {
  const sheet = document.getElementById('sheet');
  const scrim = document.getElementById('scrim');
  sheet.innerHTML = '';
  const handle = document.createElement('div');
  handle.className = 'handle';
  sheet.append(handle, contentEl);
  requestAnimationFrame(() => {
    scrim.classList.add('show');
    sheet.classList.add('show');
  });
}
export function closeSheet() {
  document.getElementById('scrim').classList.remove('show');
  document.getElementById('sheet').classList.remove('show');
}
// клик по scrim — закрыть
document.getElementById('scrim').addEventListener('click', closeSheet);
// Esc — закрыть
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
```

Сделать через swipe-down тоже (опционально):
```js
// простой pointer-drag handle; если time позволяет — иначе skip
```

### 4. API toast

```js
let _toastTimer = null;
export function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove('show'), 1600);
}
```

### 5. API tabbar

```js
// Иконки (SVG-строки) — из prototype.html, ImportPool в одном файле components/icons.js.
const TABS = [
  { id: 'lib',   label: 'Мои книги', icon: icons.books },
  { id: 'cat',   label: 'Каталог',   icon: icons.compass },
  { id: 'dict',  label: 'Словарь',   icon: icons.dict },
  { id: 'learn', label: 'Учить',     icon: icons.brain },
];

export function renderTabBar(activeId, onTabClick) {
  const bar = document.getElementById('tabbar');
  bar.innerHTML = '';
  for (const t of TABS) {
    const b = document.createElement('button');
    b.className = 'tab' + (activeId === t.id ? ' on' : '');
    b.innerHTML = t.icon + `<span>${t.label}</span>` + (activeId === t.id ? '<span class="tab-dot"></span>' : '');
    b.addEventListener('click', () => onTabClick(t.id));
    bar.append(b);
  }
}

export function hideTabBar() { document.getElementById('tabbar').classList.add('hidden'); }
export function showTabBar() { document.getElementById('tabbar').classList.remove('hidden'); }
```

### 6. Иконки (SVG)

Положи в `components/icons.js` словарь строк SVG: `books`, `compass`, `dict`, `brain`, `plus`, `chevL`, `chevR`, `star`, `undo`, `settings`, `x`, `fire`, `trend`, `check`. Берёшь из `prototype.html` как есть.

### 7. Прочие

- `handle-swipe-to-dismiss` — опционально. Если добавляешь, не запускай close пока движение < 40 px.
- Sheet с заголовком не нужен — заголовок кладётся в content.
- Scroll внутри sheet с `overflow-y: auto`, `max-height: 85vh`.

### 8. Тесты

Визуальные + unit:
- `openSheet(div) → closeSheet()` — классы переключаются.
- `showToast('X')` → видно X, через 1.6 с скрыто.
- `renderTabBar('lib', cb)` → клик по «Каталог» вызывает cb('cat').
- Esc закрывает sheet.

### 9. Ручная проверка

- На демо-странице 4 кнопки: «Open sheet», «Show toast», «Hide tabbar», «Show tabbar».
- Все работают, анимации плавные в light и dark.

---

## Acceptance

- [ ] `openSheet`, `closeSheet`, `showToast`, `renderTabBar`, `hideTabBar`, `showTabBar` работают.
- [ ] Клик по scrim / Esc — закрывает sheet.
- [ ] Toast автоматически скрывается через 1.6 с.
- [ ] TabBar: кликабельные вкладки, активная со светящейся точкой.
- [ ] В ридере `hideTabBar()` → таббар не виден.
- [ ] Иконки SVG вшиты, в dark-теме они тоже читаются.
- [ ] Анимации в light/dark корректны.

---

## Дизайн

Эталон — [`prototype.html`](./_assets/design/prototype.html) + [`design-spec.md`](./_assets/design/design-spec.md), секции «Bottom sheet», «Toast», «Tab bar», «Иконки».

---

## Что сдавать

- Ветка `task/M16-2-bottom-sheet-toast-tabbar`, PR в main.

---

## Что НЕ делать

- Не подключай сторонние UI-библиотеки типа Headless UI, Radix и т. п.
- Не делай «полноэкранный modal» — у нас bottom sheet.
- Не кладёт content-специфичный код в sheet.js — только контейнер.
