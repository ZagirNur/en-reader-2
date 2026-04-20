// Экраны часть 2: Словарь, Слово, Тренировки, Настройки, Навигация, Десктоп

// ─── 5. СЛОВАРЬ ───
const dictWords = [
  { en: 'tired', ru: 'уставший', book: 'Алиса', status: 'learning', n: 4 },
  { en: 'wreath', ru: 'венок', book: 'Алиса', status: 'new', n: 0 },
  { en: 'peculiar', ru: 'странный', book: '1984', status: 'known', n: 12 },
  { en: 'dialogue', ru: 'диалог', book: 'Алиса', status: 'learning', n: 3 },
  { en: 'whisper', ru: 'шёпот', book: '1984', status: 'new', n: 1 },
  { en: 'cellar', ru: 'погреб', book: 'Гордость…', status: 'learning', n: 2 },
];

function ScreenDictionary() {
  return (
    <Phone label="05 — Словарь" sub="По умолчанию: группы по статусу (новые / учу / выучено).">
      <TopBar title="Словарь" right={<><Ico>⌕</Ico><Ico>⇅</Ico></>} />
      <div className="scroll-area">
        <div style={{ display: 'flex', gap: 8, padding: '0 0 12px' }}>
          <div className="sk-box" style={{ flex: 1, padding: '8px 10px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 20 }}>289</div>
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>Всего</div>
          </div>
          <div className="sk-box" style={{ flex: 1, padding: '8px 10px', textAlign: 'center', background: 'rgba(212,115,74,0.12)' }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 20 }}>47</div>
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>Учить</div>
          </div>
          <div className="sk-box" style={{ flex: 1, padding: '8px 10px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 20 }}>164</div>
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>Знаю</div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <div className="chip filled">Все</div>
          <div className="chip">По книгам</div>
          <div className="chip">А–Я</div>
          <div className="chip">Недавние</div>
        </div>

        {[
          { label: '✦ НОВЫЕ · 47', items: dictWords.filter(w => w.status === 'new') },
          { label: '◐ УЧУ · 78', items: dictWords.filter(w => w.status === 'learning') },
          { label: '✓ ЗНАЮ · 164', items: dictWords.filter(w => w.status === 'known') },
        ].map(g => (
          <div key={g.label}>
            <div style={{ fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1, marginTop: 12, marginBottom: 4, fontFamily: 'var(--mono)' }}>
              {g.label}
            </div>
            {g.items.map((w, i) => (
              <div key={i} className="list-row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 16 }}>{w.en}</div>
                  <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>{w.ru} · из «{w.book}»</div>
                </div>
                <div style={{ display: 'flex', gap: 2 }}>
                  {[0,1,2,3,4].map(k => (
                    <div key={k} style={{
                      width: 6, height: 6, borderRadius: '50%',
                      border: '1px solid var(--ink)',
                      background: k < w.n ? 'var(--ink)' : 'transparent',
                    }} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
      <TabBar active="dict" />
    </Phone>
  );
}

// ─── 5b. КАРТОЧКА СЛОВА ───
function ScreenWordDetail() {
  return (
    <Phone label="05b — Карточка слова" sub="Тап по слову в словаре.">
      <TopBar left={<Ico>‹</Ico>} right={<Ico>⋯</Ico>} />
      <div className="scroll-area">
        <div style={{ padding: '12px 0 16px' }}>
          <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 36, lineHeight: 1 }}>tired</div>
          <div style={{ fontSize: 13, color: 'var(--ink-2)', marginTop: 4 }}>
            прил · /ˈtaɪəd/
          </div>
        </div>
        <div className="sk-box" style={{ padding: '12px 14px', marginBottom: 14 }}>
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 4 }}>ПЕРЕВОД</div>
          <div style={{ fontSize: 17, fontFamily: 'var(--hand-bold)' }}>уставший, утомлённый</div>
        </div>

        <div style={{ fontSize: 11, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginBottom: 6 }}>
          ИЗ КОНТЕКСТА
        </div>
        <div style={{
          fontSize: 13, lineHeight: 1.5,
          borderLeft: '2px solid var(--accent)',
          paddingLeft: 10, marginBottom: 14,
          fontStyle: 'italic',
        }}>
          "Alice was beginning to get very <span style={{ background: 'rgba(212,115,74,0.2)' }}>tired</span> of sitting by her sister on the bank…"
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4, fontStyle: 'normal' }}>
            — Алиса в Стране чудес · гл. 1
          </div>
        </div>

        <div style={{ fontSize: 11, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginBottom: 6 }}>
          ПРОГРЕСС
        </div>
        <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
          {[1,2,3,4,5].map(k => (
            <div key={k} style={{
              flex: 1, height: 8, borderRadius: 4,
              border: '1px solid var(--ink)',
              background: k <= 3 ? 'var(--ink)' : 'transparent',
            }} />
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 16 }}>
          Повторено 3/5 · последний раз 2 дня назад
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <div className="btn full primary">Тренировать это слово</div>
          <div className="btn">×</div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 6. ГЛАВНАЯ ТРЕНИРОВОК ───
function ScreenTrainingHome() {
  return (
    <Phone label="06 — Тренировки" sub="Выбор режима + прогресс дня.">
      <TopBar title="Тренировка" right={<Ico>⌕</Ico>} />
      <div className="scroll-area">
        <div className="sk-box shadow" style={{ padding: '16px', marginBottom: 16, background: 'var(--paper)' }}>
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 6, fontFamily: 'var(--mono)' }}>
            ЦЕЛЬ НА СЕГОДНЯ
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 8 }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 32 }}>12</div>
            <div style={{ fontSize: 14, color: 'var(--ink-2)' }}>/ 20 слов</div>
          </div>
          <div className="progress" style={{ height: 6 }}>
            <div style={{ width: '60%', background: 'var(--accent)' }} />
          </div>
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 6 }}>
            Серия: 🔥 7 дней
          </div>
        </div>

        <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 16, marginBottom: 8 }}>
          Выбери режим
        </div>

        <div className="sk-box shadow" style={{ padding: 14, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 44, height: 44, borderRadius: 8,
            border: '1.5px solid var(--ink)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--hand-bold)', fontSize: 22,
            background: 'var(--paper-2)',
          }}>▭</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 15 }}>Карточки</div>
            <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>EN → RU · переверни для ответа · 12 готовы</div>
          </div>
          <Ico>›</Ico>
        </div>

        <div className="sk-box shadow" style={{ padding: 14, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 44, height: 44, borderRadius: 8,
            border: '1.5px solid var(--ink)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--hand-bold)', fontSize: 18,
            background: 'var(--paper-2)',
          }}>А·Б·В</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 15 }}>Выбор из вариантов</div>
            <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>Подбери правильный перевод · 12 готовы</div>
          </div>
          <Ico>›</Ico>
        </div>

        <div style={{ fontSize: 11, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginTop: 16, marginBottom: 6 }}>
          В ОЧЕРЕДИ
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {['tired','wreath','peculiar','dialogue','whisper'].map(w => (
            <div key={w} className="chip">{w}</div>
          ))}
          <div className="chip" style={{ borderStyle: 'dashed', color: 'var(--ink-2)' }}>+ ещё 7</div>
        </div>
      </div>
      <TabBar active="train" />
    </Phone>
  );
}

