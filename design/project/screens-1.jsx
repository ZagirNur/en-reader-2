// Экраны часть 1: Библиотека, Каталог, Загрузка, Читалка, Попап перевода

// ─── Примеры данных ───
const myBooks = [
  { title: '1984', author: 'Дж. Оруэлл', variant: 1, progress: 42, words: 87 },
  { title: 'Старик\nи море', author: 'Э. Хемингуэй', variant: 3, progress: 78, words: 34 },
  { title: 'Гордость и\nпредубеждение', author: 'Дж. Остин', variant: 4, progress: 15, words: 156 },
  { title: 'Дюна', author: 'Ф. Герберт', variant: 5, progress: 5, words: 12 },
];

const catalogBooks = [
  { title: 'Алиса в\nСтране чудес', author: 'Л. Кэрролл', variant: 6 },
  { title: 'Великий\nГэтсби', author: 'Ф.С. Фицджеральд', variant: 7 },
  { title: 'Франкенштейн', author: 'М. Шелли', variant: 2 },
  { title: 'Дракула', author: 'Б. Стокер', variant: 8 },
  { title: 'Шерлок\nХолмс', author: 'А.К. Дойл', variant: 1 },
  { title: 'Моби Дик', author: 'Г. Мелвилл', variant: 5 },
];

// ─── 1. БИБЛИОТЕКА ───
function ScreenLibrary() {
  return (
    <Phone label="01 — Мои книги" sub="Главный экран. Сетка 2 в ряд, последняя карточка — всегда +">
      <TopBar
        title="Мои книги"
        right={<><Ico>⚙</Ico></>}
      />
      <div className="scroll-area">
        <div style={{ display: 'flex', gap: 8, padding: '0 0 8px' }}>
          <div className="chip filled">Все · 4</div>
          <div className="chip">Читаю · 2</div>
          <div className="chip">Прочитано · 1</div>
        </div>
        <BooksGrid books={myBooks} addLabel="Загрузить книгу" />
      </div>
      <TabBar active="books" />
    </Phone>
  );
}

// ─── 1b. БИБЛИОТЕКА — пусто ───
function ScreenLibraryEmpty() {
  return (
    <Phone label="01b — Пустая библиотека" sub="Первый запуск, книг ещё нет">
      <TopBar title="Мои книги" />
      <div className="scroll-area" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="empty" style={{ marginTop: 60 }}>
          <div style={{ fontSize: 72, fontFamily: 'var(--hand-bold)', color: 'var(--ink-3)', lineHeight: 1 }}>📖</div>
          <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 22, color: 'var(--ink)' }}>
            Полка пока пустая
          </div>
          <div style={{ fontSize: 13, maxWidth: 240 }}>
            Загрузи свою книгу или выбери что-нибудь из каталога, чтобы начать.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <div className="btn primary">+ Загрузить</div>
            <div className="btn">Открыть каталог</div>
          </div>
        </div>
      </div>
      <TabBar active="books" />
    </Phone>
  );
}

// ─── 2. КАТАЛОГ ───
function ScreenCatalog() {
  return (
    <Phone label="02 — Каталог" sub="Книги без лицензии. Та же простая сетка.">
      <TopBar title="Каталог" right={<Ico>⌕</Ico>} />
      <div className="scroll-area">
        <div className="sk-box" style={{ padding: '8px 12px', fontSize: 13, color: 'var(--ink-2)', marginBottom: 12 }}>
          ⌕ Поиск бесплатных книг…
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
          <div className="chip filled">Все</div>
          <div className="chip">A1–A2</div>
          <div className="chip">B1</div>
          <div className="chip">B2+</div>
          <div className="chip">Короткие</div>
        </div>
        <BooksGrid books={catalogBooks} withAdd={false} />
      </div>
      <TabBar active="catalog" />
    </Phone>
  );
}

