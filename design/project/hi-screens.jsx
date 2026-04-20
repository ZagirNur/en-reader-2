// hi-screens.jsx — 5 screens adapting to theme A/B/C/D via helpers
// Uses globals: Ic, ThemedPhone, TabBar, LIBRARY_BOOKS, CATALOG_SECTIONS, PAGE_TEXT, DICTIONARY

function tcls(theme) {
  const map = {
    thA: { chip: 'chip-a', btn: 'btn-a', tr: 'tr-a' },
    thB: { chip: 'chip-b', btn: 'btn-b', tr: 'tr-b' },
    thC: { chip: 'chip-c', btn: 'btn-c', tr: 'tr-c' },
    thD: { chip: 'chip-d', btn: 'btn-d', tr: 'tr-d' },
  };
  return map[theme] || map.thA;
}
function palette(theme) {
  if (theme === 'thB') return { bg: '#0e0e10', paper: '#17171a', ink: '#ebebef', ink2: '#9a9aa5', line: '#27272e', accent: '#ff7a45', card: '#17171a', soft: '#1f1f24' };
  if (theme === 'thA') return { bg: '#f7f1e3', paper: '#fbf5e7', ink: '#2a1f14', ink2: '#6b5a44', line: '#e1d6b8', accent: '#b8442d', card: '#ffffff', soft: '#efe7d2' };
  if (theme === 'thC') return { bg: '#fefbf7', paper: '#ffffff', ink: '#2d1a12', ink2: '#7d5744', line: '#f1e3d3', accent: '#ff7a4f', card: '#ffffff', soft: '#fdf3e9' };
  return   { bg: '#f6f4ef', paper: '#ffffff', ink: '#14141a', ink2: '#5c5c66', line: '#e1dfd5', accent: '#e85d2c', card: '#ffffff', soft: '#ecebe5' }; // thD
}
const displayFontFor = (t) => t === 'thA' ? 'Newsreader, Georgia, serif' : t === 'thC' ? 'Instrument Serif, Georgia, serif' : 'Geist, sans-serif';
const readerFontFor  = (t) => t === 'thA' ? 'Newsreader, Georgia, serif' : t === 'thC' ? 'Lora, Georgia, serif' : 'Geist, sans-serif';
const isDark = (t) => t === 'thB';
const displayWeight = (t) => t === 'thA' || t === 'thC' ? 500 : 600;

