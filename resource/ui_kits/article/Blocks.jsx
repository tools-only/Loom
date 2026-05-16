/* global React */

function PullQuote({ children, by }) {
  return (
    <figure className="ak-pullquote">
      <div className="ak-pq-mark">"</div>
      <blockquote className="ak-pq-body">{children}</blockquote>
      {by && <figcaption className="ak-pq-by">— {by}</figcaption>}
    </figure>
  );
}

function Callout({ kind = 'info', title, children }) {
  const icon = { info: 'ph-info', note: 'ph-lightbulb', warning: 'ph-warning-circle', tip: 'ph-sparkle' }[kind] || 'ph-info';
  return (
    <aside className={`ak-callout ak-callout-${kind}`}>
      <div className="ak-callout-icon">
        <i className={`ph-bold ${icon}`}></i>
      </div>
      <div className="ak-callout-body">
        {title && <div className="ak-callout-title">{title}</div>}
        <div className="ak-callout-text">{children}</div>
      </div>
    </aside>
  );
}

function Figure({ src, alt = '', caption, blob }) {
  return (
    <figure className="ak-figure">
      <div className="ak-figure-img">
        {blob ? <img src={`../../assets/blobs/${blob}`} alt={alt} /> : <img src={src} alt={alt} />}
      </div>
      {caption && <figcaption className="ak-figure-cap">{caption}</figcaption>}
    </figure>
  );
}

function StatRow({ stats }) {
  return (
    <div className="ak-statrow">
      {stats.map((s, i) => (
        <div key={i} className={`ak-stat ak-stat-${s.tint || 'mint'}`}>
          <div className="ak-stat-label">{s.label}</div>
          <div className="ak-stat-value">
            {s.value}{s.unit && <span className="ak-stat-unit"> {s.unit}</span>}
          </div>
          {s.sub && <div className="ak-stat-sub">{s.sub}</div>}
        </div>
      ))}
    </div>
  );
}

function EndCard({ title, dek, primary, secondary }) {
  return (
    <div className="ak-endcard">
      <img className="ak-endcard-blob" src="../../assets/blobs/cluster-electric.svg" alt="" />
      <div className="ak-endcard-text">
        <h2 className="ak-endcard-title">{title}</h2>
        {dek && <p className="ak-endcard-dek">{dek}</p>}
        <div className="ak-endcard-actions">
          {primary && <button className="ak-btn ak-btn-primary">{primary}</button>}
          {secondary && <button className="ak-btn ak-btn-ghost-light">{secondary}</button>}
        </div>
      </div>
    </div>
  );
}

window.PullQuote = PullQuote;
window.Callout = Callout;
window.Figure = Figure;
window.StatRow = StatRow;
window.EndCard = EndCard;