// ─── 6b. КАРТОЧКА — лицевая ───
function ScreenFlashcardFront() {
  return (
    <Phone label="06b — Карточка (лицо)" sub="EN слово, тап чтобы перевернуть.">
      <TopBar
        left={<Ico>✕</Ico>}
        title=""
        right={<span style={{ fontSize: 12, color: 'var(--ink-2)' }}>3 / 12</span>}
      />
      <div style={{ padding: '0 18px 10px' }}>
        <div className="progress" style={{ height: 4 }}>
          <div style={{ width: '25%', background: 'var(--accent)' }} />
        </div>
      </div>
      <div className="scroll-area" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 20px' }}>
        <div className="flashcard">
          <div style={{ fontSize: 11, color: 'var(--ink-2)', letterSpacing: 1, marginBottom: 12 }}>EN</div>
          <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 38, marginBottom: 8 }}>peculiar</div>
          <div style={{ fontSize: 13, color: 'var(--ink-2)' }}>прил · /pɪˈkjuːliə/</div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 24, fontStyle: 'italic' }}>
            тап чтобы показать →
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 14, marginTop: 24 }}>
          <div className="btn">💡 подсказка</div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 6c. КАРТОЧКА — оборот ───
function ScreenFlashcardBack() {
  return (
    <Phone label="06c — Карточка (оборот)" sub="Перевод + самооценка.">
      <TopBar
        left={<Ico>✕</Ico>}
        right={<span style={{ fontSize: 12, color: 'var(--ink-2)' }}>3 / 12</span>}
      />
      <div style={{ padding: '0 18px 10px' }}>
        <div className="progress" style={{ height: 4 }}>
          <div style={{ width: '25%', background: 'var(--accent)' }} />
        </div>
      </div>
      <div className="scroll-area" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 20px' }}>
        <div className="flashcard">
          <div style={{ fontSize: 14, fontFamily: 'var(--hand)', color: 'var(--ink-2)', marginBottom: 4 }}>peculiar</div>
          <div style={{ height: 1, background: 'var(--ink-3)', width: '60%', margin: '8px 0 14px' }} />
          <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 30, marginBottom: 12 }}>странный</div>
          <div style={{
            fontSize: 12, color: 'var(--ink-2)',
            fontStyle: 'italic', textAlign: 'center', maxWidth: 240,
            borderLeft: '2px solid var(--ink-3)', paddingLeft: 8,
          }}>
            "a peculiar smell" — странный запах
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', textAlign: 'center', margin: '20px 0 8px' }}>
          Насколько хорошо помнишь?
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <div className="btn full" style={{ background: '#e8c8c0' }}>✗ Снова</div>
          <div className="btn full" style={{ background: '#f0d8a8' }}>Сложно</div>
          <div className="btn full" style={{ background: '#c9d4b8' }}>Хорошо</div>
          <div className="btn full" style={{ background: '#a8c4a0' }}>Легко</div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 6d. ВЫБОР ИЗ ВАРИАНТОВ ───
