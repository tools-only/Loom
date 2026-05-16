/* global React */

function Header({ eyebrow, title, query, onQuery }) {
  return (
    <header className="dk-header">
      <div className="dk-header-greet">
        <div className="dk-header-eyebrow">{eyebrow}</div>
        <h1 className="dk-header-title">{title}</h1>
      </div>
      <div className="dk-search">
        <i className="ph-bold ph-magnifying-glass"></i>
        <input
          placeholder="Search reports, metrics, sources…"
          value={query}
          onChange={(e) => onQuery && onQuery(e.target.value)}
        />
      </div>
      <button className="dk-icon-btn" aria-label="Notifications">
        <i className="ph-bold ph-bell"></i>
        <span className="dot"></span>
      </button>
      <button className="dk-icon-btn" aria-label="New">
        <i className="ph-bold ph-plus"></i>
      </button>
    </header>
  );
}

function KPIGrid({ items }) {
  return (
    <div className="dk-kpi-grid">
      {items.map((k, i) => (
        <div key={i} className={`dk-kpi ${k.tint || 'mint'}`}>
          <div className="dk-kpi-label">{k.label}</div>
          <div className="dk-kpi-value">
            {k.value}{k.unit && <span className="unit"> {k.unit}</span>}
          </div>
          {k.delta && (
            <span className={`dk-kpi-delta ${k.deltaDir || 'up'}`}>
              <i className={`ph-bold ${k.deltaDir === 'down' ? 'ph-arrow-down' : 'ph-arrow-up'}`}></i>
              {k.delta}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function BarChart({ data, max }) {
  const peak = max || Math.max(...data.map(d => d.value));
  const tints = ['#D4C5F9', '#FFC79A', '#BDE8C9', '#BFDDEE', '#F7BFD7', '#FFE48A', '#7A5AF8'];
  return (
    <div className="dk-bars">
      {data.map((d, i) => (
        <div key={i} className="dk-bar-col">
          <div className="dk-bar-wrap">
            <div
              className="dk-bar"
              style={{
                height: `${(d.value / peak) * 100}%`,
                background: tints[i % tints.length],
              }}
            ></div>
          </div>
          <div className="dk-bar-label">{d.label}</div>
        </div>
      ))}
    </div>
  );
}

function RainbowProgress({ value = 0.68, title = 'Completion', tags = [] }) {
  return (
    <div className="dk-rainbow-panel">
      <div className="dk-rainbow-eyebrow">Progress</div>
      <h3 className="dk-rainbow-title">{title}</h3>
      <div className="dk-rainbow-track">
        <div className="dk-rainbow-fill" style={{ width: `${value * 100}%` }}></div>
      </div>
      <div className="dk-rainbow-marks">
        {tags.map((t, i) => <span key={i}>{t}</span>)}
      </div>
    </div>
  );
}

function ActivityList({ rows }) {
  const tints = ['var(--pastel-lavender)', 'var(--pastel-peach)', 'var(--pastel-mint)', 'var(--pastel-sky)', 'var(--pastel-petal)'];
  return (
    <div className="dk-activity-list">
      {rows.map((r, i) => (
        <div key={i} className="dk-activity-row">
          <div className="dk-activity-icon" style={{ background: tints[i % tints.length] }}>
            <i className={`ph-bold ${r.icon}`}></i>
          </div>
          <div className="dk-activity-text">
            <div className="dk-activity-name">{r.name}</div>
            <div className="dk-activity-sub">{r.sub}</div>
          </div>
          <div className="dk-activity-meta">{r.meta}</div>
        </div>
      ))}
    </div>
  );
}

function Donut({ slices, total, label }) {
  // Each slice rendered as an SVG arc.
  const radius = 64;
  const stroke = 22;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="dk-donut-wrap">
      <div className="dk-donut">
        <svg width="160" height="160" viewBox="0 0 160 160">
          <circle cx="80" cy="80" r={radius} fill="none" stroke="var(--cloud)" strokeWidth={stroke}/>
          {slices.map((s, i) => {
            const len = (s.value / total) * circumference;
            const el = (
              <circle
                key={i}
                cx="80" cy="80" r={radius}
                fill="none"
                stroke={s.color}
                strokeWidth={stroke}
                strokeDasharray={`${len} ${circumference - len}`}
                strokeDashoffset={-offset}
                strokeLinecap="round"
              />
            );
            offset += len;
            return el;
          })}
        </svg>
        <div className="dk-donut-center">
          <div className="dk-donut-value">{total}</div>
          <div className="dk-donut-label">{label}</div>
        </div>
      </div>
      <div className="dk-donut-legend">
        {slices.map((s, i) => (
          <div key={i} className="dk-donut-legend-row">
            <span className="dot" style={{ background: s.color }}></span>
            <span className="lbl">{s.label}</span>
            <span className="val">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

window.Header = Header;
window.KPIGrid = KPIGrid;
window.BarChart = BarChart;
window.RainbowProgress = RainbowProgress;
window.ActivityList = ActivityList;
window.Donut = Donut;
