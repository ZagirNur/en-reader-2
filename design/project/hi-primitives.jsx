// hi-primitives.jsx — shared shell, icons, and sample data for hi-fi designs
const { useState, useMemo } = React;

// ─────────── Icons (stroke = currentColor) ───────────
const Ic = {
  books: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5v13Z"/>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 22H20v-5"/>
    </svg>
  ),
  compass: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="12" cy="12" r="9"/>
      <path d="m15.5 8.5-2 5.5-5.5 2 2-5.5 5.5-2Z"/>
    </svg>
  ),
  dict: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 4h11a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4Z"/>
      <path d="M4 16a4 4 0 0 1 4-4h11"/>
      <path d="M9 8h5"/>
    </svg>
  ),
  brain: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 2.8V13a3 3 0 0 0 2 2.8V17a3 3 0 0 0 3 3h.5V4H9Z"/>
      <path d="M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 2.8V13a3 3 0 0 1-2 2.8V17a3 3 0 0 1-3 3h-.5V4H15Z"/>
    </svg>
  ),
  search: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>
    </svg>
  ),
  plus: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" {...p}><path d="M12 5v14M5 12h14"/></svg>),
  x: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" {...p}><path d="M6 6l12 12M18 6 6 18"/></svg>),
  chevL: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m15 6-6 6 6 6"/></svg>),
  chevR: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m9 6 6 6-6 6"/></svg>),
  dots: (p) => (<svg viewBox="0 0 24 24" fill="currentColor" {...p}><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>),
  settings: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 7h10"/><path d="M4 12h6"/><path d="M4 17h12"/>
      <circle cx="18" cy="7" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="20" cy="17" r="2"/>
    </svg>
  ),
  star: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m12 3 2.9 5.9 6.5.95-4.7 4.6 1.1 6.5L12 17.9 6.2 20.95l1.1-6.5L2.6 9.85l6.5-.95L12 3Z"/></svg>),
  check: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m4 12 5 5 11-11"/></svg>),
  fire: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 3c1.5 3 3.5 4.5 3.5 7.5 0 2-1.5 3.5-3.5 3.5-1 0-2-.5-2-2 0-1 .5-1.5.5-2.5-2 1-3.5 3-3.5 5.5 0 3 2.5 5.5 5.5 5.5s5.5-2.5 5.5-5.5c0-5-3-7-6-12Z"/></svg>),
  volume: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M5 9v6h3l5 4V5L8 9H5Z"/><path d="M16 8c1.5 1 1.5 7 0 8"/></svg>),
  trend: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m3 17 5-5 4 4 8-8"/><path d="M15 8h5v5"/></svg>),
  card: (p) => (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18"/></svg>),
};

// ─────────── Status bar ───────────
function StatusBar({ color = 'currentColor' }) {
  return (
    <div className="hi-statusbar" style={{ color }}>
      <span>9:41</span>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <svg width="16" height="11" viewBox="0 0 16 11" fill="currentColor"><path d="M1 10V7h2v3H1zm4 0V5h2v5H5zm4 0V3h2v7H9zm4 0V1h2v9h-2z"/></svg>
        <svg width="14" height="11" viewBox="0 0 14 11" fill="currentColor"><path d="M7 2c2 0 3.8.8 5.2 2l1-1C11.5 1.4 9.3.5 7 .5S2.5 1.4.8 3l1 1C3.2 2.8 5 2 7 2zm0 3c1.2 0 2.3.5 3.2 1.2l1-1C10 4.3 8.6 3.8 7 3.8S4 4.3 2.8 5.2l1 1C4.7 5.5 5.8 5 7 5zm0 3c.6 0 1.2.3 1.7.7l1-1C8.9 7.3 8 7 7 7s-1.9.3-2.7.7l1 1C5.8 8.3 6.4 8 7 8z"/></svg>
        <svg width="24" height="11" viewBox="0 0 24 11" fill="none"><rect x="0.5" y="0.5" width="20" height="10" rx="2.5" stroke="currentColor" opacity="0.4"/><rect x="2" y="2" width="14" height="7" rx="1.2" fill="currentColor"/><rect x="21" y="3.5" width="1.5" height="4" rx="0.5" fill="currentColor" opacity="0.4"/></svg>
      </span>
    </div>
  );
}

// ─────────── Phone frame ───────────
function Phone({ theme, children, statusColor }) {
  return (
    <div className={`hi thA thB thC ${theme}`} style={{ width: 380 }}>
      <div className="hi-phone">
        <div className="hi-notch"/>
        <StatusBar color={statusColor}/>
        <div className="hi-body">
          {children}
        </div>
        <div className="hi-homebar"/>
      </div>
    </div>
  );
}
// strip other theme classes (only one applies)
function ThemedPhone({ theme, children, statusColor = 'currentColor' }) {
  return (
    <div className={`hi ${theme}`} style={{ width: 380 }}>
      <div className="hi-phone">
        <div className="hi-notch"/>
        <StatusBar color={statusColor}/>
        <div className="hi-body">{children}</div>
        <div className="hi-homebar"/>
      </div>
    </div>
  );
}

// ─────────── Tab bar ───────────
const TABS = [
  { id: 'lib',  label: 'Мои книги', icon: Ic.books },
  { id: 'cat',  label: 'Каталог',   icon: Ic.compass },
  { id: 'dict', label: 'Словарь',   icon: Ic.dict },
  { id: 'learn',label: 'Учить',     icon: Ic.brain },
];
function TabBar({ theme, active = 'lib' }) {
  const cls = theme === 'thA' ? 'tabbar-a' : theme === 'thB' ? 'tabbar-b' : theme === 'thD' ? 'tabbar-d' : 'tabbar-c';
  return (
    <div className={cls}>
      {TABS.map(t => {
        const Ico = t.icon;
        return (
          <div key={t.id} className={`tab ${active === t.id ? 'on' : ''}`} style={{ position: 'relative' }}>
            <Ico />
            <span>{t.label}</span>
            {active === t.id && <span className="tab-dot"/>}
          </div>
        );
      })}
    </div>
  );
}