// ═══════════ 1) LIBRARY ═══════════
function LibraryScreen({ theme }) {
  const c = tcls(theme);
  const p = palette(theme);
  const dF = displayFontFor(theme);
  const continuing = LIBRARY_BOOKS[0];
  const others = LIBRARY_BOOKS.slice(1);

  return (
    <ThemedPhone theme={theme} statusColor={p.ink}>
      <div className="hi-scroll" style={{ background: p.bg, color: p.ink }}>
        <div style={{ padding: '18px 24px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: 11, color: p.ink2, fontFamily: 'Geist,sans-serif', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 2 }}>Вторник · 9:41</div>
            <h1 style={{ margin: 0, fontFamily: dF, fontSize: 32, letterSpacing: '-0.02em', fontWeight: displayWeight(theme) }}>
              Моя полка
            </h1>
          </div>
          <div style={{ width: 40, height: 40, borderRadius: 20, background: p.card, border: `1px solid ${p.line}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'Geist', fontSize: 13, fontWeight: 600, color: p.ink }}>М</div>
        </div>

        {/* streak */}
        <div style={{ margin: '4px 24px 20px', padding: '12px 14px', borderRadius: 14, background: p.soft, display: 'flex', alignItems: 'center', gap: 12, fontFamily: 'Geist,sans-serif' }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'center', width:32, height:32, borderRadius:10, background: p.accent, color:'#fff'}}>
            <Ic.fire width={18} height={18}/>
          </div>
          <div style={{ flex:1 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>7 дней подряд</div>
            <div style={{ fontSize: 11, color: p.ink2 }}>8 слов сегодня · 42 за неделю</div>
          </div>
          <div style={{ fontSize: 11, color: p.ink2, fontVariantNumeric:'tabular-nums' }}>+12 <Ic.trend width={12} height={12} style={{ display:'inline', verticalAlign:'-2px' }}/></div>
        </div>

        {/* continue */}
        <div style={{ padding: '0 24px 18px' }}>
          <div style={{ fontSize: 11, fontFamily: 'Geist,sans-serif', color: p.ink2, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>Продолжить чтение</div>
          <div style={{ display: 'flex', gap: 14, padding: '12px', borderRadius: 18, background: p.card, border: `1px solid ${p.line}` }}>
            <div style={{ width: 88, flexShrink: 0 }}>
              <div className={`cover ${continuing.color}`} style={{ aspectRatio: '2/3' }}>
                <div className="ct">{continuing.t}</div>
                <div className="ca">{continuing.a.split(' ').slice(-1)[0]}</div>
              </div>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <div style={{ fontFamily: dF, fontSize: 20, lineHeight: 1.15, letterSpacing: '-0.01em', fontWeight: displayWeight(theme), marginTop: 2 }}>
                {continuing.t}
              </div>
              <div style={{ fontSize: 12, color: p.ink2, fontFamily: 'Geist,sans-serif', marginTop: 2 }}>{continuing.a}</div>
              <div style={{ marginTop: 14, display: 'flex', gap: 12, fontFamily: 'Geist,sans-serif', fontSize: 11, color: p.ink2 }}>
                <span>гл. 3</span><span>·</span><span>42 % прочитано</span>
              </div>
              <div style={{ height: 4, borderRadius: 2, background: p.line, marginTop: 8, overflow: 'hidden' }}>
                <div style={{ width: '42%', height: '100%', background: p.accent }}/>
              </div>
              <button className={`${c.btn} primary`} style={{ marginTop: 14, padding: '10px 16px', fontSize: 13, alignSelf: 'flex-start' }}>
                Читать дальше <Ic.chevR width={14} height={14}/>
              </button>
            </div>
          </div>
        </div>

        {/* shelf */}
        <div style={{ padding: '0 24px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 11, fontFamily: 'Geist,sans-serif', color: p.ink2, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Моя библиотека</div>
          <div style={{ fontSize: 11, fontFamily: 'Geist,sans-serif', color: p.ink2 }}>{LIBRARY_BOOKS.length} книг</div>
        </div>

        <div style={{ padding: '0 24px 24px', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, rowGap: 22 }}>
          {others.map(b => (
            <div key={b.id}>
              <div className={`cover ${b.color}`} style={{ aspectRatio: '2/3', padding: '10px 8px' }}>
                <div className="ct" style={{ fontSize: 13, lineHeight: 1.05 }}>{b.t}</div>
                <div className="ca" style={{ fontSize: 7 }}>{b.a.split(' ').slice(-1)[0]}</div>
              </div>
              <div style={{ marginTop: 8, fontFamily: 'Geist,sans-serif' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: p.ink, lineHeight: 1.2, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{b.t}</div>
                <div style={{ fontSize: 10, color: p.ink2, marginTop: 2, display:'flex', justifyContent:'space-between' }}>
                  <span>{b.lvl}</span><span>{Math.round(b.prog*100)}%</span>
                </div>
                <div style={{ height: 2, borderRadius: 1, background: p.line, marginTop: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${b.prog*100}%`, height: '100%', background: p.accent }}/>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <TabBar theme={theme} active="lib"/>
    </ThemedPhone>
  );
}

// ═══════════ 2) READER ═══════════
function ReaderScreen({ theme }) {
  const c = tcls(theme);
  const p = palette(theme);
  const rF = readerFontFor(theme);

  return (
    <ThemedPhone theme={theme} statusColor={p.ink}>
      <div style={{ background: p.paper, padding: '4px 16px 10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, borderBottom: `1px solid ${p.line}` }}>
        <button style={{ background:'none', border:'none', padding: 6, color: p.ink, cursor:'pointer' }}>
          <Ic.chevL width={22} height={22}/>
        </button>
        <div style={{ textAlign:'center', fontFamily: 'Geist,sans-serif' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: p.ink }}>The Great Gatsby</div>
          <div style={{ fontSize: 10, color: p.ink2, marginTop: 1 }}>Глава 1 · стр. 7 из 182</div>
        </div>
        <button style={{ background:'none', border:'none', padding: 6, color: p.ink, cursor:'pointer' }}>
          <Ic.settings width={22} height={22}/>
        </button>
      </div>

      <div className="hi-scroll" style={{ background: p.paper, padding: '28px 28px 16px' }}>
        <div style={{ fontFamily: 'Geist,sans-serif', fontSize: 10, color: p.ink2, letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 14 }}>
          Chapter One
        </div>
        <div style={{ fontFamily: rF, fontSize: 17, lineHeight: 1.65, color: p.ink, textWrap: 'pretty' }}>
          {PAGE_TEXT.map((para, i) => (
            <p key={i} style={{ margin: '0 0 14px' }}>
              {para.parts.map((pt, j) => {
                if (typeof pt === 'string') return <span key={j}>{pt}</span>;
                return <span key={j} className={c.tr}>{pt.ru}</span>;
              })}
            </p>
          ))}
        </div>

        <div style={{ marginTop: 10, display:'flex', alignItems:'center', justifyContent:'space-between', fontFamily: 'Geist,sans-serif', fontSize: 11, color: p.ink2 }}>
          <span>42 % · ~18 мин до конца главы</span>
          <span style={{ display:'inline-flex', gap: 8, alignItems:'center' }}>
            <Ic.star width={14} height={14}/> 4 новых слова
          </span>
        </div>
      </div>

      <div style={{ background: p.paper, padding: '10px 24px 16px', borderTop: `1px solid ${p.line}`, flexShrink: 0 }}>
        <div style={{ height: 3, borderRadius: 2, background: p.line, overflow: 'hidden' }}>
          <div style={{ width: '42%', height: '100%', background: p.accent }}/>
        </div>
      </div>
    </ThemedPhone>
  );
}

// ═══════════ 3) WORD POPUP ═══════════
function WordPopupScreen({ theme }) {
  const c = tcls(theme);
  const p = palette(theme);
  const rF = readerFontFor(theme);
  const dF = displayFontFor(theme);
  const sheetBg = isDark(theme) ? '#1f1f24' : p.paper;

  return (
    <ThemedPhone theme={theme} statusColor={p.ink}>
      <div style={{ position:'absolute', inset: 0, background: p.paper, padding: '60px 28px 0' }}>
        <div style={{ fontFamily: rF, fontSize: 17, lineHeight: 1.65, color: p.ink, opacity: 0.35 }}>
          <p>In my younger and more <span style={{
            background: isDark(theme) ? 'rgba(255,122,69,0.25)' : `${p.accent}26`,
            color: p.accent,
            padding: '2px 4px', borderRadius: 3, opacity: 1, fontWeight: 600
          }}>vulnerable</span> years my father gave me some advice that I've been turning over in my mind ever since.</p>
          <p>"Whenever you feel like criticizing any one," he told me, "just remember that all the people in this world haven't had the advantages that you've had."</p>
        </div>
      </div>

      <div style={{ position:'absolute', inset: 0, background: isDark(theme) ? 'rgba(0,0,0,0.5)' : 'rgba(20,14,6,0.28)', backdropFilter: 'blur(1px)' }}/>

      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        background: sheetBg,
        borderTopLeftRadius: 28, borderTopRightRadius: 28,
        padding: '18px 24px 28px',
        boxShadow: '0 -20px 40px -12px rgba(0,0,0,0.3)',
        fontFamily: 'Geist,sans-serif'
      }}>
        <div style={{ width: 40, height: 4, borderRadius: 2, background: p.line, margin: '0 auto 18px' }}/>

        <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: dF, fontSize: 34, fontWeight: displayWeight(theme), lineHeight: 1, letterSpacing: '-0.02em', color: p.ink }}>
              vulnerable
            </div>
            <div style={{ marginTop: 6, fontSize: 13, color: p.ink2, fontStyle: 'italic' }}>
              /ˈvʌln(ə)rəb(ə)l/ · прил.
            </div>
          </div>
          <div style={{ display:'flex', gap: 8 }}>
            <button style={{ width: 36, height: 36, borderRadius: 12, border: `1px solid ${p.line}`, background: 'transparent', color: p.ink, display:'inline-flex', alignItems:'center', justifyContent:'center', cursor:'pointer' }}>
              <Ic.star width={16} height={16}/>
            </button>
            <button style={{ width: 36, height: 36, borderRadius: 12, border: `1px solid ${p.line}`, background: 'transparent', color: p.ink, display:'inline-flex', alignItems:'center', justifyContent:'center', cursor:'pointer' }}>
              <Ic.x width={16} height={16}/>
            </button>
          </div>
        </div>

        <div style={{ marginTop: 16, padding: 14, borderRadius: 14, background: p.soft, color: p.ink }}>
          <div style={{ fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: p.ink2, marginBottom: 6 }}>перевод</div>
          <div style={{ fontSize: 18, fontWeight: 500 }}>уязвимый, ранимый</div>
        </div>

        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: p.ink2, marginBottom: 8 }}>из книги</div>
          <div style={{ fontSize: 13, lineHeight: 1.5, color: p.ink, fontFamily: rF, fontStyle: theme === 'thA' ? 'italic' : 'normal' }}>
            "my younger and more <b style={{ color: p.accent }}>vulnerable</b> years"
          </div>
        </div>

        <div style={{ marginTop: 22, display: 'flex', gap: 10 }}>
          <button className={`${c.btn} primary`} style={{ flex: 1 }}>
            <Ic.plus width={16} height={16}/> В словарь
          </button>
          <button className={`${c.btn} ghost`} style={{ flex: 1 }}>Ещё примеры</button>
        </div>
      </div>
    </ThemedPhone>
  );
}

