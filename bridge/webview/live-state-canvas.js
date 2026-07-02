// Live State Canvas — self-mounts on [data-anc="live-state-canvas"] via MutationObserver
// Shows current environment states, bottlenecks, evidence chains, and pending repairs.
// Uses GET /episodes/{episode_id}/workspace
(function () {
  const BRAIN_URL = 'http://127.0.0.1:3002';
  const ATTR = 'data-lsc-mounted';

  function h(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

  var STATE_LABELS = {
    active: 'Active', contested: 'Contested', stale: 'Stale',
    verifying: 'Verifying', resolved: 'Resolved', retired: 'Retired'
  };

  var STATE_PILLS = {
    active: 'anc-pill--active', contested: 'anc-pill--edit', stale: 'anc-pill--warn',
    verifying: 'anc-pill--review', resolved: 'anc-pill--done', retired: 'anc-pill--lock'
  };

  function render(el, data) {
    var states = (data && data.states) ? data.states : [];
    var bottlenecks = (data && data.bottlenecks) ? data.bottlenecks : [];
    var queries = (data && data.visual_queries) ? data.visual_queries : [];
    var diagnostics = data && data.diagnostics ? data.diagnostics : {};

    var rows = states.slice(0, 8).map(function (s) {
      var pillClass = STATE_PILLS[s.status] || 'anc-pill--draft';
      return '<div class="lsc-state" data-state-id="' + h(s.state_id) + '" style="padding:8px 0;border-bottom:1px solid var(--surface-2,rgba(0,0,0,.06))">' +
        '<div class="anc-pill-row" style="margin-bottom:4px"><span class="anc-pill ' + pillClass + '">' + h(STATE_LABELS[s.status] || s.status) + '</span></div>' +
        '<div style="font-size:13px;color:var(--ink)">' + h((s.summary || s.last_transition || {}).summary || s.state_id) + '</div>' +
        '</div>';
    }).join('');

    var bnHtml = '';
    if (bottlenecks.length > 0) {
      bnHtml = '<div style="margin-top:8px;font-size:12px;color:var(--ink-2)">' +
        '<i class="ph-bold ph-warning-circle" style="color:var(--amber-5)"></i> ' +
        bottlenecks.length + ' bottleneck(s) detected</div>';
    }

    var qHtml = '';
    if (queries.length > 0) {
      qHtml = '<div style="margin-top:6px;font-size:12px;color:var(--ink-2)">' +
        '<i class="ph-bold ph-question" style="color:var(--accent)"></i> ' +
        queries.length + ' checkpoint(s) available</div>';
    }

    el.innerHTML =
      '<div class="anc-pill-row"><span class="anc-pill anc-pill--gen">Live State</span></div>' +
      '<div style="margin-top:4px;font-size:11px;color:var(--ink-3)">' +
      diagnostics.total_states + ' states, ' + rows.length + ' shown' +
      '</div>' +
      rows +
      bnHtml +
      qHtml +
      '<div style="margin-top:8px;font-size:10px;color:var(--ink-3);text-align:right">episode workspace</div>';

    el.setAttribute(ATTR, '1');
  }

  function loadData(el) {
    var epid = el.getAttribute('data-episode-id') || '';
    if (!epid) {
      el.innerHTML = '<div class="anc-pill-row"><span class="anc-pill anc-pill--draft">No Episode</span></div>';
      el.setAttribute(ATTR, '1');
      return;
    }
    fetch(BRAIN_URL + '/episodes/' + encodeURIComponent(epid) + '/workspace')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) { render(el, data); })
      .catch(function () {
        el.innerHTML =
          '<div class="anc-pill-row"><span class="anc-pill anc-pill--warn">States Offline</span></div>' +
          '<p style="font-size:11px;color:var(--ink-3)">' + h('workspace unavailable') + '</p>';
        el.setAttribute(ATTR, '1');
      });
  }

  function mount(el) {
    if (el.hasAttribute(ATTR)) return;
    el.setAttribute(ATTR, '1');
    el.innerHTML =
      '<div class="anc-pill-row"><span class="anc-pill anc-pill--gen">Live State</span></div>' +
      '<p style="font-size:11px;color:var(--ink-3)">Loading...</p>';
    loadData(el);
  }

  function mountAll(root) {
    (root || document).querySelectorAll(
      '[data-anc="live-state-canvas"]:not([' + ATTR + '])'
    ).forEach(mount);
  }

  var observer = new MutationObserver(function () { mountAll(); });
  observer.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  } else {
    mountAll();
  }

  window.LiveStateCanvas = { refresh: function (el) { el.removeAttribute(ATTR); mount(el); }, mountAll: mountAll };
})();
