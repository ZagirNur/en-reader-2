// Sketchy wireframe primitives — phone frame, icons, covers, etc.

const { useState, useEffect, useRef } = React;

// ─── Status bar ───
function StatusBar({ dark }) {
  return (
    <div className="status-bar" style={dark ? { color: '#e8e6df' } : {}}>
      <span>9:41</span>
      <span className="right">
        <span>•••</span>
        <span>◗</span>
      </span>
    </div>
  );
}

// ─── Phone frame ───
function Phone({ children, dark, label, sub, w }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', width: w || 360 }}>
      {label && <div className="frame-caption">{label}</div>}
      {sub && <div className="frame-sub">{sub}</div>}
      <div className="phone" style={dark ? { background: '#1a1a1a' } : {}}>
        <div className="phone-notch" />
        <StatusBar dark={dark} />
        <div className="screen-body" style={dark ? { color: '#e8e6df' } : {}}>
          {children}
        </div>
      </div>
    </div>
  );
}

// ─── Hand-drawn icon (text glyph) ───
function Ico({ children, size = 20 }) {
  return <span className="ico" style={{ fontSize: size }}>{children}</span>;
}

// ─── App top bar ───
function TopBar({ title, left, right }) {
  return (
    <div className="app-top">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {left}
        {title && <h1>{title}</h1>}
      </div>
      <div className="icon-row">{right}</div>
    </div>
  );
}

// ─── Bottom tab bar ───
function TabBar({ active = 'books', tabs }) {
  const def = tabs || [
    { id: 'books', icon: '▣', label: 'My Books' },
    { id: 'catalog', icon: '☰', label: 'Catalog' },
    { id: 'dict', icon: 'A', label: 'Dictionary' },
    { id: 'train', icon: '✦', label: 'Train' },
  ];
  return (
    <div className="tab-bar">
      {def.map(t => (
        <div key={t.id} className={`tab ${t.id === active ? 'active' : ''}`}>
          <div className="tab-icon">{t.icon}</div>
          <div>{t.label}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Book cover with placeholder ───
function BookCover({ title, author, variant = 1, style }) {
  return (
    <div className={`book-cover cv-${variant}`} style={style}>
      <div className="cover-stripes" />
      <div className="cover-title">{title}</div>
      {author && <div className="cover-author">{author}</div>}
    </div>
  );
}

// ─── Book card ───
function BookCard({ title, author, variant, progress, words }) {
  return (
    <div className="book-card">
      <BookCover title={title} author={author} variant={variant} />
      <div className="meta">
        <div className="title">{title}</div>
        <div className="author">{author}</div>
        {typeof progress === 'number' && (
          <div className="progress"><div style={{ width: `${progress}%` }} /></div>
        )}
        {words != null && (
          <div className="author" style={{ marginTop: 2 }}>✦ {words} words saved</div>
        )}
      </div>
    </div>
  );
}

// ─── Add book card ───
function AddBookCard({ label = 'Add book' }) {
  return (
    <div>
      <div className="add-card">
        <div className="plus">+</div>
        <div className="label">{label}</div>
      </div>
      <div style={{ height: 40 }} />
    </div>
  );
}

// ─── Books grid (2-column) ───
function BooksGrid({ books, withAdd = true, addLabel }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: '4px 0 16px' }}>
      {books.map((b, i) => <BookCard key={i} {...b} />)}
      {withAdd && <AddBookCard label={addLabel} />}
    </div>
  );
}

// ─── Section header ───
function SectionHead({ children, action }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginTop: 18, marginBottom: 8,
    }}>
      <div style={{ fontFamily: 'var(--hand-bold)', fontSize: 18, fontWeight: 700 }}>{children}</div>
      {action && <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>{action}</div>}
    </div>
  );
}

// ─── Annotation note (sticky-style for canvas overlay) ───
function Note({ children, top, left, right, bottom, rotate = -2, w = 180, color = '#fef4a8' }) {
  return (
    <div style={{
      position: 'absolute', top, left, right, bottom, width: w,
      background: color, padding: '12px 14px',
      fontFamily: 'var(--hand-bold)',
      fontSize: 14, lineHeight: 1.3,
      boxShadow: '2px 2px 6px rgba(0,0,0,0.15)',
      transform: `rotate(${rotate}deg)`,
      zIndex: 8,
      color: '#3a2a10',
    }}>{children}</div>
  );
}

// ─── Arrow callout (curved hand-drawn arrow) ───
function Arrow({ from, to, color = '#d4734a', label }) {
  // from: {x, y}, to: {x, y}
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const cx = from.x + dx / 2 + dy * 0.2;
  const cy = from.y + dy / 2 - dx * 0.2;
  return (
    <svg style={{
      position: 'absolute', top: 0, left: 0,
      width: '100%', height: '100%',
      pointerEvents: 'none',
      overflow: 'visible',
      zIndex: 7,
    }}>
      <path
        d={`M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`}
        stroke={color} strokeWidth="2" fill="none"
        strokeLinecap="round"
        strokeDasharray="0"
      />
      <polygon
        points={`${to.x},${to.y} ${to.x - 8},${to.y - 4} ${to.x - 6},${to.y + 6}`}
        fill={color}
      />
      {label && (
        <text x={cx} y={cy - 6} fontFamily="Caveat, cursive" fontSize="14" fill={color} textAnchor="middle">
          {label}
        </text>
      )}
    </svg>
  );
}

Object.assign(window, {
  Phone, StatusBar, Ico, TopBar, TabBar,
  BookCover, BookCard, AddBookCard, BooksGrid,
  SectionHead, Note, Arrow,
});