// ═══════════ 4) DICTIONARY ═══════════
function DictionaryScreen({ theme }) {
  const c = tcls(theme);
  const p = palette(theme);
  const dF = displayFontFor(theme);

  const badgeFor = (lvl) => {
    if (lvl === 'new') return { bg: p.accent, col: '#fff', t: 'новое' };
    if (lvl === 'learning') return { bg: isDark(theme) ? '#2a2a32' : theme === 'thA' ? '#e9d6b0' : theme === 'thC' ? '#ffe0c4' : '#ecebe5', col: p.ink, t: 'учу' };
    if (lvl === 'review') return { bg: isDark(theme) ? '#e4c074' : '#c9a253', col: '#2d1a12', t: 'повторить' };
    return { bg: isDark(theme) ? '#2a3f24' : theme === 'thA' ? '#d8e0b8' : theme === 'thC' ? '#d5e9c0' : '#d8e0c0', col: '#2a3f14', t: 'выучено' };
  };
  const counts = {
    all: DICTIONARY.length,
    review: DICTIONARY.filter(d=>d.lvl==='review').length,
    learning: DICTIONARY.filter(d=>d.lvl==='learning').length,
    new: DICTIONARY.filter(d=>d.lvl==='new').length,
    mastered: DICTIONARY.filter(d=>d.lvl==='mastered').length,
  };

  return (
    <ThemedPhone theme={theme} statusColor={p.ink}>
      <div className="hi-scroll" style={{ background: p.bg, color: p.ink }}>
        <div style={{ padding: '18px 24px 10px' }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-end' }}>
            <h1 style={{ margin: 0, fontFamily: dF, fontSize: 32, letterSpacing: '-0.02em', fontWeight: displayWeight(theme) }}>Словарь</h1>
            <div style={{ fontFamily: 'Geist,sans-serif', fontSize: 11, color: p.ink2 }}>{DICTIONARY.length} слов</div>
          </div>
        </div>

        <div style={{ margin: '10px 24px 18px', padding: 14, borderRadius: 14, background: p.card, border: `1px solid ${p.line}`, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, fontFamily: 'Geist,sans-serif' }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700, color: p.accent, fontVariantNumeric:'tabular-nums' }}>{counts.review}</div>
            <div style={{ fontSize: 10, color: p.ink2, marginTop: 2, letterSpacing:'0.02em' }}>на повтор<br/>сегодня</div>
          </div>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700, color: p.ink, fontVariantNumeric:'tabular-nums' }}>{counts.learning + counts.new}</div>
            <div style={{ fontSize: 10, color: p.ink2, marginTop: 2 }}>учу<br/>сейчас</div>
          </div>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700, color: p.ink, fontVariantNumeric:'tabular-nums' }}>{counts.mastered}</div>
            <div style={{ fontSize: 10, color: p.ink2, marginTop: 2 }}>выучено</div>
          </div>
        </div>

        <div style={{ padding: '0 24px 14px', display: 'flex', gap: 8, overflowX: 'auto', flexWrap:'nowrap' }}>
          <span className={`${c.chip} on`}>Все <span className="n">{counts.all}</span></span>
          <span className={c.chip}>Повторить <span className="n">{counts.review}</span></span>
          <span className={c.chip}>Учу <span className="n">{counts.learning}</span></span>
          <span className={c.chip}>Новые <span className="n">{counts.new}</span></span>
        </div>

        <div style={{ padding: '0 24px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {DICTIONARY.map((d, i) => {
            const b = badgeFor(d.lvl);
            return (
              <div key={i} style={{ padding: 14, borderRadius: 14, background: p.card, border: `1px solid ${p.line}`, fontFamily: 'Geist,sans-serif' }}>
                <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap: 10 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display:'flex', gap: 8, alignItems:'baseline' }}>
                      <div style={{ fontFamily: dF, fontSize: 20, fontWeight: displayWeight(theme), color: p.ink, letterSpacing:'-0.01em' }}>{d.w}</div>
                      <div style={{ fontSize: 13, color: p.ink2 }}>— {d.t}</div>
                    </div>
                    <div style={{ marginTop: 6, fontSize: 12, color: p.ink2, lineHeight: 1.4, fontStyle: theme === 'thA' ? 'italic' : 'normal' }}>
                      "{d.ex}"
                    </div>
                    <div style={{ marginTop: 8, fontSize: 10, color: p.ink2, letterSpacing: '0.02em' }}>
                      {d.src}{d.d > 0 && ` · ${d.d} дн.`}
                    </div>
                  </div>
                  <span style={{ padding: '4px 8px', borderRadius: 6, fontSize: 10, fontWeight: 600, background: b.bg, color: b.col, whiteSpace: 'nowrap' }}>{b.t}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <TabBar theme={theme} active="dict"/>
    </ThemedPhone>
  );
}