function ScreenMultipleChoice() {
  return (
    <Phone label="06d — Выбор варианта" sub="Выбери правильный перевод.">
      <TopBar
        left={<Ico>✕</Ico>}
        right={<span style={{ fontSize: 12, color: 'var(--ink-2)' }}>5 / 12</span>}
      />
      <div style={{ padding: '0 18px 10px' }}>
        <div className="progress" style={{ height: 4 }}>
          <div style={{ width: '42%', background: 'var(--accent)' }} />
        </div>
      </div>
      <div className="scroll-area" style={{ padding: '12px 18px' }}>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginBottom: 6 }}>
          ЧТО ОЗНАЧАЕТ…
        </div>
        <div style={{
          fontFamily: 'var(--hand-bold)', fontSize: 32,
          padding: '14px 0 6px',
        }}>wreath</div>
        <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 18 }}>
          /riːθ/ · сущ
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            { t: 'погреб', state: 'idle' },
            { t: 'венок', state: 'correct' },
            { t: 'шёпот', state: 'idle' },
            { t: 'диалог', state: 'idle' },
          ].map((o, i) => (
            <div key={i} className="sk-box" style={{
              padding: '12px 14px',
              display: 'flex', alignItems: 'center', gap: 10,
              background: o.state === 'correct' ? 'rgba(168, 196, 160, 0.4)' : 'var(--paper)',
              borderColor: o.state === 'correct' ? 'var(--accent-2)' : 'var(--ink)',
            }}>
              <div style={{
                width: 22, height: 22, borderRadius: '50%',
                border: '1.5px solid var(--ink)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontFamily: 'var(--hand-bold)',
              }}>{['А','Б','В','Г'][i]}</div>
              <div style={{ flex: 1, fontFamily: 'var(--hand-bold)', fontSize: 17 }}>{o.t}</div>
              {o.state === 'correct' && <span style={{ fontSize: 18 }}>✓</span>}
            </div>
          ))}
        </div>

        <div style={{ marginTop: 20, fontSize: 12, color: 'var(--ink-2)', textAlign: 'center', fontStyle: 'italic' }}>
          Из: «Алиса в Стране чудес»
        </div>
      </div>
    </Phone>
  );
}

