/* global React */

function Hero({ kicker, title, dek, author, date, readTime, blob = 'cluster-warm.svg', tint = 'lavender' }) {
  return (
    <header className={`ak-hero ak-hero-${tint}`}>
      <div className="ak-hero-text">
        {kicker && <div className="ak-eyebrow">{kicker}</div>}
        <h1 className="ak-hero-title">{title}</h1>
        {dek && <p className="ak-hero-dek">{dek}</p>}
        <div className="ak-byline">
          <div className="ak-byline-av" style={{ background: 'linear-gradient(135deg, #FFC79A, #FF5BA4)' }} />
          <div className="ak-byline-meta">
            <div className="ak-byline-author">{author}</div>
            <div className="ak-byline-sub">{date} · {readTime} read</div>
          </div>
        </div>
      </div>
      <div className="ak-hero-blob">
        <img src={`../../assets/blobs/${blob}`} alt="" />
      </div>
    </header>
  );
}

window.Hero = Hero;