// ─── 2b. КАТАЛОГ — карточка книги ───
function ScreenCatalogDetail() {
  return (
    <Phone label="02b — Каталог → карточка книги" sub="Тап по книге в каталоге. Добавить в библиотеку.">
      <TopBar left={<Ico>‹</Ico>} right={<Ico>⌕</Ico>} />
      <div className="scroll-area">
        <div style={{ display: 'flex', gap: 14, marginBottom: 14 }}>
          <div style={{ width: 110, flexShrink: 0 }}>
            <BookCover title={'Алиса в\nСтране чудес'} author="Л. Кэрролл" variant={6} />
          </div>
          <div style={{ paddingTop: 6 }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 20, lineHeight: 1.1 }}>
              Алиса в Стране чудес
            </div>
            <div style={{ fontSize: 13, color: 'var(--ink-2)', margin: '4px 0 8px' }}>
              Льюис Кэрролл · 1865
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              <div className="chip">B1</div>
              <div className="chip">~26к слов</div>
            </div>
          </div>
        </div>
        <div style={{ fontSize: 13, lineHeight: 1.5, color: 'var(--ink-2)', marginBottom: 16 }}>
          Алиса падает в кроличью нору и оказывается в фантастическом мире, населённом странными существами…
        </div>
        <div className="btn primary full">+ Добавить в мои книги</div>
        <div style={{ height: 16 }} />
        <div className="btn full">Читать первую главу</div>
      </div>
      <TabBar active="catalog" />
    </Phone>
  );
}

// ─── 3. ЗАГРУЗКА (drop-in) ───
function ScreenUpload() {
  return (
    <Phone label="03 — Загрузка книги" sub="Drop-in: файл → метаданные автоматически. Редактируешь позже.">
      <TopBar left={<Ico>✕</Ico>} title="Загрузка" />
      <div className="scroll-area" style={{ paddingTop: 12 }}>
        <div className="sk-box dashed" style={{
          padding: 32, textAlign: 'center',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
          marginBottom: 16,
        }}>
          <div style={{ fontSize: 40, fontFamily: 'var(--hand-bold)', color: 'var(--ink-2)', lineHeight: 1 }}>↥</div>
          <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 18 }}>
            Выбери файл
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>
            или перетащи сюда
          </div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
            .epub  ·  .fb2  ·  .txt  ·  .mobi
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--ink-2)', textAlign: 'center', padding: '0 20px' }}>
          Название, автора и обложку возьмём автоматически. Всё можно изменить позже в меню книги.
        </div>
      </div>
    </Phone>
  );
}