// ─── 6e. ЗАВЕРШЕНИЕ СЕССИИ ───
function ScreenSessionDone() {
  return (
    <Phone label="06e — Сессия завершена" sub="Итоговый экран.">
      <TopBar left={<Ico>✕</Ico>} />
      <div className="scroll-area" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: 20, textAlign: 'center' }}>
        <div style={{ fontSize: 56, fontFamily: 'var(--hand-bold)', lineHeight: 1 }}>🎉</div>
        <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 26, marginTop: 12 }}>
          <span className="scribble">Готово!</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--ink-2)', marginTop: 8, maxWidth: 240 }}>
          Ты повторил 12 слов. 9 правильно, 3 вернутся завтра.
        </div>
        <div style={{ display: 'flex', gap: 18, marginTop: 22 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 26 }}>9</div>
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>ВЕРНО</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 26 }}>3</div>
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>НЕВЕРНО</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 26 }}>4′</div>
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>ВРЕМЯ</div>
          </div>
        </div>
        <div style={{ width: '100%', marginTop: 28, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="btn primary full">Продолжить — ещё 8</div>
          <div className="btn full">Вернуться в библиотеку</div>
        </div>
      </div>
    </Phone>
  );
}

// ─── 7. НАСТРОЙКИ ───
function ScreenSettings() {
  return (
    <Phone label="07 — Настройки" sub="Общие настройки приложения.">
      <TopBar left={<Ico>‹</Ico>} title="Настройки" />
      <div className="scroll-area">
        <div style={{ fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginTop: 12, marginBottom: 4 }}>
          ЯЗЫК
        </div>
        <div className="list-row"><div style={{ flex: 1, fontSize: 14 }}>Я читаю на</div><span style={{ fontSize: 13, color: 'var(--ink-2)' }}>English ›</span></div>
        <div className="list-row"><div style={{ flex: 1, fontSize: 14 }}>Перевод на</div><span style={{ fontSize: 13, color: 'var(--ink-2)' }}>Русский ›</span></div>

        <div style={{ fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginTop: 18, marginBottom: 4 }}>
          ТРЕНИРОВКИ
        </div>
        <div className="list-row"><div style={{ flex: 1, fontSize: 14 }}>Цель в день</div><span style={{ fontSize: 13, color: 'var(--ink-2)' }}>20 слов ›</span></div>
        <div className="list-row"><div style={{ flex: 1, fontSize: 14 }}>Напоминание</div><span style={{ fontSize: 13, color: 'var(--ink-2)' }}>19:00 ›</span></div>
        <div className="list-row">
          <div style={{ flex: 1, fontSize: 14 }}>Автосохранять тапнутые слова</div>
          <div style={{ width: 36, height: 20, borderRadius: 12, border: '1.5px solid var(--ink)', background: 'var(--ink)', position: 'relative' }}>
            <div style={{ position: 'absolute', right: 1, top: 1, width: 16, height: 16, borderRadius: '50%', background: 'var(--paper)' }} />
          </div>
        </div>

        <div style={{ fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1, fontFamily: 'var(--mono)', marginTop: 18, marginBottom: 4 }}>
          ДАННЫЕ
        </div>
        <div className="list-row"><div style={{ flex: 1, fontSize: 14 }}>Экспорт словаря (.csv)</div><Ico>›</Ico></div>
        <div className="list-row"><div style={{ flex: 1, fontSize: 14 }}>Резервная копия и синхронизация</div><span style={{ fontSize: 13, color: 'var(--ink-2)' }}>Выкл ›</span></div>
        <div className="list-row" style={{ color: 'var(--accent)' }}>
          <div style={{ flex: 1, fontSize: 14 }}>Очистить все данные</div>
        </div>
      </div>
    </Phone>
  );
}

