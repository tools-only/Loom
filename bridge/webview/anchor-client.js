// Anchor Client — injects interactive handles and captures user ops
// Uses WebSocket for receiving HTML and sending ops

const Anchor = {
  ws: null,
  _pingTimer: null,
  container: null,
  statusEl: null,
  infoEl: null,
  shuttingDown: false,
  currentHtml: '',
  openPopup: null,
  pendingOps: [],   // { op, target, instruction, anchorId, timestamp }
  currentFileId: null,
  _allowIncomingHtml: false,
  _selectedPromptRoute: '',
  _pendingPromptRoute: '',

  _timing: null,  // per-interaction timing { t0_click, t1_built, t2_sent, t3_ack, t4_thinking, t5_patch, t6_dom }

  opDefs: {
    refine:    { label: 'Refine',     icon: 'ph-sparkle',                  needsInput: true,  inputLabel: 'What to change?' },
    lock:      { label: 'Lock',       icon: 'ph-lock',                     needsInput: 'optional', inputLabel: 'Reason (optional)' },
    expand:    { label: 'Expand',     icon: 'ph-arrows-out-line-vertical', needsInput: 'optional', inputLabel: 'What to expand? (optional)' },
    shorten:   { label: 'Shorten',    icon: 'ph-arrows-in-line-vertical',  needsInput: 'optional', inputLabel: 'Any specifics? (optional)' },
    longer:    { label: 'Longer',     icon: 'ph-text-aa',                  needsInput: 'optional', inputLabel: 'Any specifics? (optional)' },
    edit:      { label: 'Edit text',  icon: 'ph-pencil-simple',            needsInput: true,  inputLabel: 'Edit to:' },
    annotate:  { label: 'Annotate',   icon: 'ph-note-pencil',              needsInput: true,  inputLabel: 'Note:' },
    branch:    { label: 'Branch',     icon: 'ph-git-branch',               needsInput: true,  inputLabel: 'Alternative direction:' },
    restructure: { label: 'Restructure', icon: 'ph-squares-four',          needsInput: true, inputLabel: 'What to restructure?' },
  },

  // Fixed platform handles — always available regardless of model output.
  // The model may extend via data-handles, but can never reduce below this set.
  defaultHandles: ['refine', 'expand', 'shorten', 'annotate', 'branch', 'edit'],

  init() {
    this.container = document.getElementById('anchor-content');
    this.statusEl = document.getElementById('status');
    this.infoEl = document.getElementById('info');
    this.processingEl = document.getElementById('processing');
    this.processingLabel = this.processingEl?.querySelector('.processing-label');
    this.processingTarget = this.processingEl?.querySelector('.processing-target');
    this._processingAnchors = new Set();
    this._processingTimer = null;
    this.sessionId = this._loadOrCreateSessionId();
    this._blockConfig = this._loadBlockConfig();
    this._defaultProcessor = this._loadDefaultProcessorFromStorage();
    this.connect();

    // Wire up workspace + Phase 1/3/4 modules
    if (window.WorkspacePanel)   WorkspacePanel.init(this);
    if (window.PromptPanel)      PromptPanel.init(this);
    if (window.ContextPanel)     ContextPanel.init(this);
    if (window.SelectionToolbar) SelectionToolbar.init(this);
    if (window.TimelinePanel)    TimelinePanel.init(this);
    if (window.HistoryPanel)     HistoryPanel.init(this);
    if (window.DebateOverlay)    DebateOverlay.init(this);
    this._initSidePanelToggles();
    this._initExecuteAll();
    this._initShutdown();
    this._initHomeNav();
    this._initPromptBar();
    this._initHomeSuggestions();
    this._initHashRouting();
    this._initAnchorSelect();
  },

  _initHashRouting() {
    window.addEventListener('hashchange', () => this._handleHashChange());
    const hash = window.location.hash.slice(1);
    if (!hash) {
      this.currentHtml = '';
      this.container.innerHTML = '';
      this._syncHomeVisibility();
      this._updateToolbarTabs('');
    }
    else if (hash === 'overview') { this._loadOverview(); }
    else if (['market','position','target','sentiment'].includes(hash)) { this._loadBlogDomain(hash); }
  },

  _handleHashChange() {
    const hash = window.location.hash.slice(1);
    if (!hash) {
      this.currentHtml = '';
      this.container.innerHTML = '';
      this._syncHomeVisibility();
      this._updateToolbarTabs('');
    }
    else if (hash === 'overview') { this._loadOverview(); }
    else if (['market','position','target','sentiment'].includes(hash)) { this._loadBlogDomain(hash); }
    else {
      this.currentHtml = '';
      this.container.innerHTML = '';
      this._syncHomeVisibility();
    }
  },

  async _loadOverview() {
    window.location.hash = 'overview';
    try {
      const [mRes, tRes, sRes] = await Promise.all([
        fetch('/api/inbox/market').then(r => r.json()),
        fetch('/api/inbox/target').then(r => r.json()),
        fetch('/api/inbox/sentiment').then(r => r.json())
      ]);
      this._renderOverview({
        market: mRes.items || [],
        target: tRes.items || [],
        sentiment: sRes.items || [],
        counts: { ...(mRes.meta||{}), ...(tRes.meta||{}), ...(sRes.meta||{}) }
      });
      this._syncHomeVisibility();
      this._updateToolbarTabs('overview');
    } catch (e) { console.error('[_loadOverview]', e); }
  },

  _renderOverview(data) {
    const sourceTag = (src) => {
      if (!src) return '';
      if (src.startsWith('feed:')) src = src.slice(5);
      return '<span class="blog-source-tag">' + _escHtml(src.split(':')[0].split('-').map(w => w[0] ? w[0].toUpperCase() : '').join('')) + '</span>';
    };
    const timeAgo = (ts) => {
      if (!ts) return '';
      const diff = Date.now() - new Date(ts).getTime();
      if (diff < 60000) return '刚刚';
      if (diff < 3600000) return Math.floor(diff/60000)+'m前';
      if (diff < 86400000) return Math.floor(diff/3600000)+'h前';
      return new Date(ts).toLocaleDateString('zh-CN',{month:'short',day:'numeric'});
    };
    const icon = (name) => '<i class="ph-bold ' + name + '"></i>';

    const card = (id, color, icon, title, summary, source, ts, url, tags) =>
      `<section class="anc-section anc-section--gc anc-section--${color}" data-anc="overview.card.${_escHtml(id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
        <div class="blog-card-header">
          <span class="blog-card-icon">${icon}</span>
          <div>
            <div class="blog-card-title" data-anc="overview.card.title" data-handles="edit,refine">${_escHtml(title)}</div>
            <div class="blog-card-meta">${sourceTag(source)} · ${timeAgo(ts)}</div>
          </div>
        </div>
        <p class="blog-card-summary" data-anc="overview.card.summary" data-handles="shorten,longer,edit,refine">${_escHtml(summary||'')}</p>
        ${url ? '<a class="blog-card-link" href="'+_escHtml(url)+'" target="_blank" rel="noopener">查看原文 ↗</a>' : ''}
        ${tags ? '<div class="blog-card-tags">'+tags.map(t=>'<span class="blog-ticker-tag">'+_escHtml(t)+'</span>').join('')+'</div>' : ''}
      </section>`;

    // Market highlights: filings + macro + news
    const mFilings = data.market.filter(i => i.payload?.kind==='filing').slice(0,2);
    const mNews    = data.market.filter(i => ['news','macro','commentary'].includes(i.payload?.kind)).slice(0,2);
    const mAnalyst = data.market.filter(i => ['price_alert','analyst'].includes(i.payload?.kind)).slice(0,2);

    // Target highlights
    const tTop = data.target.slice(0,2);

    // Sentiment highlights
    const sFear = data.sentiment.filter(i => i.source?.includes('fear-greed')).slice(0,1);
    const stTop = data.sentiment.filter(i => i.source?.includes('stocktwits')).slice(0,1);
    const rTop  = data.sentiment.filter(i => i.source?.includes('reddit')).slice(0,1);

    const total = (data.market.length + data.target.length + data.sentiment.length);

    const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>市场总览</title></head>
<body>
<div class="blog-page blog-page--overview">
  <header class="blog-header anc-section anc-section--gc anc-section--aurora" data-anc="overview.header" data-handles="refine,restructure">
    <div class="blog-header-inner">
      <span class="blog-domain-icon">${icon('ph-chart-pie-slice')}</span>
      <div>
        <h1 class="blog-domain-title" data-anc="overview.title" data-handles="edit,refine">市场总览</h1>
        <p class="blog-domain-count" data-anc="overview.count" data-handles="edit,refine">市场 <strong>${data.market.length}</strong> · 标的 <strong>${data.target.length}</strong> · 情绪 <strong>${data.sentiment.length}</strong> · 共 <strong>${total}</strong> 条</p>
      </div>
    </div>
  </header>

  <main class="blog-content">
    <div class="blog-section-label"><i class="ph-bold ph-newspaper"></i> 重要文件 & 宏观</div>
    <div class="blog-card-grid">
      ${mFilings.map(it => card(it.id, 'aurora', icon('ph-file-text'), it.title, it.summary, it.source, it.timestamp, it.payload?.url, it.payload?.tickers)).join('')}
      ${mNews.map(it => card(it.id, 'arctic', it.payload?.kind==='macro'?icon('ph-chart-line-up'):icon('ph-newspaper'), it.title, it.summary, it.source, it.timestamp, it.payload?.url, it.payload?.tickers)).join('')}
      ${mAnalyst.map(it => card(it.id, 'warm', icon('ph-crosshair'), it.title, it.summary, it.source, it.timestamp, it.payload?.url, it.payload?.tickers)).join('')}
      ${(mFilings.length+mNews.length+mAnalyst.length)===0?'<div class="blog-empty-row">暂无市场数据</div>':''}
    </div>

    <div class="blog-section-label"><i class="ph-bold ph-crosshair"></i> 热门标的</div>
    <div class="blog-card-grid">
      ${tTop.map(it => card(it.id, 'warm', icon('ph-crosshair'), it.title, it.summary, it.source, it.timestamp, it.payload?.url, it.payload?.tickers)).join('')}
      ${tTop.length===0?'<div class="blog-empty-row">暂无标的数据</div>':''}
    </div>

    <div class="blog-section-label"><i class="ph-bold ph-pulse"></i> 市场情绪</div>
    <div class="blog-card-grid">
      ${sFear.map(it => card(it.id, 'flame', icon('ph-pulse'), it.title, it.summary, 'fear-greed', it.timestamp, null, null)).join('')}
      ${stTop.map(it => card(it.id, 'cool', it.payload?.bull_ratio>0.5?icon('ph-trend-up'):icon('ph-trend-down'), it.title, it.summary, 'stocktwits', it.timestamp, null, null)).join('')}
      ${rTop.map(it => card(it.id, 'aurora', icon('ph-chat-circle-text'), it.title, it.summary, it.source, it.timestamp, null, it.payload?.tickers)).join('')}
      ${(sFear.length+stTop.length+rTop.length)===0?'<div class="blog-empty-row">暂无情绪数据</div>':''}
    </div>
  </main>
</div>
</body>
</html>`;

    this.currentHtml = html;
    this.container.innerHTML = '';
    const template = document.createElement('template');
    template.innerHTML = html;
    document.getElementById('anchor-content').appendChild(template.content.cloneNode(true));
  },

  async _loadBlogDomain(domain) {
    try {
      const data = await fetch('/api/inbox/' + domain).then(r => r.json());
      const counts = data.meta || {};
      const items = data.items || [];
      this._renderBlogPage(domain, items, counts);
      this._syncHomeVisibility();
      this._updateToolbarTabs(domain);
    } catch (e) {
      console.error('[_loadBlogDomain]', e);
    }
  },

  _renderBlogPage(domain, items, counts) {
    const icon = (name) => '<i class="ph-bold ' + name + '"></i>';
    const META = {
      market:    { icon: icon('ph-newspaper'), label: '市场情报', color: 'aurora' },
      position:  { icon: icon('ph-briefcase'), label: '仓位管理', color: 'cool'   },
      target:    { icon: icon('ph-crosshair'), label: '标的跟踪', color: 'warm'   },
      sentiment: { icon: icon('ph-pulse'), label: '市场情绪', color: 'flame'  }
    };
    const meta = META[domain] || META.market;
    const count = counts[domain] || 0;

    const sourceTag = (src) => {
      if (!src) return '';
      if (src.startsWith('feed:')) src = src.slice(5);
      const parts = src.split(':');
      const short = parts[0].split('-').map(w => w[0] ? w[0].toUpperCase() : '').join('');
      return '<span class="blog-source-tag">' + _escHtml(short) + '</span>';
    };

    const timeAgo = (ts) => {
      if (!ts) return '';
      const d = new Date(ts);
      const now = Date.now();
      const diff = now - d.getTime();
      if (diff < 60000) return '刚刚';
      if (diff < 3600000) return Math.floor(diff/60000)+'m前';
      if (diff < 86400000) return Math.floor(diff/3600000)+'h前';
      return d.toLocaleDateString('zh-CN', { month:'short', day:'numeric' });
    };

    // ── Domain-specific card builders ──────────────────────────────
    const renderMarketCards = (items) => {
      const filings = items.filter(i => i.payload?.kind === 'filing');
      const macros  = items.filter(i => i.payload?.kind === 'macro');
      const news    = items.filter(i => i.payload?.kind === 'news' || i.payload?.kind === 'commentary');
      const alerts  = items.filter(i => i.payload?.kind === 'price_alert' || i.payload?.kind === 'analyst');

      return `
      <div class="blog-section-label"><i class="ph-bold ph-file-text"></i> 重要文件</div>
      <div class="blog-card-grid">${filings.slice(0,3).map(it => `
        <div class="anc-section anc-section--gc anc-section--aurora blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-file-text')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">${sourceTag(it.source)} · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          ${it.payload?.url ? '<a class="blog-card-link" href="'+_escHtml(it.payload.url)+'" target="_blank" rel="noopener">查看原文 ↗</a>' : ''}
        </div>`).join('')}${filings.length === 0 ? '<div class="blog-empty-row">暂无 SEC 文件</div>' : ''}</div>

      <div class="blog-section-label"><i class="ph-bold ph-chart-line-up"></i> 宏观 & 新闻</div>
      <div class="blog-card-grid">${macros.slice(0,2).concat(news.slice(0,2)).map(it => `
        <div class="anc-section anc-section--gc anc-section--arctic blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${it.payload?.kind === 'macro' ? icon('ph-chart-line-up') : icon('ph-newspaper')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">${sourceTag(it.source)} · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          ${it.payload?.url ? '<a class="blog-card-link" href="'+_escHtml(it.payload.url)+'" target="_blank" rel="noopener">查看原文 ↗</a>' : ''}
        </div>`).join('')}${(macros.length + news.length) === 0 ? '<div class="blog-empty-row">暂无新闻</div>' : ''}</div>

      <div class="blog-section-label"><i class="ph-bold ph-crosshair"></i> 分析师观点</div>
      <div class="blog-card-grid">${alerts.slice(0,3).map(it => `
        <div class="anc-section anc-section--gc anc-section--warm blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-crosshair')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">${sourceTag(it.source)} · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          ${it.payload?.url ? '<a class="blog-card-link" href="'+_escHtml(it.payload.url)+'" target="_blank" rel="noopener">查看原文 ↗</a>' : ''}
        </div>`).join('')}${alerts.length === 0 ? '<div class="blog-empty-row">暂无分析师更新</div>' : ''}</div>`;
    };

    const renderPositionCards = (items) => {
      if (items.length === 0) return '<div class="blog-empty">暂无仓位记录 · 使用 #position 新增仓位</div>';
      return '<div class="blog-card-grid">' + items.map(it => {
        const pnl = it.payload?.pnl_pct;
        const pnlColor = pnl > 0 ? '#16a34a' : pnl < 0 ? '#dc2626' : 'var(--fg-2)';
        const pnlSign = pnl > 0 ? '+' : '';
        return `
        <div class="anc-section anc-section--gc anc-section--ocean blog-card blog-card--position" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-briefcase')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">${sourceTag(it.source)} · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <div class="position-pnl" style="color:${pnlColor}">${pnlSign}${pnl}%</div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          <div class="blog-card-tags">
            ${(it.payload?.tickers || []).map(t => '<span class="blog-ticker-tag">'+_escHtml(t)+'</span>').join('')}
          </div>
        </div>`;
      }).join('') + '</div>';
    };

    const renderTargetCards = (items) => {
      if (items.length === 0) return '<div class="blog-empty">暂无标的跟踪 · 使用 #target 新增标的</div>';
      return '<div class="blog-card-grid">' + items.map(it => `
        <div class="anc-section anc-section--gc anc-section--warm blog-card blog-card--target" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-crosshair')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">${sourceTag(it.source)} · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          <div class="blog-card-tags">
            ${(it.payload?.tickers || []).map(t => '<span class="blog-ticker-tag">'+_escHtml(t)+'</span>').join('')}
          </div>
          ${it.payload?.url ? '<a class="blog-card-link" href="'+_escHtml(it.payload.url)+'" target="_blank" rel="noopener">查看详情 ↗</a>' : ''}
        </div>`).join('') + '</div>';
    };

    const renderSentimentCards = (items) => {
      const social  = items.filter(i => i.payload?.kind === 'social');
      const fear   = items.filter(i => i.source?.includes('fear-greed'));
      const reddit = items.filter(i => i.source?.includes('reddit'));
      const st     = items.filter(i => i.source?.includes('stocktwits'));
      const aaii   = items.filter(i => i.source?.includes('aaii'));

      return `
      <div class="blog-section-label"><i class="ph-bold ph-pulse"></i> 市场情绪综合</div>
      <div class="blog-card-grid">${fear.slice(0,2).map(it => `
        <div class="anc-section anc-section--gc anc-section--flame blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-pulse')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">CNN 恐慌贪婪指数 · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
        </div>`).join('')}${fear.length === 0 ? '<div class="blog-empty-row">暂无数据</div>' : ''}</div>

      <div class="blog-section-label"><i class="ph-bold ph-chart-donut"></i> StockTwits 情绪异动</div>
      <div class="blog-card-grid">${st.slice(0,3).map(it => `
        <div class="anc-section anc-section--gc anc-section--cool blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${it.payload?.bull_ratio > 0.5 ? icon('ph-trend-up') : icon('ph-trend-down')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">StockTwits · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          <div class="sentiment-bar">
            <div class="sentiment-bar-fill" style="width:${Math.round((it.payload?.bull_ratio||0.5)*100)}%;background:${it.payload?.bull_ratio > 0.5 ? '#16a34a' : '#dc2626'}"></div>
          </div>
          <div class="sentiment-bar-labels"><span>看多 ${Math.round((it.payload?.bull_ratio||0.5)*100)}%</span><span>看空 ${Math.round((1-(it.payload?.bull_ratio||0.5))*100)}%</span></div>
        </div>`).join('')}${st.length === 0 ? '<div class="blog-empty-row">暂无情绪异动</div>' : ''}</div>

      <div class="blog-section-label"><i class="ph-bold ph-chat-circle-text"></i> 社区热帖</div>
      <div class="blog-card-grid">${reddit.slice(0,3).map(it => `
        <div class="anc-section anc-section--gc anc-section--aurora blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-chat-circle-text')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">r/${_escHtml(it.payload?.subreddit||'')} · 👍 ${(it.payload?.upvotes||0).toLocaleString()} · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <p class="blog-card-summary">${_escHtml(it.summary || '')}</p>
          <div class="blog-card-tags">${(it.payload?.tickers||[]).map(t => '<span class="blog-ticker-tag">$'+_escHtml(t)+'</span>').join('')}</div>
        </div>`).join('')}${reddit.length === 0 ? '<div class="blog-empty-row">暂无社区帖子</div>' : ''}</div>

      <div class="blog-section-label"><i class="ph-bold ph-clipboard-text"></i> AAII 散户调查</div>
      <div class="blog-card-grid">${aaii.slice(0,1).map(it => `
        <div class="anc-section anc-section--gc anc-section--berry blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
          <div class="blog-card-header">
            <span class="blog-card-icon">${icon('ph-clipboard-text')}</span>
            <div>
              <div class="blog-card-title">${_escHtml(it.title)}</div>
              <div class="blog-card-meta">AAII · ${timeAgo(it.timestamp)}</div>
            </div>
          </div>
          <div class="aaii-bars">
            <div class="aaii-row"><span>看涨</span><div class="aaii-bar"><div class="aaii-fill" style="width:${it.payload?.bullish_pct||0}%"></div></div><span>${it.payload?.bullish_pct||0}%</span></div>
            <div class="aaii-row"><span>看跌</span><div class="aaii-bar"><div class="aaii-fill aaii-fill--bear" style="width:${it.payload?.bearish_pct||0}%"></div></div><span>${it.payload?.bearish_pct||0}%</span></div>
            <div class="aaii-row"><span>中性</span><div class="aaii-bar"><div class="aaii-fill aaii-fill--neutral" style="width:${it.payload?.neutral_pct||0}%"></div></div><span>${it.payload?.neutral_pct||0}%</span></div>
          </div>
        </div>`).join('')}${aaii.length === 0 ? '<div class="blog-empty-row">暂无 AAII 数据</div>' : ''}</div>`;
    };

    let cardsHtml = '';
    if (domain === 'market')    cardsHtml = renderMarketCards(items);
    else if (domain === 'position') cardsHtml = renderPositionCards(items);
    else if (domain === 'target')  cardsHtml = renderTargetCards(items);
    else if (domain === 'sentiment') cardsHtml = renderSentimentCards(items);
    else cardsHtml = items.length === 0 ? '<div class="blog-empty">暂无内容</div>' : items.map(it => `
      <div class="anc-section anc-section--gc anc-section--arctic blog-card" data-anc="${domain}.card.${_escHtml(it.id)}" data-handles="refine,expand,shorten,longer,edit,annotate,branch">
        <div class="blog-card-title">${_escHtml(it.title)}</div>
        <p class="blog-card-summary">${_escHtml(it.summary||'')}</p>
        <div class="blog-card-meta">${sourceTag(it.source)} · ${timeAgo(it.timestamp)}</div>
      </div>`).join('');

    const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>${meta.label}</title></head>
<body>
<div class="blog-page blog-page--${domain}">
  <header class="blog-header anc-section anc-section--gc anc-section--${meta.color}" data-anc="${domain}.header" data-handles="refine,restructure">
    <div class="blog-header-inner">
      <span class="blog-domain-icon">${meta.icon}</span>
      <div>
        <h1 class="blog-domain-title" data-anc="${domain}.title" data-handles="edit,refine">${meta.label}</h1>
        <p class="blog-domain-count" data-anc="${domain}.count" data-handles="edit,refine">共 <strong>${count}</strong> 条推送 · ${items.length} 条已加载</p>
      </div>
    </div>
  </header>
  <main class="blog-content">
    ${cardsHtml}
  </main>
</div>
</body>
</html>`;

    this.currentHtml = html;
    this.container.innerHTML = '';
    const template = document.createElement('template');
    template.innerHTML = html;
    document.getElementById('anchor-content').appendChild(template.content.cloneNode(true));
  },

  _updateToolbarTabs(activeDomain) {
    document.querySelectorAll('.domain-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.domain === activeDomain);
    });
  },

  _navigateToRoute(route) {
    const next = String(route || '').trim();
    if (!next) return;
    const current = window.location.hash.slice(1);
    if (current === next) {
      if (next === 'overview') this._loadOverview();
      else if (['market','position','target','sentiment'].includes(next)) this._loadBlogDomain(next);
      return;
    }
    window.location.hash = next;
  },

  _bindGeneratedPageRoute(route) {
    const next = String(route || '').trim();
    if (!next) return;
    if (!['overview','market','position','target','sentiment'].includes(next)) return;
    if (window.location.hash.slice(1) !== next) {
      history.replaceState(null, '', '#' + next);
    }
    this._updateToolbarTabs(next);
  },

  _initPromptBar() {
    const input = document.getElementById('anchor-prompt-input');
    const btn   = document.getElementById('anchor-prompt-submit');
    if (!input || !btn) return;
    const submit = () => {
      const text = input.value.trim();
      const route = input.dataset.route || this._selectedPromptRoute || '';
      if (text) {
        this.submitPrompt(text, route);
        input.value = '';
        delete input.dataset.route;
        this._selectedPromptRoute = '';
        document.querySelectorAll('#anchor-home button[data-route].is-selected').forEach(el => el.classList.remove('is-selected'));
      }
    };
    btn.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  },

  _initHomeSuggestions() {
    const input = document.getElementById('anchor-prompt-input');
    if (!input) return;
    document.querySelectorAll('#anchor-home button[data-prompt], #anchor-home button[data-route]').forEach(btn => {
      btn.addEventListener('click', () => {
        const route = btn.getAttribute('data-route');
        const prompt = btn.getAttribute('data-prompt') || '';
        if (prompt) {
          input.value = prompt;
          if (route) {
            input.dataset.route = route;
            this._selectedPromptRoute = route;
            document.querySelectorAll('#anchor-home button[data-route].is-selected').forEach(el => el.classList.remove('is-selected'));
            btn.classList.add('is-selected');
          } else {
            delete input.dataset.route;
            this._selectedPromptRoute = '';
          }
          input.focus();
        }
      });
    });
  },

  _inferRoute(text) {
    const t = (text || '').toLowerCase();
    if (/市场总览|market.?brief|overview|宏观.*新闻|风险日历|today/.test(t)) return 'overview';
    if (/持仓|仓位|portfolio|position|复盘/.test(t)) return 'position';
    if (/标的|target|tracker|nvda|aapl|tsla|触发/.test(t)) return 'target';
    if (/情绪|sentiment|fear.?greed|reddit|stocktwits/.test(t)) return 'sentiment';
    if (/宏观|风险偏好|market.?intel|macro/.test(t)) return 'market';
    return 'overview';
  },

  submitPrompt(text, route = '') {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.toast('Not connected — please wait');
      return;
    }
    this._allowIncomingHtml = true;
    const effectiveRoute = String(route || '').trim() || this._inferRoute(text);
    this._pendingPromptRoute = effectiveRoute;
    // Navigate immediately without waiting for hashchange (avoids async flicker over home)
    history.pushState(null, '', '#' + effectiveRoute);
    const home = document.getElementById('anchor-home');
    const shell = document.getElementById('anchor-shell');
    if (home) home.classList.add('is-hidden');
    if (shell) shell.classList.add('has-content');
    this.container.innerHTML = '';
    this._updateToolbarTabs(effectiveRoute);
    this.ws.send(JSON.stringify({ type: 'prompt', text, route: effectiveRoute, ts: Date.now() }));
    this.showProcessing('Generating…');
    this.toast('Prompt sent');
  },

  _initExecuteAll() {
    const btn = document.getElementById('anchor-execute-all');
    if (!btn) return;
    btn.addEventListener('click', () => this.executeAll());
  },

  _initShutdown() {
    const btn = document.getElementById('anchor-shutdown');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      this.shuttingDown = true;
      this.setStatus('', 'Shutting down...');
      this.toast('Shutting down Anchor services');
      try {
        const res = await fetch('/shutdown', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: 'ui_button' })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        this.showProcessing('Shutdown started');
      } catch (e) {
        this.shuttingDown = false;
        btn.disabled = false;
        this.setStatus('live', 'Connected');
        this.toast('Shutdown failed: ' + e.message);
      }
    });
  },

  _initHomeNav() {
    const logo  = document.querySelector('.toolbar-logo');
    const brand = document.querySelector('.toolbar-brand');
    const goHome = () => {
      this.currentHtml = '';
      this.container.innerHTML = '';
      if (window.location.hash) window.location.hash = '';
      this._allowIncomingHtml = false;
      this._syncHomeVisibility();
      this._updateToolbarTabs('');
      if (window.WorkspacePanel) {
        WorkspacePanel.currentFileId = null;
      }
    };
    logo?.addEventListener('click', goHome);
    brand?.addEventListener('click', goHome);

    // Toolbar domain tabs — hash routing
    document.querySelectorAll('.domain-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const d = tab.dataset.domain;
        if (d) {
          this._navigateToRoute(d);
        }
      });
    });
  },

  _initSidePanelToggles() {
    // Toggle buttons inside panel headers
    document.querySelectorAll('.side-panel-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-target');
        document.getElementById(id)?.classList.add('collapsed');
      });
    });

    // Floating trigger tabs — hover to expand, mouseleave to collapse
    this._initFloatingTrigger('trigger-context', 'anchor-context-panel');
    this._initFloatingTrigger('trigger-timeline', 'anchor-timeline-panel');
    this._initFloatingTrigger('trigger-inbox', 'anchor-inbox-panel');

    // Resize handles
    this._initPanelResize('anchor-context-panel');
    this._initPanelResize('anchor-timeline-panel');
  },

  _initFloatingTrigger(triggerId, panelId) {
    const trigger = document.getElementById(triggerId);
    const panel = document.getElementById(panelId);
    if (!trigger || !panel) return;

    let hideTimer = null;

    const showPanel = () => {
      panel.classList.remove('collapsed');
      trigger.style.opacity = '0';
      trigger.style.pointerEvents = 'none';
    };
    const hidePanel = () => {
      panel.classList.add('collapsed');
      trigger.style.opacity = '';
      trigger.style.pointerEvents = '';
    };

    // Hover trigger tab → show; leave trigger or panel → hide
    trigger.addEventListener('mouseenter', () => {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
      showPanel();
    });
    trigger.addEventListener('mouseleave', () => {
      hideTimer = setTimeout(hidePanel, 400);
    });

    panel.addEventListener('mouseenter', () => {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    });
    panel.addEventListener('mouseleave', () => {
      hideTimer = setTimeout(hidePanel, 400);
    });
  },

  _initPanelResize(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;

    // Create resize handle
    const handle = document.createElement('div');
    handle.className = 'panel-resize-handle';
    panel.appendChild(handle);

    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragging = true;
      startX = e.clientX;
      startWidth = panel.offsetWidth;
      handle.classList.add('active');
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const delta = startX - e.clientX; // drag left = wider
      const newWidth = Math.min(600, Math.max(200, startWidth + delta));
      panel.style.width = newWidth + 'px';
      // Persist width
      try { localStorage.setItem('anchor.' + panelId + '.width', newWidth); } catch (_) {}
    });

    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('active');
      document.body.style.userSelect = '';
    });

    // Restore saved width
    try {
      const saved = localStorage.getItem('anchor.' + panelId + '.width');
      if (saved) panel.style.width = saved + 'px';
    } catch (_) {}
  },

  _loadOrCreateSessionId() {
    let id = localStorage.getItem('anchor.sessionId');
    if (!id) {
      id = 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
      localStorage.setItem('anchor.sessionId', id);
    }
    return id;
  },

  // WebSocket for bidirectional communication
  connect() {
    this.setStatus('', 'connecting...');
    this.connectWS();
  },

  connectWS() {
    if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = protocol + '//' + location.host;

    try {
      this.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.error('[anchor] WebSocket construction failed:', e);
      this.setStatus('', 'Retrying...');
      setTimeout(() => this.connectWS(), 2000);
      return;
    }

    this.ws.onopen = () => {
      this.setStatus('live', 'Connected');
      this._pingTimer = setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.error('[anchor] parse error:', e);
      }
    };

    this.ws.onclose = () => {
      if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }
      if (this.shuttingDown) {
        this.setStatus('', 'Shutdown complete');
        return;
      }
      this.setStatus('', 'Disconnected. Reconnecting...');
      setTimeout(() => this.connectWS(), 2000);
    };

    this.ws.onerror = () => {
      // onclose fires after onerror, which triggers reconnect
    };
  },

  handleMessage(msg) {
    switch (msg.type) {
      case 'html':
        if (!this._allowIncomingHtml && !window.location.hash) {
          return;
        }
        if (this._pendingPromptRoute) {
          this._bindGeneratedPageRoute(this._pendingPromptRoute);
        }
        this.clearProcessing();
        this._clearSessionBlockConfig();
        this.render(msg.content);
        this._pendingPromptRoute = '';
        break;
      case 'manifest_updated':
        if (window.ContextPanel) ContextPanel.refresh();
        break;
      case 'workspace_current':
        if (!window.location.hash) {
          return;
        }
        if (window.WorkspacePanel) WorkspacePanel.applyServerCurrent(msg.file);
        break;
      case 'patch':
        if (this._timing && !this._timing.t5_patch) this._timing.t5_patch = performance.now();
        this.applyPatches(msg.patches);
        break;
      case 'ack':
        if (this._timing && !this._timing.t3_ack) this._timing.t3_ack = performance.now();
        this.toast(msg.message || 'OK');
        break;
      case 'error':
        this.toast('Error: ' + msg.message);
        this.clearProcessing();
        break;
      case 'agent_event':
        if (window.TimelinePanel) TimelinePanel.append(msg.event);
        if (window.DebateOverlay && msg.event && (msg.event.kind || '').startsWith('agent.debate')) DebateOverlay.append(msg.event);
        this._handleAgentEvent(msg.event);
        break;
      case 'shutdown':
        this.shuttingDown = true;
        this.setStatus('', msg.message || 'Shutting down...');
        this.toast(msg.message || 'Anchor service shutting down');
        break;
      case 'pong':
        break;
      case 'inbox_updated':
        if (window.InboxPanel) {
          InboxPanel.applyServerCounts(msg.counts);
          InboxPanel._fetchItems();
        }
        break;
    }
  },

  _handleAgentEvent(evt) {
    if (window.OpBars) OpBars.handleEvent(evt);
    var kind = evt.kind || '';
    var payload = evt.payload || {};
    if (kind === 'agent.timing' && this._timing) {
      this._timing.server = payload;
      if (this._timing.t6_dom) this._showTimings();
      return;
    }
    if ((kind === 'agent.thinking' || kind === 'agent.tool_call') && this._timing && !this._timing.t4_thinking) {
      this._timing.t4_thinking = performance.now();
    }
    if (kind === 'agent.thinking' || kind === 'agent.decision' || kind === 'agent.tool_call') {
      this.showProcessing(payload.target_anchor || payload.summary || 'AI working...');
    } else if (kind === 'agent.complete' || kind === 'agent.error' || kind === 'agent.partial_render') {
      // Don't clear yet — wait for the final html message
      if (kind === 'agent.error') {
        this.showProcessing('Error: ' + (payload.message || 'unknown'), true);
      }
    }
  },

  // ── Processing state ─────────────────────────────────────────────

  showProcessing(label, isError) {
    if (!this.processingEl) return;
    this.processingEl.style.display = 'flex';
    this.processingLabel.textContent = label || 'AI 处理中';
    this.processingTarget.textContent = '';
    this.processingEl.className = 'toolbar-processing' + (isError ? ' is-error' : '');
    // Auto-hide after 30s if no response
    var self = this;
    if (this._processingTimer) clearTimeout(this._processingTimer);
    this._processingTimer = setTimeout(function () {
      self.hideProcessing();
    }, 30000);
  },

  hideProcessing() {
    if (!this.processingEl) return;
    this.processingEl.style.display = 'none';
    this.processingEl.className = 'toolbar-processing';
    if (this._processingTimer) { clearTimeout(this._processingTimer); this._processingTimer = null; }
  },

  markAnchorProcessing(targetRef) {
    if (!targetRef) return;
    this._processingAnchors.add(targetRef);
    var el = this.container.querySelector('[data-anc="' + targetRef + '"]');
    if (el) el.classList.add('anc-processing');
  },

  clearProcessing() {
    this.hideProcessing();
    var self = this;
    this._processingAnchors.forEach(function (ref) {
      var el = self.container.querySelector('[data-anc="' + ref + '"]');
      if (el) el.classList.remove('anc-processing');
    });
    this._processingAnchors.clear();
  },

  // Rendering
  render(html) {
    if (this.currentHtml && this.currentHtml !== html) {
      // Save previous version to history
      if (window.HistoryPanel) HistoryPanel.save(this.currentHtml, this.countAnchors());
    }
    this.currentHtml = html;
    if (window.OpBars) OpBars.clearAll();
    this.container.innerHTML = html;
    this.injectHandles();
    this.injectCollapse();
    this.infoEl.textContent = this.countAnchors() + ' anchors';
    if (window.WorkspacePanel) WorkspacePanel.persistCurrentHtml(html);
    if (window.PromptPanel) PromptPanel.clearSelection();
    this._syncHomeVisibility();
  },

  // Patch individual anchor nodes (outerHTML replacement) without full re-render
  applyPatches(patches) {
    const prevHtml = this.currentHtml;
    const _tp0 = performance.now();

    // Save collapse state before patching so it survives outerHTML replacement
    const collapseState = new Map();
    patches.forEach(p => {
      const el = this.container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (!el) return;
      // Save collapsed state for the heading itself and all hidden siblings
      if (el.classList.contains('anc-collapsed')) {
        collapseState.set(p.anchor_id, { collapsed: true, hiddenSiblings: [] });
      }
      // Also save hidden sibling state (siblings hidden by collapse toggles)
      let sibling = el.nextElementSibling;
      const level = el.tagName.match(/^H([1-6])$/) ? parseInt(el.tagName[1]) : 0;
      const hiddenMap = collapseState.get(p.anchor_id);
      while (sibling) {
        if (/^H[1-6]$/.test(sibling.tagName) && parseInt(sibling.tagName[1]) <= level) break;
        if (sibling.style.display === 'none') {
          if (hiddenMap) hiddenMap.hiddenSiblings.push(sibling.dataset._ancCollapsePrev || '');
          else collapseState.set(p.anchor_id + ':' + sibling.getAttribute('data-anc'), { parentRef: p.anchor_id, prevDisplay: sibling.dataset._ancCollapsePrev || '' });
        }
        sibling = sibling.nextElementSibling;
      }
    });

    patches.forEach(p => {
      const el = this.container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (!el) return;
      el.outerHTML = p.html_fragment;
    });
    const _tp1 = performance.now();
    // Re-inject handles + collapse into each patched node's replacement
    patches.forEach(p => {
      const newEl = this.container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (newEl) {
        this.injectHandlesIn(newEl);
        this.injectCollapseIn(newEl);
        this._mountAnnotations(p.anchor_id);
      }
    });

    // Restore collapse state after re-injection
    collapseState.forEach((state, anchorId) => {
      const el = this.container.querySelector('[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]');
      if (!el) return;
      if (state.collapsed) {
        el.classList.add('anc-collapsed');
        const caret = el.querySelector('.anc-collapse-caret');
        if (caret) caret.style.transform = 'rotate(-90deg)';
        const level = parseInt(el.tagName[1]);
        let sibling = el.nextElementSibling;
        let idx = 0;
        while (sibling) {
          if (/^H[1-6]$/.test(sibling.tagName) && parseInt(sibling.tagName[1]) <= level) break;
          sibling.style.display = 'none';
          sibling.dataset._ancCollapsePrev = state.hiddenSiblings[idx] || '';
          sibling = sibling.nextElementSibling;
          idx++;
        }
      }
    });
    const _tp2 = performance.now();
    this.currentHtml = this.container.innerHTML;
    const _tp3 = performance.now();
    this.infoEl.textContent = this.countAnchors() + ' anchors';
    if (prevHtml && prevHtml !== this.currentHtml && window.HistoryPanel) {
      HistoryPanel.save(prevHtml, this.countAnchors());
    }
    if (window.WorkspacePanel) WorkspacePanel.persistCurrentHtml(this.currentHtml);
    if (window.PromptPanel) PromptPanel.clearSelection();
    this.clearProcessing();
    // Sync currentHtml back to leader so it stays in sync with DOM truth
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'html_synced',
        html: this.currentHtml,
        sig: 'sig:' + Date.now()
      }));
    }
    if (this._timing) {
      this._timing.t6_dom = performance.now();
      this._timing._patch_detail = {
        outerhtml_ms: Math.round(_tp1 - _tp0),
        inject_handles_ms: Math.round(_tp2 - _tp1),
        serialize_html_ms: Math.round(_tp3 - _tp2),
      };
      this._showTimings();
    }
  },

  injectHandles(rootEl) {
    this.injectHandlesIn(rootEl || this.container);
  },

  injectHandlesIn(root) {
    const elements = root.querySelectorAll ? root.querySelectorAll('[data-anc]') : [root];
    elements.forEach(el => {
      this.wrapElement(el);
      this.addHandleTrigger(el);
    });
  },

  wrapElement(el) {
    if (el.classList.contains('anc-element')) return;
    if (el === this.container) return;
    el.classList.add('anc-element');
    const style = getComputedStyle(el);
    if (style.position === 'static') {
      el.style.position = 'relative';
    }
  },

  addHandleTrigger(el) {
    const anchorId = el.getAttribute('data-anc');
    // Merge model-specified handles with fixed platform defaults.
    // The platform guarantees a minimum set of operations; data-handles only extends.
    const modelHandles = (el.getAttribute('data-handles') || '').split(',').map(h => h.trim()).filter(Boolean);
    const merged = new Set([...this.defaultHandles, ...modelHandles]);
    const handlesStr = Array.from(merged).join(',');
    const existing = Array.from(el.children).find(c => c.classList.contains('anc-handle'));
    if (existing) existing.remove();
    const trigger = document.createElement('span');
    trigger.className = 'anc-handle';
    trigger.textContent = '+';
    trigger.title = 'Actions for ' + anchorId;
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      this.togglePopup(el, trigger, anchorId, handlesStr);
    });
    el.appendChild(trigger);
  },

  injectCollapse(rootEl) {
    this.injectCollapseIn(rootEl || this.container);
  },

  injectCollapseIn(root) {
    const headings = (root.querySelectorAll ? root.querySelectorAll('h1, h2, h3, h4') : root.matches && root.matches('h1, h2, h3, h4') ? [root] : []);
    headings.forEach(h => {
      if (h.dataset.ancCollapseInit === '1') return;
      h.dataset.ancCollapseInit = '1';
      h.style.cursor = 'pointer';
      h.style.userSelect = 'none';
      const caret = document.createElement('span');
      caret.className = 'anc-collapse-caret';
      caret.textContent = '\u25BE';
      caret.setAttribute('aria-hidden', 'true');
      caret.style.display = 'inline-block';
      caret.style.marginRight = '8px';
      caret.style.fontSize = '0.7em';
      caret.style.opacity = '0.45';
      caret.style.transition = 'transform 0.15s ease';
      h.insertBefore(caret, h.firstChild);
      h.addEventListener('click', (e) => {
        if (e.target.closest('a, button, input, textarea, .anc-handle, .anc-handle-trigger, .anc-handle-popup')) return;
        this.toggleHeading(h);
      });
    });
  },

  toggleHeading(h) {
    const level = parseInt(h.tagName.substring(1), 10);
    const collapsed = h.classList.toggle('anc-collapsed');
    const caret = h.querySelector('.anc-collapse-caret');
    if (caret) caret.style.transform = collapsed ? 'rotate(-90deg)' : '';
    let sibling = h.nextElementSibling;
    while (sibling) {
      if (/^H[1-6]$/.test(sibling.tagName)) {
        const sibLevel = parseInt(sibling.tagName.substring(1), 10);
        if (sibLevel <= level) break;
      }
      if (collapsed) {
        sibling.dataset._ancCollapsePrev = sibling.style.display || '';
        sibling.style.display = 'none';
      } else {
        sibling.style.display = sibling.dataset._ancCollapsePrev || '';
        delete sibling.dataset._ancCollapsePrev;
      }
      sibling = sibling.nextElementSibling;
    }
  },

  // Per-block subagent config: { "${sessionId}:${anchorId}": { subagent_id, context_mode, _ts } }
  _blockConfig: {},
  // Global default processor: { subagent_id, context_mode } or null = main thread
  _defaultProcessor: null,

  _loadBlockConfig() {
    try {
      const raw = localStorage.getItem('anchor.blockConfig');
      if (!raw) return {};
      const all = JSON.parse(raw);
      const maxAge = 7 * 24 * 60 * 60 * 1000;
      const now = Date.now();
      const pruned = {};
      Object.entries(all).forEach(([k, v]) => {
        if (!v._ts || (now - v._ts) < maxAge) pruned[k] = v;
      });
      return pruned;
    } catch { return {}; }
  },

  _saveBlockConfig() {
    try { localStorage.setItem('anchor.blockConfig', JSON.stringify(this._blockConfig)); } catch {}
  },

  _clearSessionBlockConfig() {
    const prefix = this.sessionId + ':';
    Object.keys(this._blockConfig).forEach(k => {
      if (k.startsWith(prefix)) delete this._blockConfig[k];
    });
    this._saveBlockConfig();
  },

  _setBlockConfig(anchorId, cfg) {
    const key = this.sessionId + ':' + anchorId;
    if (cfg) {
      this._blockConfig[key] = { ...cfg, _ts: Date.now() };
    } else {
      delete this._blockConfig[key];
    }
    this._saveBlockConfig();
  },

  _getBlockConfig(anchorId) {
    return this._blockConfig[this.sessionId + ':' + anchorId] || null;
  },

  _loadDefaultProcessorFromStorage() {
    try {
      const raw = localStorage.getItem('anchor.defaultProcessor');
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  },

  _formatProcessorChipText(anchorId) {
    const blockCfg = this._getBlockConfig(anchorId);
    const defaultCfg = this._defaultProcessor;
    if (blockCfg && blockCfg.subagent_id) {
      return '⚙ ' + blockCfg.subagent_id + ' / ' + (blockCfg.context_mode || 'none') + ' ▾';
    }
    if (defaultCfg && defaultCfg.subagent_id) {
      return '⚙ (默认) ' + defaultCfg.subagent_id + ' ▾';
    }
    return '⚙ 主线程 ▾';
  },

  _renderProcessorOverride(popup, chip, anchorId) {
    const view = document.createElement('div');
    view.className = 'mini-context-view mini-processor-view';

    const blockCfg = this._getBlockConfig(anchorId);
    const defaultCfg = this._defaultProcessor;
    const currentId = (blockCfg && blockCfg.subagent_id) ? blockCfg.subagent_id : null;
    const currentMode = (blockCfg && blockCfg.context_mode) || (defaultCfg && defaultCfg.context_mode) || 'none';

    const hdr = document.createElement('div');
    hdr.style.cssText = 'font-size:11px;font-weight:600;color:var(--fg-2,#555);margin-bottom:4px;';
    hdr.textContent = '块级 Subagent 覆盖';
    view.appendChild(hdr);

    const subagents = (window.ContextPanel && ContextPanel.manifest && ContextPanel.manifest.subagents) ? ContextPanel.manifest.subagents : [];
    const allOptions = [{ id: null, name: '主线程（默认）', can_patch: true }, ...subagents];

    let selectedId = currentId;
    let selectedMode = currentMode;

    allOptions.forEach(ag => {
      const row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;padding:2px 0;cursor:pointer;' + (ag.can_patch === false ? 'opacity:0.55;' : '');
      const rb = document.createElement('input');
      rb.type = 'radio';
      rb.name = 'proc-agent-' + anchorId;
      rb.value = ag.id || '';
      rb.checked = (ag.id === currentId);
      const nm = document.createElement('span');
      nm.textContent = ag.name || ag.id;
      if (ag.can_patch === false) {
        nm.insertAdjacentHTML('beforeend', ' <span title="此 agent 可能无法调用 anchor_patch" style="color:var(--amber,#f59e0b)">⚠</span>');
      }
      row.appendChild(rb);
      row.appendChild(nm);
      rb.addEventListener('change', () => {
        selectedId = ag.id || null;
        modeSection.style.display = selectedId ? '' : 'none';
        // Auto-persist per-block config on change
        if (selectedId) {
          this._setBlockConfig(anchorId, { subagent_id: selectedId, context_mode: selectedMode });
          chip.textContent = this._formatProcessorChipText(anchorId);
        } else {
          this._setBlockConfig(anchorId, null);
          chip.textContent = this._formatProcessorChipText(anchorId);
        }
      });
      view.appendChild(row);
    });

    const modeSection = document.createElement('div');
    modeSection.style.display = selectedId ? '' : 'none';
    const modeHdr = document.createElement('div');
    modeHdr.style.cssText = 'font-size:11px;font-weight:600;color:var(--fg-2,#555);margin:6px 0 2px;';
    modeHdr.textContent = '上下文模式';
    modeSection.appendChild(modeHdr);
    [['none', '无上下文（最快）'], ['summarized', '摘要式压缩'], ['full', '完整上下文']].forEach(([id, label]) => {
      const row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;padding:1px 0;cursor:pointer;';
      const rb = document.createElement('input');
      rb.type = 'radio';
      rb.name = 'proc-mode-' + anchorId;
      rb.value = id;
      rb.checked = (id === selectedMode);
      rb.addEventListener('change', () => {
        selectedMode = id;
        // Auto-persist context_mode change on the already-selected subagent
        if (selectedId) {
          this._setBlockConfig(anchorId, { subagent_id: selectedId, context_mode: id });
          chip.textContent = this._formatProcessorChipText(anchorId);
        }
      });
      const nm = document.createElement('span'); nm.textContent = label;
      row.appendChild(rb); row.appendChild(nm);
      modeSection.appendChild(row);
    });
    view.appendChild(modeSection);

    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:4px;margin-top:6px;';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn btn--sm btn--brand';
    saveBtn.textContent = '保存';
    saveBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const cfg = selectedId ? { subagent_id: selectedId, context_mode: selectedMode } : null;
      this._setBlockConfig(anchorId, cfg);
      chip.textContent = this._formatProcessorChipText(anchorId);
      chip.classList.remove('expanded');
      view.remove();
    });
    const resetBtn = document.createElement('button');
    resetBtn.className = 'btn btn--sm btn--ghost';
    resetBtn.textContent = '重置为默认';
    resetBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this._setBlockConfig(anchorId, null);
      chip.textContent = this._formatProcessorChipText(anchorId);
      chip.classList.remove('expanded');
      view.remove();
    });
    btnRow.appendChild(saveBtn);
    btnRow.appendChild(resetBtn);
    view.appendChild(btnRow);

    const existing = popup.querySelector('.mini-processor-view');
    if (existing) existing.remove();
    chip.after(view);
  },

  // Popup
  _tempOverride: null,  // per-op context override

  togglePopup(el, trigger, anchorId, handlesStr) {
    this.closePopup();
    this._tempOverride = null;
    const handles = handlesStr.split(',').map(h => h.trim()).filter(Boolean);
    if (handles.length === 0) return;
    const popup = document.createElement('div');
    popup.className = 'anc-handle-popup open';
    // Position fixed relative to viewport — always on top
    const triggerRect = trigger.getBoundingClientRect();
    popup.style.position = 'fixed';
    popup.style.top = (triggerRect.bottom + 4) + 'px';
    popup.style.right = (window.innerWidth - triggerRect.right) + 'px';
    popup.style.zIndex = '99999';
    const header = document.createElement('div');
    header.className = 'popup-header';
    header.textContent = anchorId;
    popup.appendChild(header);

    // B.1.7 — Context override chip
    const chip = document.createElement('span');
    chip.className = 'context-chip';
    chip.textContent = this._formatContextChipText();
    chip.title = 'Click to override context for this op';
    let overrideOpen = false;
    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      overrideOpen = !overrideOpen;
      chip.classList.toggle('expanded', overrideOpen);
      if (overrideOpen) {
        const mpv = popup.querySelector('.mini-processor-view');
        if (mpv) { mpv.remove(); procOverrideOpen = false; procChip.classList.remove('expanded'); }
        this._renderMiniContext(popup, chip);
      } else { const mc = popup.querySelector('.mini-context-view:not(.mini-processor-view)'); if (mc) mc.remove(); }
    });
    popup.appendChild(chip);

    // Per-block processor chip
    const procChip = document.createElement('span');
    procChip.className = 'context-chip';
    procChip.style.marginLeft = '4px';
    procChip.textContent = this._formatProcessorChipText(anchorId);
    procChip.title = '配置此块的 Subagent';
    let procOverrideOpen = false;
    procChip.addEventListener('click', (e) => {
      e.stopPropagation();
      procOverrideOpen = !procOverrideOpen;
      procChip.classList.toggle('expanded', procOverrideOpen);
      if (procOverrideOpen) {
        const mcv = popup.querySelector('.mini-context-view:not(.mini-processor-view)');
        if (mcv) { mcv.remove(); overrideOpen = false; chip.classList.remove('expanded'); }
        this._renderProcessorOverride(popup, procChip, anchorId);
      } else { const mc = popup.querySelector('.mini-processor-view'); if (mc) mc.remove(); }
    });
    popup.appendChild(procChip);

    handles.forEach(opName => {
      const def = this.opDefs[opName];
      if (!def) return;
      // All operations show an input step — required or optional
      const btn = document.createElement('button');
      btn.className = 'anc-op-btn';
      const iconHtml = def.icon ? `<i class="ph-bold ${def.icon} anc-op-icon"></i>` : '';
      btn.innerHTML = `${iconHtml}<span class="anc-op-label">${def.label}</span>`;
      if (def.needsInput) {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.showOpInput(popup, opName, anchorId, def);
        });
      } else {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.sendOp(opName, anchorId);
          this.closePopup();
        });
      }
      popup.appendChild(btn);
    });
    document.body.appendChild(popup);
    this._positionPopup(popup, trigger);
    trigger.classList.add('open');
    this.openPopup = { popup, trigger };
    setTimeout(() => {
      document.addEventListener('click', this._outsideClickHandler = (e) => {
        if (!popup.contains(e.target) && e.target !== trigger) {
          this.closePopup();
        }
      });
    }, 0);
  },

  showOpInput(popup, opName, anchorId, def) {
    const existing = popup.querySelector('.op-input-row');
    if (existing) existing.remove();
    var optional = def.needsInput === 'optional';
    var row = document.createElement('div');
    row.className = 'op-input-row';
    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = def.inputLabel || 'Enter instruction...';
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        var instruction = input.value.trim();
        if (instruction || optional) {
          this.sendOp(opName, anchorId, instruction ? { instruction: instruction } : undefined);
          this.closePopup();
        }
      }
      e.stopPropagation();
    }.bind(this));
    var executeBtn = document.createElement('button');
    executeBtn.textContent = '执行';
    executeBtn.className = 'btn-execute-now';
    executeBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var instruction = input.value.trim();
      if (instruction || optional) {
        this.sendOp(opName, anchorId, instruction ? { instruction: instruction } : undefined);
        this.closePopup();
      }
    }.bind(this));
    var queueBtn = document.createElement('button');
    queueBtn.textContent = '暂存';
    queueBtn.className = 'btn-queue';
    queueBtn.title = '加入批量执行队列';
    queueBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var instruction = input.value.trim();
      this.queueOp(opName, anchorId, instruction);
      this.closePopup();
    }.bind(this));
    row.appendChild(input);
    row.appendChild(executeBtn);
    row.appendChild(queueBtn);
    popup.appendChild(row);
    if (this.openPopup) this._positionPopup(popup, this.openPopup.trigger);
    setTimeout(function () { input.focus(); }, 50);
  },

  _formatContextChipText() {
    const b = this._tempOverride || (window.ContextPanel ? ContextPanel.getBundle() : {});
    const mc = (b.memory_ids || (b.memory || [])).length;
    const sc = (b.skill_ids || (b.skills || [])).length;
    const ac = (b.subagent_ids || (b.subagents || [])).length;
    const rc = (b.resource_ids || (b.resources || [])).length;
    const total = mc + sc + ac + rc;
    return 'Context: ' + (total || 'default') + ' (' + mc + 'm ' + sc + 's ' + ac + 'a ' + rc + 'r) ▾';
  },

  _renderMiniContext(popup, chip) {
    const view = document.createElement('div');
    view.className = 'mini-context-view';
    const groups = [
      { key: 'memory', label: 'Memory', ids: (this._tempOverride?.memory_ids) || (window.ContextPanel?.selected?.memory ? Array.from(ContextPanel.selected.memory) : []) },
      { key: 'skills', label: 'Skills', ids: (this._tempOverride?.skill_ids) || (window.ContextPanel?.selected?.skills ? Array.from(ContextPanel.selected.skills) : []) },
      { key: 'subagents', label: 'Subagents', ids: (this._tempOverride?.subagent_ids) || (window.ContextPanel?.selected?.subagents ? Array.from(ContextPanel.selected.subagents) : []) },
      { key: 'resources', label: 'Resources', ids: (this._tempOverride?.resource_ids) || (window.ContextPanel?.selected?.resources ? Array.from(ContextPanel.selected.resources) : []) }
    ];
    groups.forEach(g => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:12px;padding:2px 0;';
      const label = document.createElement('span');
      label.textContent = g.label + ': ';
      label.style.cssText = 'font-weight:500;';
      const count = document.createElement('span');
      count.textContent = g.ids.length + ' selected';
      count.style.cssText = 'color:var(--muted,#888);';
      row.appendChild(label); row.appendChild(count);
      // Quick toggles: all / none links
      if (g.ids.length > 0) {
        const clearAll = document.createElement('a');
        clearAll.textContent = 'clear';
        clearAll.style.cssText = 'color:var(--brand);cursor:pointer;margin-left:auto;font-size:11px;';
        clearAll.addEventListener('click', (e) => { e.stopPropagation(); this._setTempOverrideGroup(g.key, []); this._renderMiniContext(popup, chip); });
        row.appendChild(clearAll);
      }
      view.appendChild(row);
    });
    const existing = popup.querySelector('.mini-context-view');
    if (existing) existing.remove();
    chip.after(view);
  },

  _setTempOverrideGroup(group, ids) {
    if (!this._tempOverride) {
      // Clone current bundle as starting point
      const b = window.ContextPanel ? ContextPanel.getBundle() : {};
      this._tempOverride = {
        memory_ids: [...(b.memory_ids || [])],
        skill_ids: [...(b.skill_ids || [])],
        subagent_ids: [...(b.subagent_ids || [])],
        resource_ids: [...(b.resource_ids || [])],
        transient_override: true
      };
    }
    const key = group === 'memory' ? 'memory_ids' : group === 'skills' ? 'skill_ids' : group === 'subagents' ? 'subagent_ids' : 'resource_ids';
    this._tempOverride[key] = ids;
  },

  closePopup() {
    if (this.openPopup) {
      this.openPopup.popup.remove();
      this.openPopup.trigger.classList.remove('open');
      this.openPopup = null;
    }
    if (this._outsideClickHandler) {
      document.removeEventListener('click', this._outsideClickHandler);
      this._outsideClickHandler = null;
    }
  },

  // ── Phase 2: Envelope construction & dispatch ─────────────────────

  _positionPopup(popup, trigger) {
    const margin = 10;
    const rect = trigger.getBoundingClientRect();
    popup.style.maxHeight = Math.max(180, window.innerHeight - margin * 2) + 'px';
    popup.style.overflowY = 'auto';
    popup.style.right = 'auto';
    const width = popup.offsetWidth || 260;
    const height = popup.offsetHeight || 280;
    let top = rect.bottom + 6;
    if (top + height > window.innerHeight - margin) top = rect.top - height - 6;
    top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));
    let left = rect.right - width;
    left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
    popup.style.top = top + 'px';
    popup.style.left = left + 'px';
  },

  buildEnvelope({ op, target_kind, target_ref, instruction, selection, overrideBundle }) {
    const eventId = 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
    const rawBundle = overrideBundle || (window.ContextPanel ? ContextPanel.getBundle() : null);
    const renderState = this._snapshotRenderState();
    if (target_ref && target_kind === 'anchor') {
      renderState.relevant_subtree = this._collectRelevantSubtree(target_ref);
    }
    // Resolve per-block → global default → null (main thread)
    const blockCfg = target_ref ? this._getBlockConfig(target_ref) : null;
    const effectiveCfg = blockCfg || this._defaultProcessor || null;
    const bundle = Object.assign({
      memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
      scope_hint: 'standard', transient_override: !!overrideBundle
    }, rawBundle || {});
    if (effectiveCfg && effectiveCfg.subagent_id) {
      bundle.subagent_id = effectiveCfg.subagent_id;
      bundle.context_mode = effectiveCfg.context_mode || 'none';
    }
    bundle.file_id = (window.WorkspacePanel && WorkspacePanel.currentFileId) || this.currentFileId || null;

    // Trading domain extension — detect target anchor's domain
    var domain = null;
    var targetEl = target_ref ? document.querySelector('[data-anc="' + target_ref.replace(/"/g, '\\"') + '"]') : null;
    if (targetEl && targetEl.getAttribute('data-domain') === 'trading.private') {
      domain = {
        namespace: 'trading.private',
        action: this._inferTradingAction(op, targetEl),
        trading_session_id: targetEl.closest('[data-trading-session-id]')?.getAttribute('data-trading-session-id') || null,
        claim_id: targetEl.getAttribute('data-claim-id') || null,
        finding_id: targetEl.getAttribute('data-finding-id') || null
      };
    }

    return {
      schema_version: '1.0',
      intent: { op, target_kind, target_ref, instruction },
      selection: selection || null,
      context_bundle: bundle,
      render_state: renderState,
      domain: domain,
      provenance: {
        session_id: this.sessionId,
        event_id: eventId,
        parent_event_id: null,
        timestamp: new Date().toISOString(),
        client_version: '0.1.0'
      }
    };
  },

  _inferTradingAction(op, el) {
    var anc = el.getAttribute('data-anc') || '';
    // Map Anchor op + target anchor to trading domain action
    if (op === 'edit') {
      if (anc === 'trade.intent' || anc.startsWith('trade.intent.')) return 'DECLARE_REASONING';
      if (anc === 'reasoning.raw') return 'DECLARE_REASONING';
      if (anc.startsWith('position.outcome')) return 'EXECUTE_TRADE';
      if (anc === 'postmortem') return 'POSTMORTEM';
      return 'EDIT';
    }
    if (op === 'annotate') {
      if (anc.startsWith('claim.')) return 'UPDATE_CLAIM';
      if (anc.startsWith('thread.')) return 'ADD_FINDING';
      if (anc.startsWith('finding.')) return 'REACT_TO_FINDING';
      if (anc.startsWith('reaction.')) return 'REACT_TO_FINDING';
      if (anc === 'reactions') return 'REACT_TO_FINDING';
      return 'ANNOTATE';
    }
    if (op === 'refine') {
      if (anc.startsWith('claim.')) return 'UPDATE_CLAIM';
      return 'REFINE';
    }
    if (op === 'expand') {
      if (anc === 'claims') return 'EXTRACT_CLAIMS';
      if (anc === 'tracking') return 'SPAWN_TRACKER';
      return 'EXPAND';
    }
    if (op === 'branch') {
      if (anc.startsWith('thread.')) return 'SPAWN_TRACKER';
      return 'BRANCH';
    }
    if (op === 'ask') return 'QUERY';
    if (op === 'restructure') return 'RESTRUCTURE';
    return 'CUSTOM';
  },

  _snapshotRenderState() {
    const anchors = Array.from(this.container.querySelectorAll('[data-anc]'));
    const anchor_tree = anchors.map(el => el.getAttribute('data-anc'));
    // Lightweight index: each anchor's handles + deps (no HTML)
    const anchor_index = {};
    anchors.forEach(el => {
      const id = el.getAttribute('data-anc');
      const handles = (el.getAttribute('data-handles') || '').split(',').map(s => s.trim()).filter(Boolean);
      const deps = (el.getAttribute('data-deps') || '').split(',').map(s => s.trim()).filter(Boolean);
      anchor_index[id] = { handles, deps };
    });
    return {
      anchor_tree,
      anchor_index,
      dom_signature: 'sig:' + anchor_tree.length,
      viewport: {
        scroll_top: window.scrollY | 0,
        visible_anchors: []
      }
    };
  },

  _syncHomeVisibility() {
    const home = document.getElementById('anchor-home');
    const shell = document.getElementById('anchor-shell');
    if (!home || !shell) return;
    const hasHtml = !!(this.currentHtml && this.currentHtml.trim());
    home.classList.toggle('is-hidden', hasHtml);
    shell.classList.toggle('has-content', hasHtml);

    // Show/hide prompt panel trigger based on content
    const trigger = document.getElementById('trigger-prompt');
    if (trigger) {
      trigger.style.display = hasHtml ? '' : 'none';
      if (!hasHtml && window.PromptPanel) window.PromptPanel.hide();
    }
  },

  // Multi-select card anchors — click to toggle context reference
  _initAnchorSelect() {
    this.container.addEventListener('click', (e) => {
      if (e.target.closest('.anc-handle, .anc-handle-popup, .anc-op-btn, ' +
        'a, button, input, textarea, select, .anc-collapse-caret, ' +
        '.prompt-chip, .chip-remove')) return;

      const anchorEl = e.target.closest('[data-anc]');
      if (!anchorEl) return;

      // Only select card-level anchors, not nested field-level ones
      const isCard = anchorEl.classList.contains('blog-card') ||
                     anchorEl.classList.contains('anc-section--gc');
      if (!isCard) return;

      if (!window.PromptPanel) return;

      const anchorId = anchorEl.getAttribute('data-anc');
      const titleEl = anchorEl.querySelector('.blog-card-title, h1, h2, h3, [data-anc$=".title"]');
      const label = titleEl ? titleEl.textContent.trim().substring(0, 60) : anchorId;

      window.PromptPanel.toggleAnchor(anchorId, label, anchorEl.outerHTML);
    });
  },

  // Collect the target node's HTML + forward/reverse dependency subtrees.
  // Returns null fields when the target can't be found.
  _collectRelevantSubtree(target_ref) {
    if (!target_ref) return null;
    const el = this.container.querySelector('[data-anc="' + target_ref.replace(/"/g, '\\"') + '"]');
    if (!el) return null;

    const target_html = el.outerHTML;

    // Forward deps: nodes listed in target's data-deps
    const depsStr = el.getAttribute('data-deps') || '';
    const forward_ids = depsStr.split(',').map(s => s.trim()).filter(Boolean);
    const forward_deps = {};
    forward_ids.forEach(id => {
      const depEl = this.container.querySelector('[data-anc="' + id.replace(/"/g, '\\"') + '"]');
      if (depEl) forward_deps[id] = depEl.outerHTML;
    });

    // Reverse deps: nodes whose data-deps include target_ref
    const reverse_deps = {};
    this.container.querySelectorAll('[data-deps]').forEach(other => {
      const odeps = (other.getAttribute('data-deps') || '').split(',').map(s => s.trim()).filter(Boolean);
      if (odeps.includes(target_ref)) {
        const oid = other.getAttribute('data-anc');
        if (oid && oid !== target_ref) reverse_deps[oid] = other.outerHTML;
      }
    });

    return {
      target_ref,
      target_html,
      forward_deps: Object.keys(forward_deps).length > 0 ? forward_deps : undefined,
      reverse_deps: Object.keys(reverse_deps).length > 0 ? reverse_deps : undefined
    };
  },

  sendEnvelope(envelope) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      var targetRef = envelope.intent && envelope.intent.target_ref;
      if (targetRef) {
        this.markAnchorProcessing(targetRef);
        this.showProcessing(targetRef);
        // Instant OpBar — user sees feedback before CC cold-start finishes
        if (window.OpBars) OpBars.preCreate(targetRef);
      }
      if (this._timing) this._timing.t2_sent = performance.now();
      this.ws.send(JSON.stringify({ type: 'envelope', envelope }));
      this.toast('Sent: ' + envelope.intent.op + ' → ' + targetRef);
    } else {
      this.toast('Connection lost — reconnecting...');
    }
  },

  _handleAnnotateOp(anchorId, text) {
    fetch('/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anchor_id: anchorId, text }),
    })
    .then(r => r.json())
    .then(() => this._mountAnnotations(anchorId))
    .catch(() => {});
  },

  _mountAnnotations(anchorId) {
    fetch('/annotations?anchor_id=' + encodeURIComponent(anchorId))
      .then(r => r.json())
      .then(data => {
        const sel = '[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]';
        const el = this.container.querySelector(sel);
        if (!el) return;
        const existing = el.querySelector('.anc-annotations');
        if (existing) existing.remove();
        const annotations = data.items || [];
        if (annotations.length === 0) return;
        const wrap = document.createElement('div');
        wrap.className = 'anc-annotations';
        annotations.forEach(ann => {
          const pill = document.createElement('span');
          pill.className = 'anc-annotation-pill';
          pill.innerHTML = _escHtml(ann.text) +
            '<span class="remove-anno" data-ann-id="' + _escHtml(ann.id) + '" title="删除注解">×</span>';
          pill.querySelector('.remove-anno').addEventListener('click', (e) => {
            e.stopPropagation();
            fetch('/annotations/' + ann.id, { method: 'DELETE' })
              .then(() => this._mountAnnotations(anchorId));
          });
          wrap.appendChild(pill);
        });
        el.appendChild(wrap);
      })
      .catch(() => {});
  },

  // ── Queue management ─────────────────────────────────────────────

  queueOp(opName, anchorId, instruction) {
    this.pendingOps.push({
      op: opName,
      target: anchorId,
      instruction: instruction || '',
      timestamp: Date.now()
    });
    this.updateQueueBadge();
    this.toast('Queued: ' + opName + ' → ' + anchorId + ' (' + this.pendingOps.length + ' total)');
  },

  executeAll() {
    if (this.pendingOps.length === 0) return;
    const count = this.pendingOps.length;

    // Build combined instruction from all queued ops
    const parts = this.pendingOps.map((q, i) =>
      (i + 1) + '. **' + q.op + '** on `' + q.target + '`' +
      (q.instruction ? ': ' + q.instruction : '')
    );
    const combinedInstruction = 'Batch of ' + count + ' operations:\n\n' + parts.join('\n');

    // Send as single envelope targeting the first op's target as primary
    const first = this.pendingOps[0];
    const envelope = this.buildEnvelope({
      op: first.op,
      target_kind: 'anchor',
      target_ref: first.target,
      instruction: combinedInstruction,
      selection: null,
      overrideBundle: this._tempOverride || null
    });
    // Attach all ops for server-side awareness, each with its own routing config
    envelope._batch_ops = this.pendingOps.map(q => {
      const bCfg = this._getBlockConfig(q.target);
      const eCfg = bCfg || this._defaultProcessor || null;
      const entry = { op: q.op, target_ref: q.target, instruction: q.instruction };
      if (eCfg && eCfg.subagent_id) {
        entry.subagent_id = eCfg.subagent_id;
        entry.context_mode = eCfg.context_mode || 'none';
      }
      return entry;
    });

    this.sendEnvelope(envelope);
    this.pendingOps = [];
    this.updateQueueBadge();
    this._tempOverride = null;
    this.toast('Executing ' + count + ' ops...');
  },

  updateQueueBadge() {
    const btn = document.getElementById('anchor-execute-all');
    const badge = btn?.querySelector('.execute-badge');
    if (!btn || !badge) return;
    const n = this.pendingOps.length;
    badge.textContent = n;
    if (n > 0) {
      btn.classList.remove('hidden');
      btn.querySelector('.execute-label').textContent = 'Execute All (' + n + ')';
    } else {
      btn.classList.add('hidden');
      btn.querySelector('.execute-label').textContent = 'Execute All';
    }
  },

  // Op dispatch via WebSocket — now builds envelope when context is active
  sendOp(opName, anchorId, args) {
    const _t_click = performance.now();
    const sel = window.getSelection();
    let selection = null;
    const el = this.container.querySelector('[data-anc="' + anchorId + '"]');
    if (sel && sel.toString().trim() && el && el.contains(sel.anchorNode)) {
      selection = { text: sel.toString(), start_offset: sel.anchorOffset, end_offset: sel.focusOffset };
    }
    if (opName === 'lock' && el) {
      el.setAttribute('data-anc-locked', '');
      this.toast('Locked: ' + anchorId);
    }
    // Build envelope (includes context bundle)
    const envelope = this.buildEnvelope({
      op: opName,
      target_kind: 'anchor',
      target_ref: anchorId,
      instruction: args?.instruction || '',
      selection,
      overrideBundle: this._tempOverride || null
    });
    const _t_built = performance.now();
    this._timing = {
      id: envelope.provenance && envelope.provenance.event_id,
      op: opName,
      target: anchorId,
      t0_click: _t_click,
      t1_built: _t_built,
    };
    this.sendEnvelope(envelope);
    this._tempOverride = null;  // reset per-op override
  },

  // ── Timing waterfall ─────────────────────────────────────────────

  _showTimings() {
    const t = this._timing;
    if (!t || !t.t6_dom || !t.t0_click) return;

    const fmt = (ms) => {
      if (ms == null || isNaN(ms) || ms < 0) return '—';
      return ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms) + 'ms';
    };
    const pct = (ms, tot) => {
      if (!ms || ms <= 0 || !tot) return 0;
      return Math.max(2, Math.min(100, Math.round(ms / tot * 100)));
    };
    const total = t.t6_dom - t.t0_click;

    const stages = [
      { name: 'Build Envelope',      ms: t.t1_built ? t.t1_built - t.t0_click : null,                                        color: '#5B8FF9' },
      { name: 'WS → Server ACK',     ms: t.t3_ack && t.t2_sent ? t.t3_ack - t.t2_sent : null,                                color: '#5B8FF9' },
      { name: 'ACK → Thinking',      ms: t.t4_thinking && t.t3_ack ? t.t4_thinking - t.t3_ack : null,                        color: '#5B8FF9' },
      { name: '★ Claude Generation', ms: t.t5_patch && (t.t4_thinking || t.t3_ack) ? t.t5_patch - (t.t4_thinking || t.t3_ack) : null, color: '#FFD700' },
      { name: 'Patch → DOM Done',    ms: t.t6_dom && t.t5_patch ? t.t6_dom - t.t5_patch : null,                              color: '#5B8FF9' },
    ].filter(s => s.ms != null && s.ms >= 0);

    // DOM detail breakdown (sub-stages of "Patch → DOM Done")
    const pd = t._patch_detail || {};
    const domDetail = [
      { name: '  └ outerHTML replace', ms: pd.outerhtml_ms },
      { name: '  └ inject handles',    ms: pd.inject_handles_ms },
      { name: '  └ serialize HTML',    ms: pd.serialize_html_ms },
    ].filter(s => s.ms != null && s.ms > 0);

    // Server report breakdown
    const srv = t.server || {};

    let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <span style="font-size:11px;font-weight:700;color:#7A5AF8;letter-spacing:.06em">⏱ 交互时序分析</span>
      <button onclick="document.getElementById('anc-timing-panel').remove()" style="background:none;border:none;color:#555;cursor:pointer;font-size:18px;padding:0 2px;line-height:1">×</button>
    </div>
    <div style="color:#666;font-size:10px;margin-bottom:10px">op: <b style="color:#aaa">${t.op||'?'}</b> · target: <b style="color:#aaa">${t.target||'?'}</b></div>`;

    stages.forEach(s => {
      const w = pct(s.ms, total);
      const isStar = s.name.startsWith('★');
      html += `<div style="margin-bottom:5px">
        <div style="display:flex;justify-content:space-between;font-size:10px;color:${isStar?'#FFD700':'#aaa'};margin-bottom:2px">
          <span>${s.name}</span><span>${fmt(s.ms)}</span>
        </div>
        <div style="height:6px;border-radius:3px;background:#1a1a2e;overflow:hidden">
          <div style="height:100%;width:${w}%;background:${s.color};border-radius:3px;transition:width .3s"></div>
        </div>
      </div>`;
    });

    if (domDetail.length) {
      html += `<div style="color:#555;font-size:10px;margin:6px 0 4px">DOM sub-stages:</div>`;
      domDetail.forEach(d => {
        html += `<div style="display:flex;justify-content:space-between;font-size:10px;color:#555;margin-bottom:1px"><span>${d.name}</span><span>${fmt(d.ms)}</span></div>`;
      });
    }

    if (srv.ms_claude_gen != null) {
      html += `<div style="color:#555;font-size:10px;margin:6px 0 4px">Server timings:</div>`;
      html += `<div style="display:flex;justify-content:space-between;font-size:10px;color:#555"><span>  op recv → CC dispatched</span><span>${fmt(srv.ms_op_to_resolve)}</span></div>`;
      html += `<div style="display:flex;justify-content:space-between;font-size:10px;color:#F6AD55"><span>  ★ CC dispatch → anchor_patch</span><span>${fmt(srv.ms_claude_gen)}</span></div>`;
      html += `<div style="display:flex;justify-content:space-between;font-size:10px;color:#555"><span>  broadcast patches</span><span>${fmt(srv.ms_broadcast)}</span></div>`;
    }

    html += `<div style="margin-top:10px;border-top:1px solid #222;padding-top:8px;display:flex;justify-content:space-between;align-items:center">
      <span style="color:#555;font-size:10px">Total (client)</span>
      <span style="color:#7A5AF8;font-size:13px;font-weight:700">${fmt(total)}</span>
    </div>`;

    let panel = document.getElementById('anc-timing-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'anc-timing-panel';
      panel.style.cssText = 'position:fixed;bottom:16px;left:16px;background:rgba(8,8,16,0.95);color:#ccc;border-radius:14px;padding:16px 18px;font-family:JetBrains Mono,monospace;font-size:11px;z-index:99998;min-width:300px;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,0.6);border:1px solid rgba(255,255,255,0.07);backdrop-filter:blur(12px);';
      document.body.appendChild(panel);
    }
    panel.innerHTML = html;
  },

  // Helpers
  countAnchors() {
    return this.container.querySelectorAll('[data-anc]').length;
  },

  setStatus(cls, text) {
    this.statusEl.textContent = text;
    this.statusEl.className = 'toolbar-status ' + (cls || '');
  },

  toast(message) {
    let el = document.querySelector('.anc-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'anc-toast';
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
  }
};

// ────────────────────────────────────────────────────────────────────
// OpBars — per-cell streaming output bar
// Attaches a floating pill to the anchor element currently being processed
// by an agent thread. Streams agent_event payloads (thinking / tool_call /
// decision / partial_render / complete / error). Click bar to expand log.
//
// States: processing (yellow/amber) → done (green) | error (red)
// ────────────────────────────────────────────────────────────────────

window.OpBars = {
  bars: new Map(),  // anchorId -> { el, logEl, summaryEl, dotEl, dismissBtn, events, done, error, cleanupTimer }

  // Create bar immediately before any agent_event (eliminates perceived cold-start delay)
  preCreate(anchorId) {
    if (this.bars.has(anchorId)) return;
    const container = (window.Anchor && Anchor.container) || document.getElementById('anchor-content') || document;
    let target = null;
    try {
      target = container.querySelector('[data-anc="' + (window.CSS && CSS.escape ? CSS.escape(anchorId) : anchorId) + '"]');
    } catch { target = null; }
    if (!target) return;
    this.createBar(anchorId, target);
  },

  handleEvent(evt) {
    const anchorId = evt && evt.payload && evt.payload.target_anchor;
    if (!anchorId) return;
    const container = (window.Anchor && Anchor.container) || document.getElementById('anchor-content') || document;
    let target = null;
    try {
      target = container.querySelector('[data-anc="' + (window.CSS && CSS.escape ? CSS.escape(anchorId) : anchorId) + '"]');
    } catch { target = null; }
    if (!target) return;
    let entry = this.bars.get(anchorId);
    if (!entry) entry = this.createBar(anchorId, target);
    if (!entry) return;
    // Don't add events after terminal state
    if (entry.done || entry.error) return;
    entry.events.push(evt);
    this.renderSummary(entry, evt);
    this.renderLog(entry);
    const kind = (evt.kind || '').replace('agent.', '');
    if (kind === 'complete') {
      this.markComplete(anchorId);
    } else if (kind === 'error') {
      this.markError(anchorId, evt.payload?.message || 'Unknown error');
    }
  },

  createBar(anchorId, target) {
    if (getComputedStyle(target).position === 'static') target.style.position = 'relative';

    const el = document.createElement('div');
    el.className = 'anc-opbar';
    el.dataset.anchor = anchorId;
    el.dataset.kind = 'processing';

    const dot = document.createElement('span');
    dot.className = 'anc-opbar-dot';
    el.appendChild(dot);

    const summary = document.createElement('span');
    summary.className = 'anc-opbar-summary';
    summary.textContent = '处理中…';
    el.appendChild(summary);

    // Dismiss button (hidden until terminal state)
    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'anc-opbar-dismiss';
    dismissBtn.textContent = '×';
    dismissBtn.title = 'Close';
    dismissBtn.style.display = 'none';
    dismissBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      this.dismissBar(anchorId);
    });
    el.appendChild(dismissBtn);

    const caret = document.createElement('span');
    caret.className = 'anc-opbar-caret';
    caret.textContent = '▾';
    el.appendChild(caret);

    const log = document.createElement('div');
    log.className = 'anc-opbar-log';
    el.appendChild(log);

    el.addEventListener('click', (e) => {
      if (e.target === dismissBtn) return;
      e.stopPropagation();
      const expanding = !el.classList.contains('expanded');
      if (expanding) {
        // Move log to body with fixed positioning so it isn't clipped by overflow:hidden ancestors
        if (log.parentNode !== document.body) {
          document.body.appendChild(log);
        }
        const barRect = el.getBoundingClientRect();
        log.style.position = 'fixed';
        log.style.top = (barRect.bottom + 6) + 'px';
        log.style.right = (window.innerWidth - barRect.right) + 'px';
        log.style.zIndex = '99999';
        log.style.maxWidth = '520px';
        log.style.minWidth = '380px';
        log.style.display = 'block';
        // Close on outside click
        const onOutside = (ev) => {
          if (!log.contains(ev.target) && ev.target !== el) {
            el.classList.remove('expanded');
            log.style.display = 'none';
            document.removeEventListener('click', onOutside, true);
          }
        };
        setTimeout(() => document.addEventListener('click', onOutside, true), 0);
      } else {
        // Collapse: move log back into bar
        log.style.display = 'none';
        log.style.position = '';
        log.style.top = '';
        log.style.right = '';
        log.style.zIndex = '';
        log.style.maxWidth = '';
        log.style.minWidth = '';
        if (log.parentNode !== el) {
          el.appendChild(log);
        }
      }
      el.classList.toggle('expanded');
    });

    // Cleanup on remove
    if (window.MutationObserver) {
      new MutationObserver(() => {
        if (!document.body.contains(el)) {
          try { if (log.parentNode) log.remove(); } catch {}
        }
      }).observe(target, { childList: true });
    }

    target.appendChild(el);
    const entry = { el, logEl: log, summaryEl: summary, dotEl: dot, dismissBtn, events: [], done: false, error: false, cleanupTimer: null };
    this.bars.set(anchorId, entry);
    return entry;
  },

  _eventText(p) {
    if (!p) return '';
    if (p.summary) return p.summary;
    if (p.choice) return p.choice;
    if (p.tool) return p.tool + (p.status ? ' (' + p.status + ')' : '') + (p.input_summary ? ' — ' + p.input_summary : '') + (p.result_summary ? ' → ' + p.result_summary : '');
    if (p.message) return p.message;
    if (p.input_summary) return p.input_summary;
    if (p.result_summary) return p.result_summary;
    return '';
  },

  renderSummary(entry, evt) {
    const kind = (evt.kind || '').replace('agent.', '');
    const text = this._eventText(evt.payload);
    if (kind === 'thinking' && text) {
      entry.summaryEl.textContent = '🤔 ' + String(text).slice(0, 70);
    } else if (kind === 'tool_call') {
      entry.summaryEl.textContent = '🔧 ' + (evt.payload?.tool || 'tool') + (evt.payload?.input_summary ? ': ' + String(evt.payload.input_summary).slice(0, 60) : '');
    } else if (kind === 'decision' && text) {
      entry.summaryEl.textContent = '🎯 ' + String(text).slice(0, 70);
    } else if (kind === 'partial_render') {
      entry.summaryEl.textContent = '📄 部分渲染' + (evt.payload?.target_anchor ? ': ' + evt.payload.target_anchor : '');
    } else {
      entry.summaryEl.textContent = kind + (text ? ': ' + String(text).slice(0, 70) : '');
    }
    entry.el.dataset.kind = kind;
  },

  renderLog(entry) {
    entry.logEl.innerHTML = '';
    entry.events.forEach(e => {
      const kind = (e.kind || '').replace('agent.', '');
      let time = '';
      try { time = new Date(e.timestamp).toLocaleTimeString(); } catch {}
      const text = this._eventText(e.payload);
      const div = document.createElement('div');
      div.className = 'anc-opbar-entry anc-opbar-entry--' + kind;
      const tEl = document.createElement('span'); tEl.className = 'anc-opbar-time'; tEl.textContent = time;
      const kEl = document.createElement('span'); kEl.className = 'anc-opbar-kind'; kEl.textContent = kind;
      const xEl = document.createElement('span'); xEl.className = 'anc-opbar-text'; xEl.textContent = String(text);
      div.appendChild(tEl); div.appendChild(kEl); div.appendChild(xEl);
      entry.logEl.appendChild(div);
    });
    entry.logEl.scrollTop = entry.logEl.scrollHeight;
  },

  markComplete(anchorId) {
    const entry = this.bars.get(anchorId);
    if (!entry) return;
    entry.done = true;
    entry.el.dataset.kind = 'complete';
    entry.summaryEl.textContent = '✓ 完成';
    entry.dismissBtn.style.display = '';
    // Auto-dismiss after 12s
    if (entry.cleanupTimer) clearTimeout(entry.cleanupTimer);
    entry.cleanupTimer = setTimeout(() => this.dismissBar(anchorId), 12000);
  },

  markError(anchorId, message) {
    const entry = this.bars.get(anchorId);
    if (!entry) return;
    entry.error = true;
    entry.el.dataset.kind = 'error';
    entry.summaryEl.textContent = '✗ ' + String(message).slice(0, 70);
    entry.dismissBtn.style.display = '';
    // Stay visible longer (30s) for user to read error
    if (entry.cleanupTimer) clearTimeout(entry.cleanupTimer);
    entry.cleanupTimer = setTimeout(() => this.dismissBar(anchorId), 30000);
  },

  dismissBar(anchorId) {
    const entry = this.bars.get(anchorId);
    if (!entry) return;
    if (entry.cleanupTimer) clearTimeout(entry.cleanupTimer);
    entry.el.style.opacity = '0';
    entry.el.style.transform = 'translateY(-4px)';
    entry.el.style.pointerEvents = 'none';
    // Remove log if it was moved to body
    try { if (entry.logEl && entry.logEl.parentNode) entry.logEl.remove(); } catch {}
    setTimeout(() => {
      try { entry.el.remove(); } catch {}
      this.bars.delete(anchorId);
    }, 350);
  },

  clearAll() {
    this.bars.forEach((entry) => {
      if (entry.cleanupTimer) clearTimeout(entry.cleanupTimer);
      try { if (entry.logEl && entry.logEl.parentNode) entry.logEl.remove(); } catch {}
      try { entry.el.remove(); } catch {}
    });
    this.bars.clear();
  }
};

// ────────────────────────────────────────────────────────────────────
// Phase 1 — ContextPanel: 4-group multi-select (memory/skills/subagents/resources)
// ────────────────────────────────────────────────────────────────────

window.WorkspacePanel = {
  anchor: null,
  workspace: null,
  currentFileId: null,
  treeEl: null,
  _persistTimer: null,
  _loadingFile: false,

  init(anchor) {
    this.anchor = anchor;
    this.treeEl = document.getElementById('workspace-tree');
    document.getElementById('workspace-new-file')?.addEventListener('click', () => this.createFileInteractive());
    document.getElementById('workspace-new-folder')?.addEventListener('click', () => this.createFolderInteractive());
    document.getElementById('workspace-link-folder')?.addEventListener('click', () => this.linkFolderInteractive());
    document.getElementById('workspace-new-trading-file')?.addEventListener('click', () => this.createTradingFileInteractive());
    this._linkedFolderContents = new Map();
    this.load();
  },

  async load() {
    try {
      const res = await fetch('/workspace');
      const data = await res.json();
      this.workspace = data.workspace;
      this.currentFileId = this.workspace.current_file_id || null;
      if (this.anchor) this.anchor.currentFileId = this.currentFileId;
      this.renderTree();
      const current = this.currentFile();
      if (current && current.html && window.location.hash) this.applyFile(current);
      else if (this.anchor) this.anchor._syncHomeVisibility();
      if (window.HistoryPanel) HistoryPanel.setFile(current);
    } catch (e) {
      console.error('[WorkspacePanel] load failed:', e);
    }
  },

  currentFile() {
    return this.workspace && this.currentFileId ? this.workspace.files[this.currentFileId] : null;
  },

  renderTree() {
    if (!this.treeEl || !this.workspace) return;
    this.treeEl.innerHTML = '';
    const nodes = this.workspace.nodes || [];
    const byParent = new Map();
    nodes.forEach(node => {
      const parent = node.parent_id || '__root__';
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(node);
    });
    const self = this;
    const renderChildren = (parentId, depth) => {
      const children = (byParent.get(parentId) || []).slice().sort((a, b) => {
        if (a.type !== b.type) return (a.type === 'folder' || a.type === 'linked-folder') ? -1 : 1;
        return (a.name || '').localeCompare(b.name || '');
      });
      children.forEach(node => {
        if (node.id === 'folder_root') {
          renderChildren(node.id, depth);
          return;
        }
        const isLinkedFolder = node.type === 'linked-folder';
        const iconClass = isLinkedFolder ? 'ph-link' : node.type === 'folder' ? 'ph-folder' : 'ph-file-html';
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'workspace-node workspace-node--' + node.type + (node.id === this.currentFileId ? ' is-active' : '');
        row.style.paddingLeft = (10 + depth * 14) + 'px';
        row.innerHTML = `<i class="ph-bold ${iconClass}"></i><span></span>`;
        row.querySelector('span').textContent = node.name || node.id;
        if (node.type === 'file') {
          row.addEventListener('click', () => this.openFile(node.id));
        } else if (isLinkedFolder) {
          row.addEventListener('click', () => this._toggleLinkedFolder(row, node));
        } else if (node.type === 'folder') {
          row.addEventListener('click', () => this._toggleFolder(row, node.id));
        }
        this.treeEl.appendChild(row);
      });
    };
    renderChildren(null, 0);
  },

  _toggleFolder(row, nodeId) {
    const existing = row.querySelector('.folder-children');
    if (existing) { existing.remove(); row.classList.remove('is-expanded'); return; }
    const nodes = this.workspace?.nodes || [];
    const byParent = new Map();
    nodes.forEach(n => {
      const parent = n.parent_id || '__root__';
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(n);
    });
    const children = (byParent.get(nodeId) || []).slice().sort((a, b) => {
      if (a.type !== b.type) return (a.type === 'folder' || a.type === 'linked-folder') ? -1 : 1;
      return (a.name || '').localeCompare(b.name || '');
    });
    if (children.length === 0) return;
    const container = document.createElement('div');
    container.className = 'folder-children';
    children.forEach(node => {
      const isLinkedFolder = node.type === 'linked-folder';
      const iconClass = isLinkedFolder ? 'ph-link' : node.type === 'folder' ? 'ph-folder' : 'ph-file-html';
      const childRow = document.createElement('button');
      childRow.type = 'button';
      childRow.className = 'workspace-node workspace-node--' + node.type + (node.id === this.currentFileId ? ' is-active' : '');
      childRow.style.paddingLeft = (10 + (parseInt(row.style.paddingLeft) || 10) + 14) + 'px';
      childRow.innerHTML = `<i class="ph-bold ${iconClass}"></i><span></span>`;
      childRow.querySelector('span').textContent = node.name || node.id;
      if (node.type === 'file') {
        childRow.addEventListener('click', () => this.openFile(node.id));
      } else if (isLinkedFolder) {
        childRow.addEventListener('click', () => this._toggleLinkedFolder(childRow, node));
      } else if (node.type === 'folder') {
        childRow.addEventListener('click', () => this._toggleFolder(childRow, node.id));
      }
      container.appendChild(childRow);
    });
    row.insertAdjacentElement('afterend', container);
    row.classList.add('is-expanded');
  },

  async _toggleLinkedFolder(row, node) {
    const existing = row.querySelector('.linked-folder-children');
    if (existing) { existing.remove(); row.classList.remove('is-expanded'); return; }
    try {
      const res = await fetch('/workspace/linked-folder/' + encodeURIComponent(node.id) + '/contents');
      const data = await res.json();
      if (!data.ok) return;
      this._linkedFolderContents.set(node.id, data.children);
      const container = document.createElement('div');
      container.className = 'linked-folder-children';
      data.children.forEach(child => {
        const childRow = document.createElement('button');
        childRow.type = 'button';
        childRow.className = 'workspace-node workspace-node--' + child.type;
        childRow.style.paddingLeft = '24px';
        const childIcon = child.type === 'folder' ? 'ph-folder' : 'ph-file-html';
        childRow.innerHTML = `<i class="ph-bold ${childIcon}"></i><span></span>`;
        childRow.querySelector('span').textContent = child.name;
        if (child.type === 'file' && child.name.endsWith('.html')) {
          childRow.addEventListener('click', () => this._openLinkedFile(child.path, child.name));
        } else if (child.type === 'folder') {
          childRow.addEventListener('click', () => this._openLinkedFolder(childRow, child.path, child.name));
        }
        container.appendChild(childRow);
      });
      row.insertAdjacentElement('afterend', container);
      row.classList.add('is-expanded');
    } catch (e) { console.error('[WorkspacePanel] failed to load linked folder:', e); }
  },

  async _openLinkedFolder(row, folderPath, folderName) {
    try {
      const res = await fetch('/workspace/linked-folder/contents?path=' + encodeURIComponent(folderPath));
      const data = await res.json();
      if (!data.ok) return;
      const container = document.createElement('div');
      container.className = 'linked-folder-children';
      data.children.forEach(child => {
        const childRow = document.createElement('button');
        childRow.type = 'button';
        childRow.className = 'workspace-node workspace-node--' + child.type;
        childRow.style.paddingLeft = '24px';
        childRow.innerHTML = `<i class="ph-bold ${child.type === 'folder' ? 'ph-folder' : 'ph-file-html'}"></i><span></span>`;
        childRow.querySelector('span').textContent = child.name;
        if (child.type === 'file' && child.name.endsWith('.html')) {
          childRow.addEventListener('click', () => this._openLinkedFile(child.path, child.name));
        }
        container.appendChild(childRow);
      });
      row.insertAdjacentElement('afterend', container);
    } catch (e) { console.error('[WorkspacePanel] failed to load subfolder:', e); }
  },

  async _openLinkedFile(filePath, fileName) {
    try {
      const res = await fetch('/workspace/linked-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, name: fileName })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to open linked file');
      this.workspace = data.workspace;
      this.currentFileId = data.file.id;
      if (this.anchor) this.anchor.currentFileId = this.currentFileId;
      this.renderTree();
      this.applyFile(data.file);
    } catch (e) {
      this.anchor?.toast('Failed to open linked file: ' + (e.message || 'Unknown error'));
    }
  },

  async linkFolderInteractive() {
    const input = document.createElement('input');
    input.type = 'file';
    input.webkitdirectory = true;
    input.style.display = 'none';
    document.body.appendChild(input);
    const self = this;
    input.addEventListener('change', async () => {
      if (!input.files || input.files.length === 0) { document.body.removeChild(input); return; }
      // Get folder path from first file's webkitRelativePath
      const folderPath = input.files[0].webkitRelativePath.split('/')[0];
      // Prompt for full path since File.path not available in all browsers
      const fullPath = prompt('Enter the full path to the folder:', 'C:\\Users\\' + folderPath);
      if (!fullPath) { document.body.removeChild(input); return; }
      try {
        const res = await fetch('/workspace/link-folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: fullPath })
        });
        const data = await res.json();
        if (data.ok) { this.workspace = data.workspace; this.renderTree(); }
      } catch (e) { console.error('[WorkspacePanel] link folder failed:', e); }
      document.body.removeChild(input);
    });
    input.click();
  },

  async createFileFromPrompt(prompt) {
    const title = prompt.trim().slice(0, 60) || 'Untitled';
    const res = await fetch('/workspace/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: title, prompt })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'workspace file create failed');
    this.workspace = data.workspace;
    this.currentFileId = data.file.id;
    if (this.anchor) this.anchor.currentFileId = this.currentFileId;
    this.renderTree();
    if (window.HistoryPanel) HistoryPanel.setFile(data.file);
    document.getElementById('anchor-home')?.classList.add('is-hidden');
    document.getElementById('anchor-shell')?.classList.add('has-content');
    return data.file;
  },

  async createFileInteractive() {
    const name = prompt('File name', 'Untitled');
    if (!name) return;
    try {
      const file = await this.createFileFromPrompt(name);
      this.applyFile(file);
    } catch (e) {
      this.anchor?.toast('Failed to create file: ' + (e.message || 'Unknown error'));
    }
  },

  async createTradingFileInteractive() {
    const name = prompt('Trading file name', 'Trading Analysis');
    if (!name) return;
    try {
      const res = await fetch('/workspace/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, domain: 'trading.private', prompt: name })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Failed to create trading file');
      this.workspace = data.workspace;
      this.currentFileId = data.file.id;
      if (this.anchor) this.anchor.currentFileId = this.currentFileId;
      this.renderTree();
      if (window.HistoryPanel) HistoryPanel.setFile(data.file);
      document.getElementById('anchor-home')?.classList.add('is-hidden');
      document.getElementById('anchor-shell')?.classList.add('has-content');
      this.applyFile(data.file);
    } catch (e) {
      this.anchor?.toast('Failed to create trading file: ' + (e.message || 'Unknown error'));
    }
  },

  async createFolderInteractive() {
    const name = prompt('Folder name', 'New folder');
    if (!name) return;
    try {
      const res = await fetch('/workspace/folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Folder creation failed');
      this.workspace = data.workspace;
      this.renderTree();
    } catch (e) {
      this.anchor?.toast('Failed to create folder: ' + (e.message || 'Unknown error'));
    }
  },

  async openFile(id) {
    const file = this.workspace && this.workspace.files[id];
    if (!file) return;
    await fetch('/workspace/file/' + encodeURIComponent(id), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ set_current: true })
    }).catch(() => {});
    this.currentFileId = id;
    if (this.anchor) this.anchor.currentFileId = id;
    this.renderTree();
    this.applyFile(file);
  },

  applyServerCurrent(file) {
    if (!file) return;
    this.currentFileId = file.id;
    if (this.workspace) {
      this.workspace.current_file_id = file.id;
      this.workspace.files[file.id] = file;
    }
    if (this.anchor) this.anchor.currentFileId = file.id;
    this.applyFile(file);
  },

  applyFile(file) {
    if (!this.anchor || !file) return;
    this._loadingFile = true;
    this.currentFileId = file.id;
    this.anchor.currentFileId = file.id;
    this.anchor.currentHtml = file.html || '';
    this.anchor.container.innerHTML = file.html || '';
    this.anchor.injectHandles();
    this.anchor.injectCollapse();
    this.anchor.infoEl.textContent = this.anchor.countAnchors() + ' anchors';
    this.anchor._syncHomeVisibility();
    this._loadingFile = false;
    if (window.HistoryPanel) HistoryPanel.setFile(file);
    if (window.ContextPanel) ContextPanel.applyFileContext(file.context || null);
  },

  persistCurrentHtml(html) {
    if (this._loadingFile || !this.currentFileId) return;
    if (this.workspace && this.workspace.files[this.currentFileId]) {
      this.workspace.files[this.currentFileId].html = html;
    }
    clearTimeout(this._persistTimer);
    this._persistTimer = setTimeout(() => {
      fetch('/workspace/file/' + encodeURIComponent(this.currentFileId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ html })
      }).catch(() => {});
    }, 250);
  },

  persistCurrentContext(context) {
    if (!this.currentFileId) return;
    fetch('/workspace/file/' + encodeURIComponent(this.currentFileId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ context })
    }).catch(() => {});
  }
};

window.ContextPanel = {
  panel: null,
  anchor: null,
  manifest: { memory: [], skills: [], subagents: [], resources: [] },
  selected: { memory: new Set(), skills: new Set(), subagents: new Set(), resources: new Set() },
  userResources: [],
  _defaultProcessor: null,
  _processorDetailsEl: null,

  init(anchor) {
    this.anchor = anchor;
    this.panel = document.getElementById('anchor-context-panel');
    if (!this.panel) return;
    this._loadFromStorage();
    this._loadUserResources();
    this._loadDefaultProcessor();
    this._wireFilters();
    this._wireSkillForm();
    this._wireResourceForm();
    this.refresh();
  },

  _loadDefaultProcessor() {
    try {
      const raw = localStorage.getItem('anchor.defaultProcessor');
      this._defaultProcessor = raw ? JSON.parse(raw) : null;
    } catch { this._defaultProcessor = null; }
    if (this.anchor) this.anchor._defaultProcessor = this._defaultProcessor;
  },

  _saveDefaultProcessor(cfg) {
    this._defaultProcessor = cfg;
    if (this.anchor) this.anchor._defaultProcessor = cfg;
    try {
      if (cfg) localStorage.setItem('anchor.defaultProcessor', JSON.stringify(cfg));
      else localStorage.removeItem('anchor.defaultProcessor');
    } catch {}
    if (window.WorkspacePanel) {
      const bundle = this.getBundle();
      bundle.subagent_id = cfg ? cfg.subagent_id : null;
      bundle.context_mode = cfg ? cfg.context_mode : null;
      WorkspacePanel.persistCurrentContext(bundle);
    }
  },

  _initProcessorSection() {
    const body = this.panel.querySelector('.side-panel-body');
    if (!body) return;
    // Remove existing injected section to allow re-render
    if (this._processorDetailsEl && this._processorDetailsEl.parentNode) {
      this._processorDetailsEl.remove();
    }
    const det = document.createElement('details');
    det.setAttribute('data-group', 'default-processor');
    const summary = document.createElement('summary');
    const dp = this._defaultProcessor;
    const activeLabel = dp && dp.subagent_id ? dp.subagent_id : '主线程';
    summary.innerHTML = `默认处理器 <span class="group-count">${activeLabel}</span>`;
    det.appendChild(summary);

    const content = document.createElement('div');
    content.className = 'group-list';
    content.style.padding = '6px 0';

    const agentHdr = document.createElement('div');
    agentHdr.style.cssText = 'font-size:11px;font-weight:600;color:var(--fg-2,#555);margin-bottom:4px;';
    agentHdr.textContent = 'Subagent';
    content.appendChild(agentHdr);

    const subagents = this.manifest.subagents || [];
    const allOptions = [{ id: null, name: '主线程（默认）', can_patch: true }, ...subagents];
    let selectedId = (dp && dp.subagent_id) || null;
    let selectedMode = (dp && dp.context_mode) || 'none';

    allOptions.forEach(ag => {
      const row = document.createElement('label');
      row.className = 'context-item';
      row.style.opacity = ag.can_patch === false ? '0.55' : '';
      const rb = document.createElement('input');
      rb.type = 'radio';
      rb.name = 'dp-agent';
      rb.value = ag.id || '';
      rb.checked = (ag.id === selectedId);
      const meta = document.createElement('div');
      meta.className = 'item-meta';
      const nm = document.createElement('span');
      nm.className = 'item-name';
      nm.textContent = ag.name || ag.id;
      if (ag.can_patch === false) {
        nm.insertAdjacentHTML('beforeend', ' <span title="可能无法调用 anchor_patch" style="color:var(--amber,#f59e0b)">⚠</span>');
      }
      meta.appendChild(nm);
      row.appendChild(rb);
      row.appendChild(meta);
      rb.addEventListener('change', () => {
        selectedId = ag.id || null;
        modeSection.style.display = selectedId ? '' : 'none';
      });
      content.appendChild(row);
    });

    const modeSection = document.createElement('div');
    modeSection.style.display = selectedId ? '' : 'none';
    const modeHdr = document.createElement('div');
    modeHdr.style.cssText = 'font-size:11px;font-weight:600;color:var(--fg-2,#555);margin:8px 0 4px;';
    modeHdr.textContent = '上下文模式';
    modeSection.appendChild(modeHdr);
    [['none', '无上下文（最快）'], ['summarized', '摘要式压缩'], ['full', '完整上下文']].forEach(([id, label]) => {
      const row = document.createElement('label');
      row.className = 'context-item';
      const rb = document.createElement('input');
      rb.type = 'radio';
      rb.name = 'dp-mode';
      rb.value = id;
      rb.checked = (id === selectedMode);
      rb.addEventListener('change', () => { selectedMode = id; });
      const meta = document.createElement('div');
      meta.className = 'item-meta';
      const nm = document.createElement('span');
      nm.className = 'item-name';
      nm.textContent = label;
      meta.appendChild(nm);
      row.appendChild(rb);
      row.appendChild(meta);
      modeSection.appendChild(row);
    });
    content.appendChild(modeSection);

    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn btn--sm btn--brand';
    saveBtn.style.marginTop = '8px';
    saveBtn.textContent = '保存默认';
    saveBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const cfg = selectedId ? { subagent_id: selectedId, context_mode: selectedMode } : null;
      this._saveDefaultProcessor(cfg);
      const countEl = det.querySelector('.group-count');
      if (countEl) countEl.textContent = cfg ? cfg.subagent_id : '主线程';
      this.anchor && this.anchor.toast('默认处理器已更新: ' + (cfg ? cfg.subagent_id + ' / ' + cfg.context_mode : '主线程'));
    });
    content.appendChild(saveBtn);

    // Custom subagent creation form
    const newHdr = document.createElement('div');
    newHdr.style.cssText = 'font-size:11px;font-weight:600;color:var(--fg-2,#555);margin-top:12px;margin-bottom:4px;border-top:1px solid var(--border-1,#e5e5e5);padding-top:8px;';
    newHdr.textContent = '+ 新建 Subagent';
    newHdr.style.cursor = 'pointer';
    content.appendChild(newHdr);

    const formWrap = document.createElement('div');
    formWrap.style.display = 'none';
    newHdr.addEventListener('click', () => {
      formWrap.style.display = formWrap.style.display === 'none' ? '' : 'none';
    });

    const mkInput = (placeholder, type = 'text') => {
      const el = document.createElement(type === 'textarea' ? 'textarea' : 'input');
      if (type !== 'textarea') el.type = type;
      el.placeholder = placeholder;
      el.style.cssText = 'width:100%;box-sizing:border-box;font-size:12px;padding:4px 6px;margin-bottom:4px;border:1px solid var(--border-1,#ddd);border-radius:4px;background:var(--bg-1,#fff);color:var(--fg-1,#222);resize:vertical;';
      if (type === 'textarea') el.rows = 3;
      return el;
    };

    const nameInput = mkInput('agent 名称 (a-z0-9_-)');
    const descInput = mkInput('描述（一行）');
    const promptInput = mkInput('系统提示词 (system prompt)', 'textarea');
    const allToolsCb = document.createElement('input');
    allToolsCb.type = 'checkbox';
    allToolsCb.checked = true;
    const cbLabel = document.createElement('label');
    cbLabel.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:12px;margin-bottom:6px;cursor:pointer;';
    const cbText = document.createTextNode(' 使用所有工具（含 MCP）');
    cbLabel.appendChild(allToolsCb);
    cbLabel.appendChild(cbText);

    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn--sm btn--brand';
    submitBtn.textContent = '创建';
    submitBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const agentName = nameInput.value.trim();
      if (!agentName) { this.anchor && this.anchor.toast('请输入 agent 名称'); return; }
      submitBtn.disabled = true;
      submitBtn.textContent = '保存中...';
      try {
        const res = await fetch('/agents/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: agentName,
            description: descInput.value.trim(),
            system_prompt: promptInput.value.trim(),
            tools: allToolsCb.checked ? '*' : []
          })
        });
        const data = await res.json();
        if (data.ok) {
          this.anchor && this.anchor.toast('已创建 subagent: ' + agentName);
          nameInput.value = ''; descInput.value = ''; promptInput.value = '';
          // manifest_updated broadcast will trigger refresh
        } else {
          this.anchor && this.anchor.toast('错误: ' + data.error);
        }
      } catch (err) {
        this.anchor && this.anchor.toast('请求失败: ' + err.message);
      }
      submitBtn.disabled = false;
      submitBtn.textContent = '创建';
    });

    [nameInput, descInput, promptInput, cbLabel, submitBtn].forEach(el => formWrap.appendChild(el));
    content.appendChild(formWrap);

    det.appendChild(content);
    body.appendChild(det);
    this._processorDetailsEl = det;
  },

  _wireResourceForm() {
    const addBtn = this.panel.querySelector('.resource-add-btn');
    const nameInput = this.panel.querySelector('.resource-name-input');
    const urlInput = this.panel.querySelector('.resource-url-input');
    if (!addBtn) return;
    addBtn.addEventListener('click', () => {
      const name = (nameInput?.value || '').trim();
      const url = (urlInput?.value || '').trim();
      if (!name) return;
      this.addUserResource(name, url);
      if (nameInput) nameInput.value = '';
      if (urlInput) urlInput.value = '';
    });
  },

  _wireSkillForm() {
    const details = this.panel.querySelector('details[data-group="skills"]');
    if (!details || details.querySelector('.skill-form')) return;
    const form = document.createElement('div');
    form.className = 'skill-form';
    form.innerHTML = [
      '<input type="text" class="skill-name-input" placeholder="Skill name...">',
      '<input type="url" class="skill-url-input" placeholder="GitHub repo or resource URL...">',
      '<button class="btn btn--sm btn--brand skill-add-btn" type="button">+ Add</button>'
    ].join('');
    details.appendChild(form);
    const addBtn = form.querySelector('.skill-add-btn');
    const nameInput = form.querySelector('.skill-name-input');
    const urlInput = form.querySelector('.skill-url-input');
    addBtn.addEventListener('click', async () => {
      const name = (nameInput.value || '').trim();
      const url = (urlInput.value || '').trim();
      if (!name) return;
      addBtn.disabled = true;
      try {
        const res = await fetch('/skills/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, url, file_id: window.WorkspacePanel?.currentFileId || null })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'register failed');
        this.selected.skills.add(data.skill.id);
        this._saveToStorage();
        nameInput.value = '';
        urlInput.value = '';
        await this.refresh();
        this.anchor && this.anchor.toast('Skill registered: ' + data.skill.name);
      } catch (e) {
        this.anchor && this.anchor.toast('Skill register failed: ' + e.message);
      } finally {
        addBtn.disabled = false;
      }
    });
  },

  async addUserResource(name, url) {
    try {
      const res = await fetch('/resources/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, url, file_id: window.WorkspacePanel?.currentFileId || null })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'register failed');
      this.selected.resources.add(data.resource.id);
      this._saveToStorage();
      await this.refresh();
      this.anchor && this.anchor.toast('Resource registered: ' + data.resource.name);
    } catch (e) {
      const id = 'ures_' + Date.now().toString(36);
      this.userResources.push({ id, name, url: url || '', addedAt: Date.now() });
      this._saveUserResources();
      this._renderGroup('resources');
      this.anchor && this.anchor.toast('Resource saved locally: ' + e.message);
    }
  },

  removeUserResource(id) {
    this.userResources = this.userResources.filter(r => r.id !== id);
    this.selected.resources.delete(id);
    this._saveUserResources();
    this._saveToStorage();
    this._renderGroup('resources');
  },

  async refresh() {
    try {
      const res = await fetch('/context-manifest');
      this.manifest = await res.json();
      this._renderAllGroups();
      this._initProcessorSection();
    } catch (e) {
      console.error('[ContextPanel] manifest load failed:', e);
    }
  },

  _renderAllGroups() {
    ['memory', 'skills', 'subagents', 'resources'].forEach(group => this._renderGroup(group));
  },

  _renderGroup(group) {
    const root = this.panel.querySelector(`details[data-group="${group}"] .group-list`);
    const countEl = this.panel.querySelector(`details[data-group="${group}"] .group-count`);
    if (!root) return;
    root.innerHTML = '';
    let items = this.manifest[group] || [];
    // Merge user resources
    if (group === 'resources') {
      items = [...items, ...this.userResources.map(r => ({
        id: r.id, name: r.name, description: r.url || 'user link', type: 'user', _isUser: true
      }))];
    }
    items.forEach(item => root.appendChild(this._renderItem(group, item)));
    if (countEl) countEl.textContent = this.selected[group].size + '/' + items.length;
  },

  _renderItem(group, item) {
    const row = document.createElement('label');
    row.className = 'context-item';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = this.selected[group].has(item.id);
    cb.addEventListener('change', () => this._toggle(group, item.id, cb.checked));
    const meta = document.createElement('div');
    meta.className = 'item-meta';
    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = item.name || item.id;
    const desc = document.createElement('span');
    desc.className = 'item-desc';
    desc.textContent = item.description || '';
    const linkUrl = item.url || (item.description && item.description.startsWith('http') ? item.description : '');
    if (linkUrl) {
      const link = document.createElement('a');
      link.href = linkUrl;
      link.textContent = linkUrl;
      link.target = '_blank';
      link.style.cssText = 'color:var(--brand);font-size:11px;word-break:break-all;';
      desc.textContent = '';
      desc.appendChild(link);
    }
    meta.appendChild(name);
    meta.appendChild(desc);
    row.appendChild(cb);
    row.appendChild(meta);
    // Delete button for user resources
    if (item._isUser) {
      const delBtn = document.createElement('button');
      delBtn.textContent = '×';
      delBtn.className = 'btn-remove-resource';
      delBtn.title = 'Remove this resource';
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        this.removeUserResource(item.id);
      });
      row.appendChild(delBtn);
    }
    return row;
  },

  _toggle(group, id, checked) {
    if (checked) this.selected[group].add(id);
    else this.selected[group].delete(id);
    this._saveToStorage();
    this._renderGroup(group);
    this._notifyChanged();
  },

  _wireFilters() {
    this.panel.querySelectorAll('.group-filter').forEach(input => {
      input.addEventListener('input', () => {
        const term = input.value.toLowerCase();
        const parent = input.closest('details');
        const items = parent.querySelectorAll('.context-item');
        items.forEach(el => {
          const text = (el.querySelector('.item-name')?.textContent || '') + ' ' +
                       (el.querySelector('.item-desc')?.textContent || '');
          el.style.display = term ? (text.toLowerCase().includes(term) ? '' : 'none') : '';
        });
      });
    });
  },

  _notifyChanged() {
    if (this.anchor?.ws?.readyState === WebSocket.OPEN) {
      this.anchor.ws.send(JSON.stringify({ type: 'context_changed', bundle: this.getBundle() }));
    }
  },

  getBundle() {
    return {
      memory_ids:    Array.from(this.selected.memory),
      skill_ids:     Array.from(this.selected.skills),
      subagent_ids:  Array.from(this.selected.subagents),
      resource_ids:  Array.from(this.selected.resources),
      scope_hint:    'standard',
      transient_override: false
    };
  },

  applyFileContext(context) {
    if (!context) return;
    this.selected.memory = new Set(context.memory_ids || []);
    this.selected.skills = new Set(context.skill_ids || []);
    this.selected.subagents = new Set(context.subagent_ids || []);
    this.selected.resources = new Set(context.resource_ids || []);
    if (context.subagent_id) {
      this._saveDefaultProcessor({ subagent_id: context.subagent_id, context_mode: context.context_mode || 'none' });
    }
    this._renderAllGroups();
    this._initProcessorSection();
  },

  _loadFromStorage() {
    try {
      const raw = localStorage.getItem('anchor.contextBundle');
      if (!raw) return;
      const data = JSON.parse(raw);
      ['memory', 'skills', 'subagents', 'resources'].forEach(g => {
        this.selected[g] = new Set(data[g] || []);
      });
    } catch (e) { /* ignore */ }
  },

  _saveToStorage() {
    const data = {
      memory:     Array.from(this.selected.memory),
      skills:     Array.from(this.selected.skills),
      subagents:  Array.from(this.selected.subagents),
      resources:  Array.from(this.selected.resources)
    };
    localStorage.setItem('anchor.contextBundle', JSON.stringify(data));
    if (window.WorkspacePanel) WorkspacePanel.persistCurrentContext(this.getBundle());
  },

  _loadUserResources() {
    try {
      const raw = localStorage.getItem('anchor.userResources');
      if (raw) this.userResources = JSON.parse(raw);
    } catch { this.userResources = []; }
  },

  _saveUserResources() {
    try {
      localStorage.setItem('anchor.userResources', JSON.stringify(this.userResources));
    } catch { /* ignore */ }
  }
};

// ────────────────────────────────────────────────────────────────────
// Phase 3 — SelectionToolbar: free text selection → floating op buttons
// ────────────────────────────────────────────────────────────────────

window.SelectionToolbar = {
  toolbar: null,
  anchor: null,
  _debounce: null,

  init(anchor) {
    this.anchor = anchor;
    this.toolbar = document.getElementById('anchor-floating-toolbar');
    if (!this.toolbar) return;
    this._wireButtons();
    document.addEventListener('selectionchange', () => this._onSelectionChange());
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hide(); });
  },

  _wireButtons() {
    this.toolbar.querySelectorAll('button[data-op]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        this._dispatch(btn.getAttribute('data-op'));
      });
    });
  },

  _onSelectionChange() {
    clearTimeout(this._debounce);
    this._debounce = setTimeout(() => this._evaluate(), 100);
  },

  _evaluate() {
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || !this._isWithinAnchorContent(sel)) {
      this.hide();
      return;
    }
    this._positionFor(sel);
  },

  _isWithinAnchorContent(sel) {
    if (!sel.anchorNode) return false;
    return !!(this.anchor.container && this.anchor.container.contains(sel.anchorNode));
  },

  _positionFor(sel) {
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (!rect.width && !rect.height) { this.hide(); return; }
    const toolbarW = this.toolbar.offsetWidth || 240;
    const toolbarH = this.toolbar.offsetHeight || 40;
    let top = rect.bottom + 8;
    // Switch above if too close to bottom edge
    if (top + toolbarH > window.innerHeight) {
      top = rect.top - toolbarH - 8;
      if (top < 0) top = rect.bottom + 4; // fallback: tiny gap
    }
    let left = rect.left;
    if (left + toolbarW > window.innerWidth - 8) {
      left = window.innerWidth - toolbarW - 8;
    }
    if (left < 4) left = 4;
    this.toolbar.classList.remove('hidden');
    this.toolbar.style.top  = (window.scrollY + top) + 'px';
    this.toolbar.style.left = (window.scrollX + left) + 'px';
  },

  hide() { this.toolbar?.classList.add('hidden'); },

  _dispatch(op) {
    const sel = window.getSelection();
    const text = sel?.toString();
    if (!text) return;
    const meta = this._buildSelectionMeta(sel);
    // B.3.4: if no ancestor anchor, treat as global
    const targetKind = meta.ancestor_anchor ? 'selection' : 'global';
    const targetRef = targetKind === 'global' ? 'global' : ('selection:' + meta.ancestor_anchor + ':' + this._hash(text));

    // ops that need instruction → show inline input row
    if (['refine','branch','annotate','ask'].includes(op)) {
      this._showInstructionPrompt(op, targetKind, targetRef, meta);
    } else {
      this._doDispatch(op, targetKind, targetRef, '', meta);
    }
  },

  _showInstructionPrompt(op, targetKind, targetRef, meta) {
    const existing = this.toolbar.querySelector('.selection-input-row');
    if (existing) existing.remove();
    const row = document.createElement('div');
    row.className = 'selection-input-row';
    row.style.cssText = 'display:flex;gap:4px;padding:4px 0;';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'What to change?';
    input.style.cssText = 'flex:1;min-width:120px;padding:2px 6px;border:1px solid var(--border);border-radius:6px;background:transparent;color:inherit;font:inherit;';
    const submit = document.createElement('button');
    submit.textContent = 'Go';
    submit.className = 'btn btn--sm';
    const cancel = document.createElement('button');
    cancel.textContent = '×';
    cancel.className = 'btn btn--ghost btn--sm';
    row.appendChild(input); row.appendChild(submit); row.appendChild(cancel);
    this.toolbar.appendChild(row);
    input.focus();
    const finish = (instr) => {
      row.remove();
      this._doDispatch(op, targetKind, targetRef, instr || '', meta);
    };
    submit.addEventListener('click', (e) => { e.stopPropagation(); finish(input.value.trim()); });
    cancel.addEventListener('click', (e) => { e.stopPropagation(); row.remove(); this.hide(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.stopPropagation(); finish(input.value.trim()); }
      if (e.key === 'Escape') { e.stopPropagation(); row.remove(); this.hide(); }
    });
  },

  _doDispatch(op, targetKind, targetRef, instruction, meta) {
    if (op === 'annotate') {
      this.anchor._handleAnnotateOp(targetRef, instruction);
      this.hide();
      return;
    }
    const envelope = this.anchor.buildEnvelope({
      op, target_kind: targetKind, target_ref: targetRef, instruction, selection: meta
    });
    this.anchor.sendEnvelope(envelope);
    this.hide();
  },

  _buildSelectionMeta(sel) {
    const text = sel.toString();
    let ancestor = sel.anchorNode;
    while (ancestor && !(ancestor.nodeType === 1 && ancestor.hasAttribute('data-anc'))) {
      ancestor = ancestor.parentNode;
    }
    // Compute offsets within the ancestor's text content
    let startOffset = 0;
    let endOffset = text.length;
    if (ancestor) {
      const ancText = ancestor.textContent;
      const selStart = ancText.indexOf(text);
      if (selStart >= 0) {
        startOffset = selStart;
        endOffset = selStart + text.length;
      }
    }
    // Compute simplified dom_path from #anchor-content
    let domPath = '';
    try {
      const parts = [];
      let node = sel.anchorNode;
      while (node && node !== this.anchor.container) {
        if (node.nodeType === 1) {
          const tag = node.tagName.toLowerCase();
          let sel = tag;
          if (node.getAttribute && node.hasAttribute('data-anc')) {
            sel += '[data-anc="' + node.getAttribute('data-anc') + '"]';
          } else if (node.id) {
            sel += '#' + node.id;
          } else {
            const parent = node.parentNode;
            if (parent) {
              const idx = Array.from(parent.children).indexOf(node) + 1;
              sel += ':nth-child(' + idx + ')';
            }
          }
          parts.unshift(sel);
        }
        node = node.parentNode;
      }
      domPath = parts.join(' > ');
    } catch (e) { domPath = ''; }

    return {
      text, start_offset: startOffset, end_offset: endOffset,
      ancestor_anchor: ancestor ? ancestor.getAttribute('data-anc') : null,
      dom_path: domPath
    };
  },

  _hash(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h).toString(36).slice(0, 8);
  }
};

// ────────────────────────────────────────────────────────────────────
// Phase 4 — TimelinePanel: render agent_event stream
// ────────────────────────────────────────────────────────────────────

window.TimelinePanel = {
  panel: null,
  list: null,
  anchor: null,
  _currentGroup: null,

  init(anchor) {
    this.anchor = anchor;
    this.panel = document.getElementById('anchor-timeline-panel');
    this.list = document.getElementById('timeline-events');
  },

  append(event) {
    if (!this.list) return;
    if (event.kind === 'user.intent') {
      // Auto-fold previous group
      if (this._currentGroup) {
        this._currentGroup.removeAttribute('open');
        this._currentGroup = null;
      }
      this._startNewGroup();
    }
    const card = this._renderEvent(event);
    // If we have an open group, append to it, else directly to list
    const groupOpen = this.list.querySelector('details.timeline-group[open]');
    if (groupOpen) {
      groupOpen.appendChild?.(card);
      // details elements use a nested structure, append to its last child if needed
      // Actually, let's keep things simple: append to the group's own .group-body or directly
      let body = groupOpen.querySelector('.group-body');
      if (!body) {
        body = document.createElement('div');
        body.className = 'group-body';
        groupOpen.appendChild(body);
      }
      body.appendChild(card);
    } else {
      this.list.appendChild(card);
    }
    this.list.scrollTop = this.list.scrollHeight;
    // On agent.complete, wrap current events in a group
    if (event.kind === 'agent.complete') {
      this._wrapCurrentGroup(event);
    }
  },

  _renderEvent(event) {
    const details = document.createElement('details');
    const kind = (event.kind || 'unknown').replace(/^agent\./, '');
    details.className = 'timeline-event kind-' + kind;
    const summary = document.createElement('summary');
    summary.className = 'event-summary';
    summary.textContent = this._summaryFor(event);
    // Time relative to previous event, or absolute
    const timeSpan = document.createElement('span');
    timeSpan.className = 'event-time';
    timeSpan.textContent = this._formatTime(event.timestamp);
    summary.appendChild(timeSpan);
    details.appendChild(summary);
    // Expanded payload
    const payloadDiv = document.createElement('pre');
    payloadDiv.style.cssText = 'font-size:11px;margin:4px 0 0;padding:4px 8px;border-radius:6px;background:rgba(0,0,0,0.1);max-height:200px;overflow-y:auto;white-space:pre-wrap;';
    payloadDiv.textContent = JSON.stringify(event.payload || {}, null, 2);
    details.appendChild(payloadDiv);
    return details;
  },

  _summaryFor(event) {
    const p = event.payload || {};
    const kind = event.kind || '';
    if (kind.includes('thinking'))  return 'Thinking: ' + (p.summary || '(thinking)');
    if (kind.includes('tool_call')) return 'Tool: ' + (p.tool || '?') + (p.status ? ' [' + p.status + ']' : '');
    if (kind.includes('partial_render')) return 'Partial render' + (p.target_anchor ? ' (target: ' + p.target_anchor + ')' : '');
    if (kind.includes('decision')) return 'Decision: ' + (p.choice || '?');
    if (kind.includes('render'))   return 'Rendered (' + (p.html_size || '?') + ' bytes)';
    if (kind.includes('complete')) return 'Done' + (p.summary ? ': ' + p.summary : '');
    if (kind.includes('error'))    return 'Error: ' + (p.message || '?');
    if (kind.includes('user.intent')) return 'User: ' + ((event.payload?.intent || event.payload)?.op || '?').toString();
    if (kind.includes('session_start')) return 'Session started';
    if (kind.includes('session_end'))   return 'Session ended';
    return kind + (p.summary ? ': ' + p.summary : '');
  },

  _formatTime(ts) {
    if (!ts) return '';
    if (this._lastTs) {
      try {
        const delta = Math.round((new Date(ts) - new Date(this._lastTs)) / 1000);
        this._lastTs = ts;
        return delta > 60 ? Math.floor(delta/60) + 'm' : delta + 's';
      } catch { this._lastTs = ts; return ''; }
    }
    this._lastTs = ts;
    try { return new Date(ts).toLocaleTimeString(); } catch { return ''; }
  },

  _startNewGroup() {
    this._lastTs = null;
  },

  _wrapCurrentGroup(completeEvent) {
    // Gather all non-details elements or loose cards since the last separator
    const recent = [];
    let el = this.list.lastElementChild;
    while (el && !el.classList.contains('timeline-group-separator')) {
      if (!el.classList.contains('timeline-group')) recent.unshift(el);
      el = el.previousElementSibling;
    }
    if (recent.length === 0) return;
    const group = document.createElement('details');
    group.className = 'timeline-group';
    group.setAttribute('open', '');
    const gSummary = document.createElement('summary');
    gSummary.style.cssText = 'font-size:12px;font-weight:500;padding:4px 0;cursor:pointer;color:var(--muted,#888);';
    gSummary.textContent = 'Completed  ·  ' + recent.length + ' step(s)';
    group.appendChild(gSummary);
    const body = document.createElement('div');
    body.className = 'group-body';
    recent.forEach(c => { c.remove(); body.appendChild(c); });
    group.appendChild(body);
    this.list.appendChild(group);
    this._currentGroup = group;
  }
};

// ────────────────────────────────────────────────────────────────────
// HistoryPanel — version history with rollback
// ────────────────────────────────────────────────────────────────────

window.HistoryPanel = {
  MAX_ENTRIES: 50,
  entries: [],
  fileId: null,

  init(anchor) {
    this.anchor = anchor;
    this._loadFromStorage();
    this._render();
  },

  setFile(file) {
    this.fileId = file?.id || null;
    this.entries = Array.isArray(file?.history) ? file.history.slice() : [];
    this._render();
  },

  save(html, anchorCount) {
    const entry = {
      id: 'hist_' + Date.now().toString(36),
      timestamp: new Date().toISOString(),
      anchorCount,
      html,
      summary: anchorCount + ' anchors, ' + html.length + ' bytes'
    };
    this.entries.unshift(entry);
    if (this.entries.length > this.MAX_ENTRIES) this.entries.pop();
    this._saveToStorage();
    this._saveToServer(entry);
    this._render();
  },

  restore(entryId) {
    const entry = this.entries.find(e => e.id === entryId);
    if (!entry || !this.anchor) return;
    this.anchor.currentHtml = entry.html;
    this.anchor.container.innerHTML = entry.html;
    this.anchor.injectHandles();
    this.anchor.infoEl.textContent = entry.anchorCount + ' anchors (restored)';
    this.anchor.toast('Restored: ' + entry.summary);
  },

  _render() {
    const root = document.querySelector('details[data-group="history"] .group-list');
    const countEl = document.querySelector('details[data-group="history"] .group-count');
    if (!root) return;
    root.innerHTML = '';
    this.entries.forEach(entry => {
      const row = document.createElement('div');
      row.className = 'history-entry';
      const meta = document.createElement('div');
      meta.className = 'history-meta';
      const time = document.createElement('span');
      time.className = 'history-time';
      try { time.textContent = new Date(entry.timestamp).toLocaleString(); } catch { time.textContent = entry.timestamp; }
      const summary = document.createElement('span');
      summary.className = 'history-summary';
      summary.textContent = entry.summary;
      meta.appendChild(time);
      meta.appendChild(summary);
      const restoreBtn = document.createElement('button');
      restoreBtn.className = 'btn btn--ghost btn--sm';
      restoreBtn.textContent = 'Restore';
      restoreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.restore(entry.id);
      });
      row.appendChild(meta);
      row.appendChild(restoreBtn);
      // Click row to preview (tooltip style — just restore for now)
      row.addEventListener('click', () => this.restore(entry.id));
      row.style.cursor = 'pointer';
      root.appendChild(row);
    });
    if (countEl) countEl.textContent = this.entries.length;
  },

  _loadFromStorage() {
    try {
      const key = this.fileId ? 'anchor.history.' + this.fileId : 'anchor.history';
      const raw = localStorage.getItem(key);
      if (raw) this.entries = JSON.parse(raw);
    } catch { /* ignore */ }
  },

  _saveToStorage() {
    try {
      // Don't store full HTML in localStorage (size limits); keep last 20
      const toSave = this.entries.slice(0, 20);
      const key = this.fileId ? 'anchor.history.' + this.fileId : 'anchor.history';
      localStorage.setItem(key, JSON.stringify(toSave));
    } catch (e) {
      // If quota exceeded, trim further
      try {
        const slim = this.entries.slice(0, 5).map(e => ({ ...e, html: e.html.substring(0, 5000) }));
        const key = this.fileId ? 'anchor.history.' + this.fileId : 'anchor.history';
        localStorage.setItem(key, JSON.stringify(slim));
      } catch { /* give up */ }
    }
  },

  _saveToServer(entry) {
    if (!this.fileId) return;
    fetch('/workspace/file/' + encodeURIComponent(this.fileId) + '/history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry)
    }).catch(() => {});
  }
};

// ────────────────────────────────────────────────────────────────────
// Inbox Panel
// ────────────────────────────────────────────────────────────────────

const InboxPanel = {
  _panel: null,
  _list: null,
  _activeDomain: '',
  _items: [],

  init() {
    this._panel = document.getElementById('anchor-inbox-panel');
    this._list  = document.getElementById('inbox-list');
    if (!this._panel) return;

    // tab clicks
    document.getElementById('inbox-domain-tabs').addEventListener('click', (e) => {
      const tab = e.target.closest('.inbox-tab');
      if (!tab) return;
      document.querySelectorAll('.inbox-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      this._activeDomain = tab.dataset.domain || '';
      this._renderList();
    });

    // read-all
    this._panel.querySelector('.inbox-read-all').addEventListener('click', () => {
      fetch('/inbox/read-all', { method: 'POST' }).then(() => {
        this._items.forEach(it => { it.read = true; });
        this._renderList();
        this.applyServerCounts({ market: 0, position: 0, target: 0, sentiment: 0, total: 0 });
      }).catch(() => {});
    });

    // item click → mark read + toggle inline detail
    this._list.addEventListener('click', (e) => {
      if (e.target.closest('.inbox-item-detail')) return;
      const item = e.target.closest('.inbox-item');
      if (!item) return;
      const id = item.dataset.id;
      const domain = item.dataset.domain;
      const wasExpanded = item.classList.contains('inbox-item--expanded');
      fetch('/inbox/' + id + '/read', { method: 'POST' }).catch(() => {});
      const found = this._items.find(it => it.id === id);
      if (found) { found.read = true; }
      this._renderList();
      if (!wasExpanded) {
        const freshItem = this._list.querySelector('[data-id="' + CSS.escape(id) + '"]');
        if (freshItem && found) {
          freshItem.classList.add('inbox-item--expanded');
          const detail = document.createElement('div');
          detail.className = 'inbox-item-detail';
          const ts = found.timestamp ? new Date(found.timestamp).toLocaleString('zh-CN') : '';
          const payloadStr = found.payload ? JSON.stringify(found.payload, null, 2) : '(no payload)';
          detail.innerHTML =
            `<div class="inbox-detail-meta">${_escHtml(found.source || '')} · ${_escHtml(ts)}</div>` +
            `<pre class="inbox-detail-payload">${_escHtml(payloadStr)}</pre>` +
            (domain ? `<button class="btn btn--sm btn--ghost inbox-detail-nav" data-domain="${_escHtml(domain)}">查看详情页 →</button>` : '');
          detail.querySelector('.inbox-detail-nav')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            _openDomain(domain);
          });
          freshItem.appendChild(detail);
        }
      }
    });

    this._fetchCounts();
    this._fetchItems();
  },

  applyServerCounts(counts) {
    const total = counts.total || 0;
    const badge = document.getElementById('inbox-trigger-badge');
    if (badge) {
      badge.textContent = total;
      badge.hidden = total === 0;
    }
    ['market', 'position', 'target', 'sentiment'].forEach(d => {
      const el = document.getElementById('itab-' + d);
      if (el) {
        const n = counts[d] || 0;
        el.textContent = n > 0 ? n : '';
      }
      const domBadge = document.getElementById('badge-' + d);
      if (domBadge) {
        const n = counts[d] || 0;
        domBadge.textContent = n;
        domBadge.hidden = n === 0;
      }
    });
    if (total > 0) this._fetchItems();
  },

  _fetchCounts() {
    fetch('/inbox/counts').then(r => r.json()).then(counts => {
      this.applyServerCounts(counts);
    }).catch(() => {});
  },

  _fetchItems() {
    const url = this._activeDomain ? '/inbox?domain=' + this._activeDomain : '/inbox';
    fetch(url).then(r => r.json()).then(data => {
      this._items = data.items || data || [];
      this._renderList();
    }).catch(() => {});
  },

  _renderList() {
    if (!this._list) return;
    const filtered = this._activeDomain
      ? this._items.filter(it => it.domain === this._activeDomain)
      : this._items;

    if (filtered.length === 0) {
      this._list.innerHTML = '<div class="inbox-empty">暂无消息</div>';
      return;
    }

    this._list.innerHTML = filtered.map(it => {
      const readCls = it.read ? 'inbox-item--read' : 'inbox-item--unread';
      const time = it.ts ? new Date(it.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
      return `<div class="inbox-item ${readCls}" data-id="${_escHtml(it.id)}" data-domain="${_escHtml(it.domain || '')}">
        <div class="inbox-item-header">
          <span class="inbox-item-dot"></span>
          <span class="inbox-item-title">${_escHtml(it.title)}</span>
          <span class="inbox-item-time">${time}</span>
        </div>
        ${it.summary ? `<div class="inbox-item-summary">${_escHtml(it.summary)}</div>` : ''}
        <div class="inbox-item-source">${_escHtml(it.source || '')}</div>
      </div>`;
    }).join('');
  }
};

// ────────────────────────────────────────────────────────────────────
// Domain card wiring
// ────────────────────────────────────────────────────────────────────

function _initDomainCards() {
  document.querySelectorAll('.home-domain-card').forEach(card => {
    card.addEventListener('click', () => {
      const domain = card.dataset.domain;
      if (domain) _openDomain(domain);
    });
  });
}

function _openDomain(domain) {
  if (window.Anchor && typeof Anchor._navigateToRoute === 'function') {
    Anchor._navigateToRoute(domain);
    return;
  }
  window.location.hash = domain;
}

function _escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  Anchor.init();
  InboxPanel.init();
  _initDomainCards();
});