// ─── 3b. Загрузка — обработка ───
function ScreenUploadProgress() {
  return (
    <Phone label="03b — Обработка файла" sub="Файл выбран. Автоматически разбираем.">
      <TopBar left={<Ico>✕</Ico>} title="Загрузка" />
      <div className="scroll-area">
        <div className="sk-box" style={{ padding: 16, marginTop: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
          <div style={{ width: 48, height: 60, background: 'var(--paper-2)', border: '1.5px solid var(--ink)', borderRadius: 3 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 14 }}>book-name.epub</div>
            <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 6 }}>2.4 МБ</div>
            <div className="progress" style={{ height: 6, background: 'var(--paper-2)', border: '1px solid var(--ink)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: '64%', height: '100%', background: 'var(--accent)' }} />
            </div>
          </div>
        </div>
        <div style={{ marginTop: 18, padding: '0 4px' }}>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span>✓</span> Читаем файл…
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span>✓</span> Нашли название и автора
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span>◐</span> Генерируем обложку…
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>○</span> Разбиваем на главы
          </div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 3c. Меню книги (редактировать обложку/название) ───
function ScreenBookMenu() {
  return (
    <Phone label="03c — Меню книги" sub="Долгий тап по книге → редактировать обложку, название, удалить.">
      <TopBar left={<Ico>‹</Ico>} title="О книге" />
      <div className="scroll-area">
        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0 14px' }}>
          <div style={{ width: 130, position: 'relative' }}>
            <BookCover title="1984" author="Дж. Оруэлл" variant={1} />
            <div style={{
              position: 'absolute', bottom: -6, right: -6,
              background: 'var(--paper)', border: '1.5px solid var(--ink)',
              width: 32, height: 32, borderRadius: '50%',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '1.5px 1.5px 0 var(--ink)',
              fontFamily: 'var(--hand-bold)', fontSize: 14,
            }}>✎</div>
          </div>
        </div>
        <div className="list-row">
          <Ico>✎</Ico>
          <div style={{ flex: 1, fontSize: 14 }}>Изменить название и автора</div>
          <Ico>›</Ico>
        </div>
        <div className="list-row">
          <Ico>⌘</Ico>
          <div style={{ flex: 1, fontSize: 14 }}>Заменить обложку…</div>
          <Ico>›</Ico>
        </div>
        <div className="list-row">
          <Ico>☰</Ico>
          <div style={{ flex: 1, fontSize: 14 }}>Главы / оглавление</div>
          <Ico>›</Ico>
        </div>
        <div className="list-row">
          <Ico>✦</Ico>
          <div style={{ flex: 1, fontSize: 14 }}>Слова из этой книги</div>
          <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>87</span>
        </div>
        <div className="list-row" style={{ color: 'var(--accent)' }}>
          <Ico>×</Ico>
          <div style={{ flex: 1, fontSize: 14 }}>Убрать из библиотеки</div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 4. ЧИТАЛКА — обычный вид ───
function ScreenReader() {
  return (
    <Phone label="04 — Читалка" sub="Слова, на которые ты тапал, заменились на перевод и подсвечены.">
      <TopBar
        left={<Ico>‹</Ico>}
        right={<>
          <Ico>Аа</Ico>
          <Ico>☰</Ico>
        </>}
      />
      <div style={{ padding: '0 18px 10px' }}>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 4 }}>
          Глава 3 · Зал дверей
        </div>
        <div className="progress" style={{ height: 3 }}>
          <div style={{ width: '34%' }} />
        </div>
      </div>
      <div className="scroll-area" style={{ padding: '4px 18px 16px' }}>
        <div className="reader-text">
          <p>
            Alice was beginning to get very <span className="tr-word">уставшей</span> of sitting by her sister on the bank, and of having nothing to do.
          </p>
          <p>
            Once or twice she had <span className="tr-word">заглянула</span> into the book her sister was reading, but it had no pictures or <span className="tr-word">диалогов</span> in it.
          </p>
          <p>
            "And what is the use of a book," thought Alice, "without pictures or <span className="tr-word">диалогов</span>?"
          </p>
          <p>
            So she was considering, in her own mind, whether the pleasure of making a <span className="tr-word">венок</span> of daisies would be worth the trouble of getting up.
          </p>
          <p>
            Suddenly a White Rabbit with pink eyes ran close by her.
          </p>
        </div>
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        padding: '8px 18px 12px', fontSize: 11, color: 'var(--ink-3)',
        borderTop: '1px dashed var(--ink-3)',
      }}>
        <span>стр. 12 / 287</span>
        <span>34%</span>
        <span>~ 14 мин</span>
      </div>
    </Phone>
  );
}

// ─── 4b. ЧИТАЛКА — попап перевода (тап по уже переведённому слову) ───
function ScreenReaderPopup() {
  return (
    <Phone label="04b — Тап по переведённому слову" sub="Попап: подсказка, примеры, отмена перевода.">
      <TopBar left={<Ico>‹</Ico>} right={<><Ico>Аа</Ico><Ico>☰</Ico></>} />
      <div style={{ padding: '0 18px 10px' }}>
        <div className="progress" style={{ height: 3 }}>
          <div style={{ width: '34%' }} />
        </div>
      </div>
      <div className="scroll-area" style={{ padding: '4px 18px 16px', position: 'relative' }}>
        <div className="reader-text">
          <p>
            Alice was beginning to get very <span className="tr-word" style={{ outline: '2px solid var(--accent)', outlineOffset: 2 }}>уставшей</span> of sitting by her sister on the bank.
          </p>
          <p>
            Once or twice she had <span className="tr-word">заглянула</span> into the book her sister was reading.
          </p>
          <div className="tr-popup" style={{ top: 64, left: 24, right: 24 }}>
            <div className="pop-arrow" style={{ left: 64 }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 18 }}>tired</div>
              <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>прил · /ˈtaɪəd/</div>
            </div>
            <div style={{ fontSize: 13, marginBottom: 8 }}>уставший, утомлённый</div>
            <div style={{
              fontSize: 11, color: 'var(--ink-2)',
              borderLeft: '2px solid var(--ink-3)', paddingLeft: 8,
              marginBottom: 10,
            }}>
              "I'm tired of waiting." — Я устал ждать.
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <div className="btn sm">↩ Отменить перевод</div>
              <div className="btn sm primary">✦ В словаре</div>
            </div>
          </div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 4c. ЧИТАЛКА — выделение слова (до перевода) ───
function ScreenReaderSelect() {
  return (
    <Phone label="04c — Тап по незнакомому слову" sub="Слово выделено → подтверждение перевода.">
      <TopBar left={<Ico>‹</Ico>} right={<><Ico>Аа</Ico><Ico>☰</Ico></>} />
      <div style={{ padding: '0 18px 10px' }}>
        <div className="progress" style={{ height: 3 }}><div style={{ width: '34%' }} /></div>
      </div>
      <div className="scroll-area" style={{ padding: '4px 18px 16px', position: 'relative' }}>
        <div className="reader-text">
          <p>
            So she was considering whether the pleasure of making a <span style={{ background: 'rgba(0,0,0,0.12)', borderBottom: '2px dashed var(--ink)', padding: '0 2px' }}>wreath</span> of daisies would be worth the trouble.
          </p>
          <p>
            Suddenly a White Rabbit with pink eyes ran close by her.
          </p>
          <div style={{
            position: 'absolute',
            top: 76, left: '50%', transform: 'translateX(-50%)',
            background: 'var(--ink)', color: 'var(--paper)',
            padding: '8px 14px', borderRadius: 22,
            fontSize: 13, fontFamily: 'var(--hand-bold)',
            display: 'flex', alignItems: 'center', gap: 10,
            boxShadow: '2px 2px 0 var(--ink-2)',
            whiteSpace: 'nowrap',
          }}>
            <span>wreath → венок</span>
            <span style={{ opacity: 0.5 }}>|</span>
            <span style={{ fontSize: 11, opacity: 0.8 }}>перевести везде</span>
          </div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 4d. ЧИТАЛКА — настройки (Аа) ───
function ScreenReaderSettings() {
  return (
    <Phone label="04d — Настройки читалки" sub="Кнопка Аа → шрифт, размер, тема.">
      <TopBar left={<Ico>‹</Ico>} right={<><Ico>Аа</Ico><Ico>☰</Ico></>} />
      <div className="scroll-area" style={{ padding: '8px 18px', opacity: 0.4 }}>
        <div className="reader-text">
          <p>Alice was beginning to get very tired of sitting by her sister on the bank…</p>
        </div>
      </div>
      <div className="sheet">
        <div className="grabber" />
        <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 16, marginBottom: 12 }}>Настройки читалки</div>

        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 6 }}>РАЗМЕР ШРИФТА</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 12 }}>А</span>
            <div style={{ flex: 1, height: 4, background: 'var(--paper-2)', border: '1px solid var(--ink)', borderRadius: 2, position: 'relative' }}>
              <div style={{ position: 'absolute', left: '40%', top: -7, width: 18, height: 18, borderRadius: '50%', background: 'var(--ink)' }} />
            </div>
            <span style={{ fontSize: 22, fontFamily: 'var(--hand-bold)' }}>А</span>
          </div>
        </div>

        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 6 }}>ШРИФТ</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <div className="chip filled">Patrick</div>
            <div className="chip">Serif</div>
            <div className="chip">Sans</div>
            <div className="chip">Mono</div>
          </div>
        </div>

        <div>
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 6 }}>ТЕМА</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1, padding: '14px 10px', textAlign: 'center', border: '2px solid var(--ink)', borderRadius: 8, background: '#faf7f0', fontSize: 12 }}>Светлая</div>
            <div style={{ flex: 1, padding: '14px 10px', textAlign: 'center', border: '1px solid var(--ink-3)', borderRadius: 8, background: '#f4ebd3', fontSize: 12 }}>Сепия</div>
            <div style={{ flex: 1, padding: '14px 10px', textAlign: 'center', border: '1px solid var(--ink-3)', borderRadius: 8, background: '#1a1a1a', color: '#e8e6df', fontSize: 12 }}>Тёмная</div>
          </div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 4e. ЧИТАЛКА — оглавление ───