// ═══════════ 5) LEARN ═══════════
function LearnScreen({ theme }) {
  const c = tcls(theme);
  const p = palette(theme);
  const dF = displayFontFor(theme);

  return (
    <ThemedPhone theme={theme} statusColor={p.ink}>
      <div className="hi-scroll" style={{ background: p.bg, color: p.ink, padding: '18px 24px 24px' }}>
        <div>
          <div style={{ fontSize: 11, color: p.ink2, fontFamily: 'Geist,sans-serif', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Тренировка</div>
          <h1 style={{ margin: '2px 0 0', fontFamily: dF, fontSize: 26, fontWeight: displayWeight(theme), letterSpacing: '-0.02em' }}>Слово 3 из 12</h1>
        </div>

        <div style={{ marginTop: 14, display: 'flex', gap: 4 }}>
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} style={{ flex: 1, height: 3, borderRadius: 2, background: i < 2 ? p.accent : i === 2 ? p.ink : p.line }}/>
          ))}
        </div>

        <div style={{
          marginTop: 26, padding: '34px 22px 26px', borderRadius: 20,
          background: p.card, border: `1px solid ${p.line}`,
          boxShadow: isDark(theme) ? 'none' : '0 2px 0 rgba(0,0,0,0.03), 0 12px 24px -18px rgba(40,20,10,0.25)',
          minHeight: 300
        }}>
          <div style={{ fontFamily: 'Geist,sans-serif', fontSize: 10, color: p.ink2, letterSpacing: '0.14em', textTransform:'uppercase', textAlign:'center' }}>Какой перевод?</div>
          <div style={{ marginTop: 18, textAlign: 'center', fontFamily: dF, fontSize: 44, lineHeight: 1, letterSpacing: '-0.02em', fontWeight: displayWeight(theme), color: p.ink }}>
            reluctant
          </div>
          <div style={{ marginTop: 10, textAlign:'center', fontFamily: 'Geist,sans-serif', fontSize: 12, color: p.ink2, fontStyle: 'italic' }}>/rɪˈlʌktənt/ · прил.</div>

          <div style={{
            marginTop: 22, padding: '14px 16px', borderRadius: 12, background: p.soft,
            fontFamily: readerFontFor(theme), fontSize: 14, lineHeight: 1.55, color: p.ink,
            fontStyle: theme === 'thA' ? 'italic' : 'normal', textAlign: 'center'
          }}>
            "a <b style={{ color: p.accent, fontStyle: 'normal' }}>reluctant</b> smile crossed her face"
          </div>
          <div style={{ marginTop: 8, textAlign: 'center', fontSize: 10, color: p.ink2, fontFamily: 'Geist,sans-serif', letterSpacing: '0.04em' }}>1984 · Оруэлл</div>
        </div>

        <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {[{t:'неохотный'},{t:'настойчивый'},{t:'усталый'},{t:'скромный'}].map((opt,i)=>(
            <button key={i} style={{ padding: '16px 14px', borderRadius: 14, background: p.card, color: p.ink, border: `1.5px solid ${p.line}`, fontFamily: 'Geist,sans-serif', fontSize: 15, fontWeight: 500, textAlign: 'left', cursor: 'pointer' }}>
              {opt.t}
            </button>
          ))}
        </div>

        <div style={{ marginTop: 18, display:'flex', alignItems:'center', justifyContent:'space-between', fontFamily: 'Geist,sans-serif', fontSize: 12, color: p.ink2 }}>
          <span style={{ cursor:'pointer' }}>Пропустить</span>
          <span style={{ cursor:'pointer', display:'inline-flex', gap: 6, alignItems:'center' }}>
            <Ic.volume width={14} height={14}/> Показать перевод
          </span>
        </div>
      </div>
      <TabBar theme={theme} active="learn"/>
    </ThemedPhone>
  );
}

Object.assign(window, { LibraryScreen, ReaderScreen, WordPopupScreen, DictionaryScreen, LearnScreen });