// ─── ВАРИАНТЫ НАВИГАЦИИ ───
function NavVarA() {
  return (
    <div style={{ width: 360 }}>
      <div className="frame-caption">Навигация A — 4 вкладки</div>
      <div className="frame-sub">Мои книги · Каталог · Словарь · Тренировки</div>
      <div className="phone" style={{ height: 90 }}>
        <TabBar active="books" tabs={[
          { id: 'books', icon: '▣', label: 'Мои книги' },
          { id: 'catalog', icon: '☰', label: 'Каталог' },
          { id: 'dict', icon: 'А', label: 'Словарь' },
          { id: 'train', icon: '✦', label: 'Учить' },
        ]} />
      </div>
    </div>
  );
}
function NavVarB() {
  return (
    <div style={{ width: 360 }}>
      <div className="frame-caption">Навигация B — Библиотека объединена</div>
      <div className="frame-sub">Библиотека (мои+каталог внутри) · Словарь · Учить</div>
      <div className="phone" style={{ height: 90 }}>
        <TabBar active="books" tabs={[
          { id: 'books', icon: '▣', label: 'Библиотека' },
          { id: 'dict', icon: 'А', label: 'Словарь' },
          { id: 'train', icon: '✦', label: 'Учить' },
        ]} />
      </div>
    </div>
  );
}
function NavVarC() {
  return (
    <div style={{ width: 360 }}>
      <div className="frame-caption">Навигация C — Учёба объединена</div>
      <div className="frame-sub">Мои книги · Каталог · Учёба (словарь + тренировки)</div>
      <div className="phone" style={{ height: 90 }}>
        <TabBar active="books" tabs={[
          { id: 'books', icon: '▣', label: 'Мои книги' },
          { id: 'catalog', icon: '☰', label: 'Каталог' },
          { id: 'train', icon: '✦', label: 'Учёба' },
        ]} />
      </div>
    </div>
  );
}

// ─── ДЕСКТОП / ПЛАНШЕТ ───
function ScreenDesktop() {
  return (
    <div style={{ width: 880 }}>
      <div className="frame-caption">D — Десктоп / планшет</div>
      <div className="frame-sub">То же приложение, боковое меню и шире сетка. Mobile-first, но адаптируется.</div>
      <div style={{
        width: 880, height: 540,
        background: 'var(--paper)',
        border: '2.5px solid var(--ink)',
        borderRadius: 12,
        boxShadow: '4px 4px 0 var(--ink)',
        display: 'flex',
        overflow: 'hidden',
      }}>
        <div style={{
          width: 180,
          borderRight: '1.5px solid var(--ink)',
          padding: '20px 14px',
          display: 'flex', flexDirection: 'column', gap: 4,
          background: 'var(--paper-2)',
        }}>
          <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 22, marginBottom: 18 }}>EN Reader</div>
          {[
            { l: 'Мои книги', a: true },
            { l: 'Каталог' },
            { l: 'Словарь' },
            { l: 'Тренировки' },
            { l: 'Настройки' },
          ].map(it => (
            <div key={it.l} style={{
              padding: '8px 10px', borderRadius: 6, fontSize: 14,
              background: it.a ? 'var(--ink)' : 'transparent',
              color: it.a ? 'var(--paper)' : 'var(--ink)',
              fontWeight: it.a ? 700 : 400,
            }}>{it.l}</div>
          ))}
        </div>
        <div style={{ flex: 1, padding: 24, overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 26 }}>Мои книги</div>
            <div className="btn primary sm">+ Загрузить книгу</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 18 }}>
            {myBooks.slice(0,4).map((b,i) => <BookCard key={i} {...b} />)}
            <AddBookCard />
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  ScreenDictionary, ScreenWordDetail,
  ScreenTrainingHome, ScreenFlashcardFront, ScreenFlashcardBack,
  ScreenMultipleChoice, ScreenSessionDone,
  ScreenSettings,
  NavVarA, NavVarB, NavVarC,
  ScreenDesktop,
});