function ScreenReaderTOC() {
  return (
    <Phone label="04e — Оглавление" sub="Кнопка ☰ → список глав с прогрессом.">
      <TopBar left={<Ico>‹</Ico>} title="Главы" />
      <div className="scroll-area" style={{ padding: '8px 4px' }}>
        {[
          { n: 1, title: 'Вниз по кроличьей норе', done: true },
          { n: 2, title: 'Море слёз', done: true },
          { n: 3, title: 'Зал дверей', current: true },
          { n: 4, title: 'Бег по кругу', done: false },
          { n: 5, title: 'Совет от Гусеницы', done: false },
          { n: 6, title: 'Поросёнок и перец', done: false },
          { n: 7, title: 'Безумное чаепитие', done: false },
        ].map(ch => (
          <div key={ch.n} className="list-row" style={ch.current ? { background: 'rgba(212, 115, 74, 0.12)', borderRadius: 6, paddingLeft: 8 } : {}}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              border: '1.5px solid var(--ink)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, fontFamily: 'var(--hand-bold)',
              background: ch.done ? 'var(--ink)' : 'var(--paper)',
              color: ch.done ? 'var(--paper)' : 'var(--ink)',
            }}>{ch.done ? '✓' : ch.n}</div>
            <div style={{ flex: 1, fontSize: 14, fontWeight: ch.current ? 700 : 400 }}>
              {ch.title}
              {ch.current && <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700 }}>→ читаю сейчас</div>}
            </div>
          </div>
        ))}
      </div>
    </Phone>
  );
}