// ─────────── Sample data ───────────
const LIBRARY_BOOKS = [
  { id: 'gatsby',    t: 'The Great Gatsby',     a: 'F. Scott Fitzgerald', lvl: 'B2', prog: 0.42, color: 'c-olive' },
  { id: '1984',      t: '1984',                 a: 'George Orwell',       lvl: 'B2', prog: 0.18, color: 'c-ink' },
  { id: 'pride',     t: 'Pride & Prejudice',    a: 'Jane Austen',         lvl: 'C1', prog: 0.68, color: 'c-mauve' },
  { id: 'hobbit',    t: 'The Hobbit',           a: 'J.R.R. Tolkien',      lvl: 'B1', prog: 0.05, color: 'c-mustard' },
  { id: 'alchemist', t: 'The Alchemist',        a: 'Paulo Coelho',        lvl: 'B1', prog: 0.91, color: 'c-sage' },
  { id: 'murakami',  t: 'Norwegian Wood',       a: 'Haruki Murakami',     lvl: 'C1', prog: 0.00, color: 'c-rose' },
];

const CATALOG_SECTIONS = [
  { k: '🚀 По твоему уровню', items: [
      { id: 'c1', t: 'Animal Farm',         a: 'George Orwell',       lvl: 'B1', pages: 112, color: 'c-sage' },
      { id: 'c2', t: 'Of Mice and Men',     a: 'John Steinbeck',      lvl: 'B2', pages: 107, color: 'c-clay' },
      { id: 'c3', t: 'The Old Man & the Sea', a: 'E. Hemingway',      lvl: 'B2', pages: 127, color: 'c-ink' },
      { id: 'c4', t: 'Fahrenheit 451',      a: 'Ray Bradbury',        lvl: 'B2', pages: 158, color: 'c-clay' },
  ]},
  { k: 'Короткое — за выходные', items: [
      { id: 'd1', t: 'Flowers for Algernon',  a: 'Daniel Keyes',      lvl: 'B2', pages: 30, color: 'c-mauve' },
      { id: 'd2', t: 'The Yellow Wallpaper',  a: 'Charlotte Gilman',  lvl: 'B2', pages: 18, color: 'c-mustard' },
      { id: 'd3', t: 'The Lottery',            a: 'Shirley Jackson',  lvl: 'B1', pages: 12, color: 'c-olive' },
  ]},
];

const PAGE_TEXT = [
  { type: 'p', parts: [
    't: "In my younger and more ',
    { tr: 'vulnerable', ru: 'уязвимый' },
    ' years my father gave me some advice that I\'ve been ',
    { tr: 'turning', ru: 'прокручиваю' },
    ' over in my mind ever since.'
  ]},
  { type: 'p', parts: [
    '"Whenever you feel like ',
    { tr: 'criticizing', ru: 'критиковать' },
    ' any one," he told me, "just remember that all the people in this world haven\'t had the ',
    { tr: 'advantages', ru: 'преимущества' },
    ' that you\'ve had."'
  ]},
  { type: 'p', parts: [
    'He didn\'t say any more, but we\'ve always been unusually ',
    { tr: 'communicative', ru: 'общительными' },
    ' in a reserved way, and I understood that he meant a great deal more than that.'
  ]},
  { type: 'p', parts: [
    'In ',
    { tr: 'consequence', ru: 'вследствие' },
    ', I\'m inclined to ',
    { tr: 'reserve', ru: 'воздерживаться от' },
    ' all judgments, a habit that has opened up many curious natures to me.'
  ]},
];

const DICTIONARY = [
  { w: 'vulnerable',    t: 'уязвимый',       ex: 'my younger and more vulnerable years', src: 'The Great Gatsby', lvl: 'mastered', d: 12 },
  { w: 'reluctant',     t: 'неохотный',      ex: 'a reluctant smile crossed her face', src: '1984',              lvl: 'review',   d: 0 },
  { w: 'ember',         t: 'уголёк, тлеющий', ex: 'a single ember glowed in the ash',    src: 'The Hobbit',        lvl: 'new',      d: 1 },
  { w: 'solitude',      t: 'уединение',      ex: 'he relished the solitude of dawn',    src: 'Norwegian Wood',    lvl: 'learning', d: 3 },
  { w: 'quaint',        t: 'причудливый',    ex: 'a quaint old village by the sea',     src: 'Pride & Prejudice', lvl: 'mastered', d: 20 },
  { w: 'grasp',         t: 'ухватить(ся)',   ex: 'he could not grasp her meaning',      src: 'The Great Gatsby',  lvl: 'learning', d: 5 },
  { w: 'consequence',   t: 'следствие',      ex: 'in consequence, I reserved judgment', src: 'The Great Gatsby',  lvl: 'new',      d: 0 },
  { w: 'linger',        t: 'задерживаться',  ex: 'the scent lingered in the room',      src: '1984',              lvl: 'review',   d: 0 },
];

// Expose globals
Object.assign(window, {
  Ic, StatusBar, ThemedPhone, TabBar, TABS,
  LIBRARY_BOOKS, CATALOG_SECTIONS, PAGE_TEXT, DICTIONARY,
});
