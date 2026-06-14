/* loom-detail-overlay.js: generic drill-down overlay for Loom HTML. */
(function () {
  'use strict';

  // ── Density category system (semantic, no L-prefix) ─────────────────────
  var DENSITY_CATEGORIES = {
    analysis: { label: '分析', types: ['summary', 'analysis', 'gaps'], defaultOn: true },
    evidence: { label: '证据', types: ['evidence'], defaultOn: true },
    raw:      { label: '原始', types: ['raw_source', 'raw_item'], defaultOn: false },
  };

  var _density = {
    activeCategories: (function () {
      try {
        var saved = typeof localStorage !== 'undefined' && localStorage.getItem('loom.density.categories');
        if (saved) return JSON.parse(saved);
      } catch (_) {}
      var def = {};
      for (var k in DENSITY_CATEGORIES) def[k] = DENSITY_CATEGORIES[k].defaultOn;
      return def;
    })(),
    overrides: JSON.parse((typeof localStorage !== 'undefined' && localStorage.getItem('loom.density.overrides')) || '{}'),
    customLayers: JSON.parse((typeof localStorage !== 'undefined' && localStorage.getItem('loom.density.custom_layers')) || '[]'),
  };

  var LoomDensity = {
    registerLayer: function (cfg) {
      var existing = _density.customLayers.find(function (l) { return l.layer_type === cfg.layer_type; });
      if (!existing) {
        _density.customLayers.push(cfg);
        if (typeof localStorage !== 'undefined') localStorage.setItem('loom.density.custom_layers', JSON.stringify(_density.customLayers));
      }
    },
    toggleCategory: function (name) {
      if (name in DENSITY_CATEGORIES) {
        _density.activeCategories[name] = !_density.activeCategories[name];
        if (typeof localStorage !== 'undefined') localStorage.setItem('loom.density.categories', JSON.stringify(_density.activeCategories));
      }
    },
    toggleOverride: function (layer_type, visible) {
      _density.overrides[layer_type] = visible;
      if (typeof localStorage !== 'undefined') localStorage.setItem('loom.density.overrides', JSON.stringify(_density.overrides));
    },
    isVisible: function (layer_type) {
      if (!layer_type) return true;
      if (layer_type in _density.overrides) return _density.overrides[layer_type];
      var custom = _density.customLayers.find(function (l) { return l.layer_type === layer_type; });
      if (custom) {
        var cat = custom.default_category || 'analysis';
        return _density.activeCategories[cat] === true;
      }
      for (var name in DENSITY_CATEGORIES) {
        if (DENSITY_CATEGORIES[name].types.indexOf(layer_type) !== -1) {
          return _density.activeCategories[name] === true;
        }
      }
      return true;
    },
  };
  if (typeof window !== 'undefined') window.LoomDensity = LoomDensity;

  var overlay = null;
  var titleEl = null;
  var subtitleEl = null;
  var pillsEl = null;
  var tabsEl = null;
  var bodyEl = null;
  var rootEl = null;
  var options = {
    clickToOpen: false,
    hoverToOpen: true,
    requireCtrlForHover: true,
    hoverDelay: 180
  };
  var hoverTimer = null;
  var hoverTarget = null;
  var activeTarget = null;
  var closeTimer = null;
  var dockRaf = null;

  var INTERACTIVE_SELECTOR = [
    'a', 'button', 'input', 'textarea', 'select', 'summary',
    '.anc-handle', '.anc-handle-popup', '.anc-op-btn', '.anc-collapse-caret',
    '.card-handles', '.resize-handle', '.rotate-handle',
    '.prompt-chip', '.chip-remove'
  ].join(',');

  var KNOWN_SECTIONS = [
    { cls: 'anc-detail-section--content', label: 'Detail' },
    { cls: 'anc-detail-section--sources', label: 'Sources' },
    { cls: 'anc-detail-section--hand-eval', label: 'Hand Eval' },
    { cls: 'anc-detail-section--brain-eval', label: 'Brain Eval' }
  ];

  function _filterSectionsByDensity(overlayEl) {
    overlayEl.querySelectorAll('[data-layer-type]').forEach(function (sec) {
      var lt = sec.getAttribute('data-layer-type');
      var visible = LoomDensity.isVisible(lt);
      sec.style.display = visible ? '' : 'none';
      var tabId = sec.dataset.panel;
      if (tabId) {
        var tab = overlayEl.querySelector('.loom-detail-tab[data-tab="' + tabId + '"]');
        if (tab) tab.style.display = visible ? '' : 'none';
      }
    });
    // If current active tab is hidden, activate first visible tab
    var activeTab = overlayEl.querySelector('.loom-detail-tab--active');
    if (activeTab && activeTab.style.display === 'none') {
      var firstVisible = overlayEl.querySelector('.loom-detail-tab:not([style*="display: none"]),.loom-detail-tab:not([style*="display:none"])');
      if (firstVisible) {
        var tabId = firstVisible.dataset.tab;
        if (tabId) activateTab(tabId);
      }
    }
  }

  function _renderDensityBar(overlayEl) {
    var existing = overlayEl.querySelector('.loom-density-bar');
    if (existing) existing.remove();

    var bar = document.createElement('div');
    bar.className = 'loom-density-bar';
    bar.style.cssText = (
      'display:flex;align-items:center;gap:7px;padding:10px 18px 4px;' +
      'flex-wrap:wrap;background:transparent'
    );

    Object.keys(DENSITY_CATEGORIES).forEach(function (name) {
      var cat = DENSITY_CATEGORIES[name];
      var active = _density.activeCategories[name] === true;
      var btn = document.createElement('button');
      btn.textContent = cat.label;
      btn.type = 'button';
      btn.style.cssText = (
        'padding:5px 11px;border-radius:999px;border:1px solid rgba(255,255,255,.48);' +
        'font-size:11px;font-weight:750;cursor:pointer;backdrop-filter:blur(14px);' +
        'background:' + (active ? 'rgba(122,90,248,.24)' : 'rgba(255,255,255,.22)') + ';' +
        'color:' + (active ? 'var(--accent-iris,#6f4ef6)' : 'var(--fg-2,#555)')
      );
      function selectCategory() {
        if (_density.activeCategories[name] === true) return;
        LoomDensity.toggleCategory(name);
        _renderDensityBar(overlayEl);
        _filterSectionsByDensity(overlayEl);
      }
      btn.addEventListener('mouseenter', selectCategory);
      btn.addEventListener('focus', selectCategory);
      bar.appendChild(btn);
    });

    var header = overlayEl.querySelector('.loom-detail-header');
    if (header && header.nextSibling) {
      overlayEl.querySelector('.loom-detail-card').insertBefore(bar, header.nextSibling);
    } else {
      overlayEl.querySelector('.loom-detail-card').appendChild(bar);
    }
  }

  function init(config) {
    config = config || {};
    options.clickToOpen = config.clickToOpen !== undefined ? !!config.clickToOpen : options.clickToOpen;
    options.hoverToOpen = config.hoverToOpen !== undefined ? !!config.hoverToOpen : options.hoverToOpen;
    options.requireCtrlForHover = config.requireCtrlForHover !== undefined ? !!config.requireCtrlForHover : options.requireCtrlForHover;
    options.hoverDelay = Number(config.hoverDelay || options.hoverDelay);
    rootEl = config.root || rootEl || document;

    ensureOverlay();
    bindRoot(rootEl);
    refresh(rootEl);
  }

  function bindRoot(root) {
    if (!root || root.__loomDetailBound) return;
    root.__loomDetailBound = true;

    root.addEventListener('click', function (event) {
      if (!options.clickToOpen || shouldIgnore(event)) return;
      var target = findDetailTarget(event.target);
      if (!target) return;
      event.preventDefault();
      event.stopPropagation();
      open(target);
    });

    root.addEventListener('mouseover', function (event) {
      if (!canHoverOpen(event) || shouldIgnore(event)) return;
      var target = findDetailTarget(event.target);
      if (!target || target.contains(event.relatedTarget)) return;
      clearHover();
      hoverTarget = target;
      target.classList.add('loom-detail-hover');
      hoverTimer = window.setTimeout(function () {
        if (hoverTarget === target) open(target);
      }, options.hoverDelay);
    });

    root.addEventListener('mouseout', function (event) {
      var target = findDetailTarget(event.target);
      if (!target || target.contains(event.relatedTarget)) return;
      target.classList.remove('loom-detail-hover');
      clearHover();
      scheduleClose();
    });

    root.addEventListener('mousemove', function (event) {
      if (!canHoverOpen(event) || shouldIgnore(event)) return;
      var target = findDetailTarget(event.target);
      if (!target || hoverTarget === target || activeTarget === target) return;
      clearHover();
      hoverTarget = target;
      target.classList.add('loom-detail-hover');
      hoverTimer = window.setTimeout(function () {
        if (hoverTarget === target && canHoverOpen(event)) open(target);
      }, options.hoverDelay);
    });

    if (window.MutationObserver) {
      var observeTarget = root === document ? document.body : root;
      if (observeTarget && !observeTarget.__loomDetailObserver) {
        var refreshTimer = null;
        observeTarget.__loomDetailObserver = new MutationObserver(function () {
          if (refreshTimer) window.clearTimeout(refreshTimer);
          refreshTimer = window.setTimeout(function () { refresh(observeTarget); }, 60);
        });
        observeTarget.__loomDetailObserver.observe(observeTarget, { childList: true, subtree: true });
      }
    }
  }

  function refresh(root) {
    root = root || rootEl || document;
    var candidates = [];
    if (root.nodeType === 1 && isDetailTarget(root)) candidates.push(root);
    if (root.querySelectorAll) {
      root.querySelectorAll('[data-detail-root], [data-has-detail="true"], aside.anc-detail').forEach(function (el) {
        if (overlay && overlay.contains(el)) return;
        var target = el.matches('aside.anc-detail') ? el.closest('[data-anc], [data-detail-root]') : el;
        if (target && candidates.indexOf(target) === -1 && isDetailTarget(target)) candidates.push(target);
      });
    }
    candidates.forEach(markDetailTarget);
  }

  function ensureOverlay() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.id = 'loom-detail-overlay';
    overlay.innerHTML = [
      '<div class="loom-detail-backdrop"></div>',
      '<article class="loom-detail-card" role="dialog" aria-modal="true" aria-labelledby="loom-detail-title">',
      '  <header class="loom-detail-header">',
      '    <div>',
      '      <h2 id="loom-detail-title" class="loom-detail-title"></h2>',
      '      <div class="loom-detail-subtitle"></div>',
      '    </div>',
      '  </header>',
      '  <div class="loom-detail-pills"></div>',
      '  <nav class="loom-detail-tabs" role="tablist"></nav>',
      '  <div class="loom-detail-body"></div>',
      '</article>'
    ].join('');
    document.body.appendChild(overlay);

    titleEl = overlay.querySelector('.loom-detail-title');
    subtitleEl = overlay.querySelector('.loom-detail-subtitle');
    pillsEl = overlay.querySelector('.loom-detail-pills');
    tabsEl = overlay.querySelector('.loom-detail-tabs');
    bodyEl = overlay.querySelector('.loom-detail-body');

    var card = overlay.querySelector('.loom-detail-card');
    card.addEventListener('mouseenter', cancelClose);
    card.addEventListener('mouseleave', function () {
      resetDockTabs();
      scheduleClose();
    });
    document.addEventListener('mousemove', function (event) {
      if (!overlay.classList.contains('loom-detail--open')) return;
      if (options.requireCtrlForHover && !event.ctrlKey) {
        close();
        return;
      }
      if (isPointerInActiveArea(event)) {
        cancelClose();
      } else {
        scheduleClose();
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && overlay.classList.contains('loom-detail--open')) close();
    });
    document.addEventListener('keyup', function (event) {
      if (event.key === 'Control' && overlay.classList.contains('loom-detail--open')) close();
    });
  }

  function open(targetOrId, contentEl) {
    ensureOverlay();
    var target = contentEl || resolveTarget(targetOrId);
    if (!target) return false;

    clearHover();
    cancelClose();
    activeTarget = target;
    renderTarget(target, targetOrId);
    _renderDensityBar(overlay);
    _filterSectionsByDensity(overlay);
    centerCard();
    requestAnimationFrame(function () {
      overlay.classList.add('loom-detail--open');
    });
    return true;
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove('loom-detail--open');
    activeTarget = null;
    cancelClose();
  }

  function renderTarget(target, fallbackId) {
    tabsEl.innerHTML = '';
    bodyEl.innerHTML = '';

    var title = getTitle(target) || String(fallbackId || target.getAttribute('data-anc') || 'Detail');
    titleEl.textContent = title;
    subtitleEl.textContent = target.getAttribute('data-detail-subtitle') || target.getAttribute('data-anc') || '';

    var pillRow = target.querySelector('.anc-pill-row, .blog-card-tags');
    pillsEl.innerHTML = pillRow ? pillRow.innerHTML : '';
    pillsEl.insertAdjacentHTML('beforeend', renderAgentBadge(target));

    var sections = collectSections(target);
    if (!sections.length) {
      sections = collectFallbackSections(target);
    }

    sections.forEach(function (section, index) {
      addTab(section.id || ('section-' + index), section.label || ('Layer ' + (index + 1)), section.html || '', section.layerType || '');
    });

    var first = tabsEl.querySelector('.loom-detail-tab');
    if (first) activateTab(first.dataset.tab);
  }

  function collectSections(target) {
    var aside = target.matches && target.matches('aside.anc-detail') ? target : target.querySelector('aside.anc-detail');
    var sections = [];
    if (!aside) return sections;

    KNOWN_SECTIONS.forEach(function (def) {
      var section = aside.querySelector('.' + def.cls);
      if (section) sections.push(sectionFromElement(section, def.label));
    });

    aside.querySelectorAll('[data-detail-section], .anc-detail-section').forEach(function (section) {
      if (sections.some(function (item) { return item.source === section; })) return;
      sections.push(sectionFromElement(section));
    });

    if (!sections.some(function (item) { return item.id === 'agents'; })) {
      sections.push(ensureAgentSection(target, sections));
    }

    if (!sections.length) {
      sections.push({ id: 'detail', label: 'Detail', html: aside.innerHTML, source: aside });
    }
    return sections;
  }

  function collectFallbackSections(target) {
    var sections = [];
    var title = getTitle(target);
    var pillRow = target.querySelector('.anc-pill-row, .blog-card-tags');
    var firstText = target.querySelector('p, blockquote, .blog-card-summary, .insight-box');
    var overview = [
      title ? '<h3>' + escapeHtml(title) + '</h3>' : '',
      pillRow ? pillRow.outerHTML : '',
      firstText ? firstText.outerHTML : ''
    ].join('');

    if (overview.trim()) {
      sections.push({ id: 'overview', label: 'Overview', html: overview });
    }

    var support = Array.from(target.querySelectorAll('.anc-kpi-grid, table, ul, ol, .risk-list, .insight-box, blockquote'))
      .filter(function (el, index, arr) {
        if (el.closest('aside.anc-detail')) return false;
        return arr.findIndex(function (other) { return other !== el && other.contains(el); }) === -1;
      })
      .slice(0, 8)
      .map(function (el) { return el.outerHTML; })
      .join('');

    if (support.trim()) {
      sections.push({ id: 'support', label: 'Supporting Data', html: support });
    }

    sections.push(ensureAgentSection(target, sections));

    var clone = cloneSummary(target);
    sections.push({ id: 'full', label: 'Full Section', html: clone.innerHTML });
    return sections;
  }

  function inferAgentMeta(target) {
    var anchor = target.getAttribute('data-anc') || target.getAttribute('data-detail-root') || '';
    var domain = target.getAttribute('data-agent-domain') || anchor.split('.')[0] || 'workspace';
    var hand = target.getAttribute('data-agent-hand') || (domain && domain !== 'card' ? domain : 'loom-renderer');
    var executor = target.getAttribute('data-agent-executor') || hand;
    var role = target.getAttribute('data-agent-role') || '';
    var kind = target.getAttribute('data-agent-kind') || '';
    var roles = {
      market: 'Tracks market regime, macro signals, risk catalysts, and source-backed evidence.',
      position: 'Reviews portfolio exposure, concentration, P/L drivers, and position-level risk.',
      target: 'Assesses target-specific thesis, catalysts, triggers, and invalidation conditions.',
      sentiment: 'Reads sentiment, crowding, positioning tone, and contrarian risk.',
      'loom-renderer': 'Renders this card and exposes available detail layers for review.'
    };
    return {
      hand: hand,
      executor: executor,
      domain: domain,
      kind: kind,
      role: role || roles[hand] || roles[domain] || roles['loom-renderer']
    };
  }

  function ensureAgentSection(target, sections) {
    var meta = inferAgentMeta(target);
    var bits = [meta.executor, meta.domain, meta.kind].filter(Boolean).map(escapeHtml).join(' / ');
    var html = [
      '<h3>Hand Agent</h3>',
      '<p>Current card processing hand agent and its compact responsibility.</p>',
      '<ul class="anc-source-list">',
      '<li>',
      '<strong>' + escapeHtml(meta.hand) + '</strong>',
      bits ? '<small>' + bits + '</small>' : '',
      '<p>' + escapeHtml(meta.role) + '</p>',
      '</li>',
      '</ul>'
    ].join('');
    return {
      id: 'agents',
      label: 'Hand Agent',
      html: html,
      layerType: ''
    };
  }

  function renderAgentBadge(target) {
    var meta = inferAgentMeta(target);
    var bits = [meta.executor, meta.domain, meta.kind].filter(Boolean).join(' / ');
    return [
      '<span class="anc-tier-pill anc-tier-pill--b">Hand Agent: ' + escapeHtml(meta.hand) + '</span>',
      '<span class="anc-tier-pill anc-tier-pill--c">' + escapeHtml(bits || meta.domain) + '</span>',
      meta.role ? '<span class="anc-tier-pill anc-tier-pill--c">' + escapeHtml(meta.role) + '</span>' : ''
    ].join('');
  }

  function sectionFromElement(section, fallbackLabel) {
    var heading = section.querySelector('h1,h2,h3,h4');
    return {
      id: section.getAttribute('data-detail-section') || slug(fallbackLabel || (heading && heading.textContent) || 'detail'),
      label: section.getAttribute('data-detail-label') || fallbackLabel || cleanText(heading && heading.textContent) || 'Detail',
      html: section.innerHTML,
      source: section,
      layerType: section.getAttribute('data-layer-type') || '',
    };
  }

  function addTab(id, label, html, layerType) {
    var tab = document.createElement('button');
    tab.className = 'loom-detail-tab';
    tab.type = 'button';
    tab.dataset.tab = id;
    tab.textContent = label;
    if (layerType) tab.setAttribute('data-layer-type', layerType);
    tab.addEventListener('click', function () { activateTab(id); });
    tab.addEventListener('mouseenter', function () { activateTab(id); });
    tab.addEventListener('focus', function () { activateTab(id); });
    tab.addEventListener('mousemove', updateDockTabs);
    tab.addEventListener('mouseleave', resetDockTabs);
    tabsEl.appendChild(tab);

    var panel = document.createElement('section');
    panel.className = 'loom-detail-panel';
    panel.dataset.panel = id;
    if (layerType) panel.setAttribute('data-layer-type', layerType);
    panel.innerHTML = html;
    bodyEl.appendChild(panel);
  }

  function activateTab(id) {
    tabsEl.querySelectorAll('.loom-detail-tab').forEach(function (tab) {
      tab.classList.toggle('loom-detail-tab--active', tab.dataset.tab === id);
    });
    bodyEl.querySelectorAll('.loom-detail-panel').forEach(function (panel) {
      panel.classList.toggle('loom-detail-panel--active', panel.dataset.panel === id);
    });
  }

  function cloneSummary(target) {
    var clone = target.cloneNode(true);
    clone.querySelectorAll('.anc-handle, .anc-handle-popup, .card-handles, aside.anc-detail').forEach(function (el) {
      el.remove();
    });
    [
      'data-anc-x', 'data-anc-y', 'data-anc-w', 'data-anc-h',
      'data-anc-rot', 'data-anc-scale', 'data-anc-z'
    ].forEach(function (attr) { clone.removeAttribute(attr); });
    clone.style.cssText = '';
    return clone;
  }

  function findDetailTarget(start) {
    var el = start && start.nodeType === 1 ? start : start && start.parentElement;
    while (el && el !== document.body && el !== document.documentElement) {
      if (isDetailTarget(el)) return el;
      el = el.parentElement;
    }
    return null;
  }

  function isDetailTarget(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.closest('[data-detail-disabled="true"], .portfolio-hub')) return false;
    return el.hasAttribute('data-detail-root') ||
      el.getAttribute('data-has-detail') === 'true' ||
      !!el.querySelector('aside.anc-detail');
  }

  function markDetailTarget(el) {
    el.classList.add('loom-detail-drillable');
    if (window.getComputedStyle && getComputedStyle(el).position === 'static') {
      el.style.position = 'relative';
    }
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
    el.setAttribute('aria-haspopup', 'dialog');
  }

  function resolveTarget(targetOrId) {
    if (targetOrId && targetOrId.nodeType === 1) return targetOrId;
    if (!targetOrId) return null;
    var id = String(targetOrId).replace(/"/g, '\\"');
    return document.querySelector('[data-anc="' + id + '"], [data-detail-root="' + id + '"]');
  }

  function shouldIgnore(event) {
    if (!event || !event.target) return true;
    if (overlay && overlay.contains(event.target)) return true;
    return !!event.target.closest(INTERACTIVE_SELECTOR);
  }

  function clearHover() {
    if (hoverTimer) window.clearTimeout(hoverTimer);
    hoverTimer = null;
    if (hoverTarget) hoverTarget.classList.remove('loom-detail-hover');
    hoverTarget = null;
  }

  function canHoverOpen(event) {
    if (!options.hoverToOpen) return false;
    return !options.requireCtrlForHover || !!(event && event.ctrlKey);
  }

  function cancelClose() {
    if (closeTimer) window.clearTimeout(closeTimer);
    closeTimer = null;
  }

  function scheduleClose() {
    cancelClose();
    closeTimer = window.setTimeout(function () {
      if (!overlay || !overlay.classList.contains('loom-detail--open')) return;
      close();
    }, 360);
  }

  function isPointerInActiveArea(event) {
    if (!event || !event.target) return false;
    var card = overlay && overlay.querySelector('.loom-detail-card');
    if (card && card.contains(event.target)) return true;
    return !!(activeTarget && activeTarget.contains && activeTarget.contains(event.target));
  }

  function centerCard() {
    var card = overlay && overlay.querySelector('.loom-detail-card');
    if (!card) return;
    var vw = window.innerWidth || document.documentElement.clientWidth || 1200;
    var vh = window.innerHeight || document.documentElement.clientHeight || 800;
    var cardW = Math.min(920, Math.max(320, vw * 0.62));
    var cardH = Math.min(760, Math.max(360, vh * 0.78));
    var gutter = 18;
    var finalW = Math.min(cardW, vw - gutter * 2);
    var finalH = Math.min(cardH, vh - gutter * 2);
    var x = Math.max(gutter, (vw - finalW) / 2);
    var y = Math.max(gutter, (vh - finalH) / 2);
    overlay.style.setProperty('--loom-detail-x', Math.round(x) + 'px');
    overlay.style.setProperty('--loom-detail-y', Math.round(y) + 'px');
    overlay.style.setProperty('--loom-detail-w', Math.round(finalW) + 'px');
    overlay.style.setProperty('--loom-detail-max-h', Math.round(finalH) + 'px');
  }

  function updateDockTabs(event) {
    if (!tabsEl) return;
    var x = event.clientX;
    if (dockRaf) window.cancelAnimationFrame(dockRaf);
    dockRaf = window.requestAnimationFrame(function () {
      dockRaf = null;
      tabsEl.querySelectorAll('.loom-detail-tab').forEach(function (tab) {
        var rect = tab.getBoundingClientRect();
        var center = rect.left + rect.width / 2;
        var distance = Math.abs(x - center);
        var influence = Math.max(0, 1 - distance / 150);
        var scale = 1 + influence * 0.22;
        var lift = influence * -5;
        var glow = influence * 0.18;
        tab.style.setProperty('--dock-scale', scale.toFixed(3));
        tab.style.setProperty('--dock-lift', lift.toFixed(1) + 'px');
        tab.style.setProperty('--dock-glow', glow.toFixed(3));
      });
    });
  }

  function resetDockTabs() {
    if (!tabsEl) return;
    if (dockRaf) {
      window.cancelAnimationFrame(dockRaf);
      dockRaf = null;
    }
    tabsEl.querySelectorAll('.loom-detail-tab').forEach(function (tab) {
      tab.style.removeProperty('--dock-scale');
      tab.style.removeProperty('--dock-lift');
      tab.style.removeProperty('--dock-glow');
    });
  }

  function getTitle(target) {
    var explicit = target.getAttribute('data-detail-title');
    if (explicit) return explicit;
    var heading = target.querySelector('.blog-card-title, h1, h2, h3, [data-anc$=".title"]');
    return cleanText(heading && heading.textContent);
  }

  function cleanText(text) {
    return text ? String(text).replace(/[\u25be\u25b8\u25bc\u25ba]/g, '').replace(/\s+/g, ' ').trim() : '';
  }

  function escapeHtml(text) {
    return String(text || '').replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function slug(text) {
    return cleanText(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'detail';
  }

  window.LoomDetailOverlay = {
    init: init,
    refresh: refresh,
    open: open,
    close: close
  };

  document.addEventListener('DOMContentLoaded', function () {
    var isCanvas = !!document.getElementById('canvas-stage');
    init({ root: document, clickToOpen: false, hoverToOpen: true, requireCtrlForHover: true });
  });
})();
