/* global React */

function TopBar({ progress = 0.42 }) {
  return (
    <div className="ak-topbar">
      <a className="ak-brand" href="#">
        <img src="../../assets/logo-mark.svg" alt="" />
        <span>bloom</span>
      </a>
      <div className="ak-progress">
        <div className="ak-progress-fill" style={{ width: `${progress * 100}%` }} />
      </div>
      <div className="ak-actions">
        <button className="ak-icon-btn" aria-label="Share">
          <i className="ph-bold ph-share-network"></i>
        </button>
        <button className="ak-icon-btn" aria-label="Bookmark">
          <i className="ph-bold ph-bookmark-simple"></i>
        </button>
      </div>
    </div>
  );
}

window.TopBar = TopBar;