// ─── 4f. ЧИТАЛКА — тёмная тема ───
function ScreenReaderDark() {
  return (
    <Phone label="04f — Тёмная тема" sub="Та же читалка, тёмный режим" dark>
      <div style={{ background: '#1a1a1a', flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="app-top" style={{ color: '#e8e6df' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Ico>‹</Ico>
          </div>
          <div className="icon-row" style={{ color: '#e8e6df' }}>
            <Ico>Аа</Ico>
            <Ico>☰</Ico>
          </div>
        </div>
        <div style={{ padding: '0 18px 10px' }}>
          <div style={{ height: 3, background: '#333', borderRadius: 2 }}>
            <div style={{ width: '34%', height: '100%', background: '#e8e6df', borderRadius: 2 }} />
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 18px 16px', color: '#e8e6df' }}>
          <div className="reader-text" style={{ color: '#e8e6df' }}>
            <p>Alice was beginning to get very <span className="tr-word" style={{ background: 'rgba(212,115,74,0.3)', color: '#f0a070' }}>уставшей</span> of sitting by her sister on the bank.</p>
            <p>Once or twice she had <span className="tr-word" style={{ background: 'rgba(212,115,74,0.3)', color: '#f0a070' }}>заглянула</span> into the book…</p>
          </div>
        </div>
      </div>
    </Phone>
  );
}

Object.assign(window, {
  ScreenLibrary, ScreenLibraryEmpty,
  ScreenCatalog, ScreenCatalogDetail,
  ScreenUpload, ScreenUploadProgress, ScreenBookMenu,
  ScreenReader, ScreenReaderPopup, ScreenReaderSelect,
  ScreenReaderSettings, ScreenReaderTOC, ScreenReaderDark,
});
