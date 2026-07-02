// Harness ¡ª Loom System Architecture Dashboard
// Self-mounts on [data-anc="harness-summary"] via MutationObserver.
// Fetches from Brain APIs on the same origin.
// Shows: agent states, hand configs, runtime bindings, adapter registry, system health.

(function () {
  'use strict';

  var BRAIN = 'http://127.0.0.1:3002';
  var ATTR = 'data-hs-mounted';

  // ©¤©¤ helpers ©¤©¤

  function h(s) { return (s == null ? '' : String(s)).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  function pill(cls, txt) { return '<span class="anc-pill ' + cls + '" style="font-size:10px">' + h(txt) + '</span>'; }

  function dot(cls) { return '<span class="hs-dot hs-dot--' + cls + '"></span>'; }

  function fmtTs(iso) {
    if (!iso) return '¡ª';
    try {
      var d = new Date(iso);
      return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) + ' ' +
             d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    } catch (_) { return iso.slice(0, 19); }
  }

  function capsList(arr) {
    if (!Array.isArray(arr) || !arr.length) return '<span style="color:var(--ink-3);font-size:11px">none</span>';
    return arr.slice(0, 6).map(function (c) {
      return '<span class="hs-cap-tag">' + h(c) + '</span>';
    }).join('') + (arr.length > 6 ? '<span class="hs-cap-tag">+' + (arr.length - 6) + '</span>' : '');
  }

  // ©¤©¤ render sections ©¤©¤

  function renderStatusBar(data) {
    var health = data.health || {};
    var ok = health.ok;
    var hands = health.hands || [];
    var adapters = (health.adapters || []);
    var mounted = health.mounted || {};
    var mCount = Object.keys(mounted).length;

    return (
      '<div class="hs-status-bar">' +
      '<div class="hs-status-item">' + dot(ok ? 'ok' : 'err') +
      '<span><strong>Brain</strong> ' + (ok ? 'healthy' : 'unreachable') + '</span></div>' +
      '<div class="hs-status-item">' +
      '<span style="font-size:11px;color:var(--ink-3)">' + hands.length + ' hands</span>' +
      '<span style="font-size:11px;color:var(--ink-3)">' + adapters.length + ' adapters</span>' +
      (mCount > 0 ? '<span style="font-size:11px;color:var(--ink-3)">' + mCount + ' mounted</span>' : '') +
      '</div>' +
      '</div>'
    );
  }

  function renderHandTable(handProfiles) {
    if (!handProfiles.length) return '<p class="hs-empty">No hands registered.</p>';

    var desc = {
      market:    'Market intelligence ¡ª regime detection, macro signals, sector rotation',
      sentiment: 'Sentiment tracking ¡ª social media, news sentiment, Fear & Greed index',
      target:    'Target thesis ¡ª security analysis, valuation models, debate engine',
      position:  'Portfolio management ¡ª risk analysis, position sizing, trade review',
      canvas:    'Canvas collaboration ¡ª coordinate multi-hand workflows and patches',
    };

    var rows = handProfiles.map(function (p) {
      var cfg = p.config || {};
      var provider = cfg.provider || '¡ª';
      var model = cfg.model || '¡ª';
      var runtime = p.effective_runtime || p.declared_runtime || '¡ª';
      var mounted = p.mounted_adapter ? pill('anc-pill--done', 'mounted: ' + p.mounted_adapter) : '';
      var handDesc = desc[p.hand_id] || '';

      return (
        '<tr>' +
        '<td class="hs-td-name"><div class="hs-hand-label">' + h(p.label || p.hand_id) + '</div>' +
        '<div class="hs-hand-desc">' + h(handDesc) + '</div></td>' +
        '<td>' + pill('anc-pill--gen', runtime) + '</td>' +
        '<td>' + (provider !== '¡ª' ? pill('anc-pill--review', provider) : '<span style="color:var(--ink-3);font-size:11px">inherited</span>') + '</td>' +
        '<td style="max-width:140px;font-size:11px;color:var(--ink-2)">' + h(model) + '</td>' +
        '<td>' + capsList(p.capabilities || []) + '</td>' +
        '<td>' + (mounted || '<span style="color:var(--ink-3);font-size:11px">¡ª</span>') + '</td>' +
        '<td>' + (p.health === false ? dot('err') : dot('ok')) + '</td>' +
        '</tr>'
      );
    }).join('');

    return (
      '<table class="hs-table">' +
      '<thead><tr>' +
      '<th>Hand</th><th>Runtime</th><th>Provider</th><th>Model</th><th>Capabilities</th><th>Mount</th><th>Status</th>' +
      '</tr></thead>' +
      '<tbody>' + rows + '</tbody>' +
      '</table>'
    );
  }

  function renderAdapterTable(adapters) {
    if (!adapters || !adapters.length) return '<p class="hs-empty">No adapters registered.</p>';

    var rows = adapters.map(function (a) {
      var transport = a.transport || '(inline)';
      var protocol = a.protocol || '¡ª';
      var codexBackend = a.codex_backend || '';
      var command = Array.isArray(a.command) && a.command.length ? a.command.join(' ') : '¡ª';
      var caps = a.capabilities || [];
      return (
        '<tr>' +
        '<td class="hs-td-name"><code>' + h(a.id) + '</code></td>' +
        '<td>' + pill('anc-pill--gen', transport) + '</td>' +
        '<td>' + h(protocol) + '</td>' +
        '<td style="max-width:200px;font-size:11px;font-family:monospace;color:var(--ink-2)">' + h(command) + '</td>' +
        '<td>' + capsList(caps) + '</td>' +
        '</tr>'
      );
    }).join('');

    return (
      '<table class="hs-table">' +
      '<thead><tr>' +
      '<th>Adapter ID</th><th>Transport</th><th>Protocol</th><th>Command</th><th>Capabilities</th>' +
      '</tr></thead>' +
      '<tbody>' + rows + '</tbody>' +
      '</table>'
    );
  }

  function renderRuntimeTable(handProfiles) {
    if (!handProfiles.length) return '';

    var rows = handProfiles.map(function (p) {
      return (
        '<tr>' +
        '<td class="hs-td-name">' + h(p.label || p.hand_id) + '</td>' +
        '<td><code>' + h(p.declared_runtime || '¡ª') + '</code></td>' +
        '<td><code>' + h(p.configured_runtime || 'default') + '</code></td>' +
        '<td><strong>' + h(p.effective_runtime || '¡ª') + '</strong></td>' +
        '<td>' + (p.mounted_adapter ? pill('anc-pill--done', p.mounted_adapter) : '<span style="color:var(--ink-3);font-size:11px">none</span>') + '</td>' +
        '</tr>'
      );
    }).join('');

    return (
      '<table class="hs-table">' +
      '<thead><tr>' +
      '<th>Hand</th><th>Declared</th><th>Configured</th><th>Effective</th><th>Mounted</th>' +
      '</tr></thead>' +
      '<tbody>' + rows + '</tbody>' +
      '</table>'
    );
  }

  function renderConfigSummary(config, handProfiles) {
    var def = (config && config.default) ? config.default : {};
    var defProvider = def.provider || '¡ª';
    var defModel = def.model || '¡ª';

    var handRows = handProfiles.map(function (p) {
      var cfg = p.config || {};
      var prov = cfg.provider || 'inherited';
      var model = cfg.model || 'inherited';
      return (
        '<tr>' +
        '<td class="hs-td-name">' + h(p.label || p.hand_id) + '</td>' +
        '<td>' + h(prov) + '</td>' +
        '<td style="font-family:monospace;font-size:11px">' + h(model) + '</td>' +
        '</tr>'
      );
    }).join('');

    return (
      '<div class="hs-config-block">' +
      '<div class="hs-config-default">' +
      '<span style="font-weight:600">Default: </span>' +
      pill('anc-pill--review', defProvider) +
      ' <code style="font-size:11px">' + h(defModel || '(default)') + '</code>' +
      '</div>' +
      '<table class="hs-table" style="margin-top:8px">' +
      '<thead><tr><th>Hand</th><th>Provider</th><th>Model</th></tr></thead>' +
      '<tbody>' + handRows + '</tbody>' +
      '</table>' +
      '</div>'
    );
  }

  function renderActivityFootprint(goalsData, fwData) {
    var goalCount = goalsData.count || 0;
    var epCount = (fwData && fwData.count) || 0;
    var fwRecords = (fwData && fwData.records) || [];
    var latestTs = fwRecords.length > 0 ? fmtTs(fwRecords[0].ts) : '¡ª';

    var goalRows = (goalsData.goals || []).slice(0, 5).map(function (g) {
      return (
        '<tr>' +
        '<td class="hs-td-name" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + h(g.title) + '">' + h(g.title) + '</td>' +
        '<td>' + pill('anc-pill--gen', g.goal_type) + '</td>' +
        '<td>' + h(g.status) + '</td>' +
        '<td>' + g.episode_count + '</td>' +
        '<td style="font-size:11px;color:var(--ink-3)">' + fmtTs(g.updated_at) + '</td>' +
        '</tr>'
      );
    }).join('');

    return (
      '<div class="hs-activity">' +
      '<div class="hs-activity-stats">' +
      '<span>' + goalCount + ' goals</span>' +
      '<span>' + epCount + ' episodes</span>' +
      '<span style="font-size:11px;color:var(--ink-3)">latest: ' + latestTs + '</span>' +
      '</div>' +
      (goalRows ? (
        '<table class="hs-table" style="margin-top:8px">' +
        '<thead><tr><th>Goal</th><th>Type</th><th>Status</th><th>EPS</th><th>Updated</th></tr></thead>' +
        '<tbody>' + goalRows + '</tbody></table>'
      ) : '') +
      '</div>'
    );
  }

  // ©¤©¤ CSS ©¤©¤

  var _CSS_INJECTED = false;
  function injectCSS() {
    if (_CSS_INJECTED) return;
    _CSS_INJECTED = true;
    var s = document.createElement('style');
    s.textContent =
      '.hs-status-bar{display:flex;align-items:center;gap:16px;padding:8px 0;border-bottom:1px solid var(--bg-3);margin-bottom:12px;flex-wrap:wrap}' +
      '.hs-status-item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-2)}' +
      '.hs-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;display:inline-block}' +
      '.hs-dot--ok{background:var(--success)}' +
      '.hs-dot--err{background:var(--warning)}' +
      '.hs-dot--load{background:var(--warning);animation:hs-pulse 1.2s infinite}' +
      '@keyframes hs-pulse{0%,100%{opacity:1}50%{opacity:.3}}' +
      '.hs-section{margin-bottom:18px}' +
      '.hs-section-title{font-size:13px;font-weight:700;color:var(--ink-1);margin-bottom:8px;display:flex;align-items:center;gap:6px}' +
      '.hs-section-title i{font-size:15px;color:var(--accent-iris)}' +
      '.hs-table{width:100%;border-collapse:collapse;font-size:12px}' +
      '.hs-table th{text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--ink-3);padding:6px 8px;border-bottom:1px solid var(--bg-3)}' +
      '.hs-table td{padding:7px 8px;border-bottom:1px solid var(--bg-3);vertical-align:middle}' +
      '.hs-table tbody tr:hover{background:var(--bg-3)}' +
      '.hs-td-name{font-weight:600;color:var(--ink-1)}' +
      '.hs-hand-label{font-size:13px;font-weight:700}' +
      '.hs-hand-desc{font-size:10px;color:var(--ink-3);font-weight:400;margin-top:1px;max-width:260px}' +
      '.hs-cap-tag{display:inline-block;background:var(--bg-3);color:var(--ink-2);font-size:10px;padding:1px 6px;border-radius:3px;margin:1px 2px}' +
      '.hs-empty{padding:12px 0;font-size:12px;color:var(--ink-3)}' +
      '.hs-config-block{font-size:12px}' +
      '.hs-config-default{display:flex;align-items:center;gap:8px;padding:6px 0}' +
      '.hs-activity-stats{display:flex;gap:12px;font-size:12px;color:var(--ink-2);padding:4px 0}' +
      '.hs-activity{border-top:1px solid var(--bg-3);padding-top:8px;margin-top:4px}' +
      '.hs-loading{padding:20px 0;font-size:12px;color:var(--ink-3);display:flex;align-items:center;gap:8px}';
    document.head.appendChild(s);
  }

  // ©¤©¤ main render ©¤©¤

  function render(el, data) {
    injectCSS();
    var handProfiles = data.handProfiles || [];
    var adapters = data.adapters || [];
    var config = data.config || {};
    var goalsData = data.goals || { goals: [], count: 0 };
    var fwData = data.flywheel || { records: [], count: 0 };

    el.innerHTML =
      renderStatusBar(data) +
      '<div class="hs-section">' +
      '<div class="hs-section-title"><i class="ph-bold ph-stack"></i> Agent Hands</div>' +
      renderHandTable(handProfiles) +
      '</div>' +
      '<div class="hs-section">' +
      '<div class="hs-section-title"><i class="ph-bold ph-plug"></i> Adapter Registry</div>' +
      renderAdapterTable(adapters) +
      '</div>' +
      '<div class="hs-section">' +
      '<div class="hs-section-title"><i class="ph-bold ph-arrows-left-right"></i> Runtime Resolution Chain</div>' +
      renderRuntimeTable(handProfiles) +
      '</div>' +
      '<div class="hs-section">' +
      '<div class="hs-section-title"><i class="ph-bold ph-gear-six"></i> Configuration</div>' +
      renderConfigSummary(config, handProfiles) +
      '</div>' +
      renderActivityFootprint(goalsData, fwData);

    el.setAttribute(ATTR, '1');
  }

  // ©¤©¤ fetch ©¤©¤

  async function loadData(el) {
    el.innerHTML = '<div class="hs-loading">' + dot('load') + ' Loading system architecture¡­</div>';
    el.setAttribute(ATTR, '1');

    try {
      // parallel: health, runtime-bindings, config, goals, flywheel, adapters
      var [hResp, rbResp, cfgResp, goalResp, fwResp, adaptResp] = await Promise.all([
        fetch(BRAIN + '/health'),
        fetch(BRAIN + '/hands/runtime-bindings'),
        fetch(BRAIN + '/config'),
        fetch(BRAIN + '/goals?status=all'),
        fetch(BRAIN + '/flywheel?limit=5'),
        fetch(BRAIN + '/adapters')
      ]);

      var health = hResp.ok ? await hResp.json() : { ok: false };
      var rbData = rbResp.ok ? await rbResp.json() : { hands: [], bindings: {} };
      var config = cfgResp.ok ? await cfgResp.json() : {};
      var goals = goalResp.ok ? await goalResp.json() : { goals: [], count: 0 };
      var fwData = fwResp.ok ? await fwResp.json() : { records: [], count: 0 };
      var adaptersData = adaptResp.ok ? await adaptResp.json() : { adapters: [] };

      var hands = rbData.hands || [];
      var adapters = adaptersData.adapters || [];

      // Fetch per-hand config + mount in parallel
      var handProfiles = await Promise.all(hands.map(async function (h) {
        var p = {
          hand_id: h.hand_id,
          label: h.label || h.hand_id,
          declared_runtime: h.declared_runtime || '',
          configured_runtime: h.configured_runtime || '',
          effective_runtime: h.effective_runtime || '',
          mounted_adapter: h.mounted_runtime || '',
          capabilities: [],
          config: {},
          health: true,
        };
        try {
          var [cResp, mResp] = await Promise.all([
            fetch(BRAIN + '/hand/' + h.hand_id + '/config'),
            fetch(BRAIN + '/hand/' + h.hand_id + '/mount')
          ]);
          if (cResp.ok) { var cd = await cResp.json(); p.config = cd.config || {}; }
          if (mResp.ok) {
            var md = await mResp.json();
            if (md.mounted) p.mounted_adapter = md.adapter_id || 'yes';
          }
        } catch (_) { p.health = false; }

        // Capabilities from matched adapter or health data
        var matchedAdapter = adapters.find(function (a) { return a.id === p.effective_runtime; });
        p.capabilities = (matchedAdapter && matchedAdapter.capabilities) || [];

        return p;
      }));

      render(el, {
        health: health,
        handProfiles: handProfiles,
        adapters: adapters,
        config: config,
        goals: goals,
        flywheel: fwData,
      });

    } catch (e) {
      el.innerHTML =
        '<div class="anc-pill-row"><span class="anc-pill anc-pill--warn">Harness offline</span></div>' +
        '<p style="font-size:11px;color:var(--ink-3);padding:8px 0">' + h(e.message || 'error') + '</p>';
      el.setAttribute(ATTR, '1');
    }
  }

  function mount(el) {
    if (el.hasAttribute(ATTR)) return;
    el.setAttribute(ATTR, '1');
    injectCSS();
    el.innerHTML = '<div class="hs-loading">' + dot('load') + ' Loading system architecture¡­</div>';
    loadData(el);
  }

  function mountAll(root) {
    (root || document).querySelectorAll(
      '[data-anc="harness-summary"]:not([' + ATTR + '])'
    ).forEach(mount);
  }

  var observer = new MutationObserver(function () { mountAll(); });
  observer.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  } else {
    mountAll();
  }

  window.HarnessSummary = { refresh: function (el) { el.removeAttribute(ATTR); mount(el); }, mountAll: mountAll };
})();
