/* loom-detail-overlay.js: generic drill-down overlay for Loom HTML. */
(function () {
  'use strict';

  // ── Density level system ──────────────────────────────────────────────
  var DENSITY_LEVELS = {
    L0: ['raw_source', 'raw_item'],
    L1: ['summary', 'evidence', 'analysis', 'gaps'],
    L2: ['state_engine'],
  };

  var _density = {
    level: (typeof localStorage !== 'undefined' && localStorage.getItem('loom.density.level')) || 'L1',
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
    setLevel: function (level) {
      _density.level = level;
      if (typeof localStorage !== 'undefined') localStorage.setItem('loom.density.level', level);
    },
    toggle: function (layer_type, visible) {
      _density.overrides[layer_type] = visible;
      if (typeof localStorage !== 'undefined') localStorage.setItem('loom.density.overrides', JSON.stringify(_density.overrides));
    },
    isVisible: function (layer_type) {
      if (!layer_type) return true;
      if (layer_type in _density.overrides) return _density.overrides[layer_type];
      var custom = _density.customLayers.find(function (l) { return l.layer_type === layer_type; });
      if (custom) {
        var customPreset = DENSITY_LEVELS[custom.default_level] || [];
        return customPreset.indexOf(layer_type) !== -1;
      }
      var preset = DENSITY_LEVELS[_density.level] || DENSITY_LEVELS['L1'];
      return preset.indexOf(layer_type) !== -1;
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
    clickToOpen: true,
    hoverToOpen: true,
    hoverDelay: 650
  };
  var hoverTimer = null;
  var hoverTarget = null;

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
      'display:flex;align-items:center;gap:6px;padding:8px 16px;' +
      'border-bottom:1px solid var(--border,#e8e6f0);flex-wrap:wrap;background:var(--surface,#fff)'
    );

    ['L0', 'L1', 'L2'].forEach(function (lvl) {
      var btn = document.createElement('button');
      btn.textContent = lvl;
      btn.type = 'button';
      btn.style.cssText = (
        'padding:3px 10px;border-radius:999px;border:1.5px solid #e8e6f0;' +
        'font-size:11px;font-weight:700;cursor:pointer;' +
        'background:' + (_density.level === lvl ? '#7A5AF8' : 'transparent') + ';' +
        'color:' + (_density.level === lvl ? '#fff' : '#6b7280')
      );
      btn.addEventListener('click', function () {
        LoomDensity.setLevel(lvl);
        _renderDensityBar(overlayEl);
        _filterSectionsByDensity(overlayEl);
      });
      bar.appendChild(btn);
    });

    var sep = document.createElement('span');
    sep.style.cssText = 'width:1px;height:16px;background:#e8e6f0;margin:0 4px;flex-shrink:0';
    bar.appendChild(sep);

    var allTypes = Object.keys(DENSITY_LEVELS).reduce(function (a, k) {
      return a.concat(DENSITY_LEVELS[k].filter(function (t) { return a.indexOf(t) === -1; }));
    }, []);
    _density.customLayers.forEach(function (cl) {
      if (allTypes.indexOf(cl.layer_type) === -1) allTypes.push(cl.layer_type);
    });
    var LABELS = {
      raw_source: '原始数据', raw_item: '媒体/推文',
      summary: 'Hand 归纳', evidence: '证据行',
      analysis: '深度分析', gaps: '数据缺口',
      state_engine: 'Brain 分析',
    };

    var customPanel = document.createElement('div');
    customPanel.style.cssText = (
      'display:none;position:absolute;background:#fff;border:1px solid #e8e6f0;' +
      'border-radius:10px;padding:12px;box-shadow:0 4px 16px rgba(80,60,160,.10);' +
      'z-index:100;min-width:190px;top:100%;left:0;margin-top:4px;' +
      'flex-direction:column;gap:8px'
    );
    allTypes.forEach(function (lt) {
      var row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = LoomDensity.isVisible(lt);
      cb.addEventListener('change', function () {
        LoomDensity.toggle(lt, cb.checked);
        _filterSectionsByDensity(overlayEl);
      });
      row.appendChild(cb);
      row.appendChild(document.createTextNode(LABELS[lt] || lt));
      customPanel.appendChild(row);
    });

    var customBtn = document.createElement('button');
    customBtn.textContent = '自定义 ▾';
    customBtn.type = 'button';
    customBtn.style.cssText = (
      'padding:3px 10px;border-radius:999px;border:1.5px solid #e8e6f0;' +
      'font-size:11px;font-weight:600;cursor:pointer;background:transparent;color:#6b7280'
    );
    customBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      customPanel.style.display = customPanel.style.display === 'none' ? 'flex' : 'none';
    });
    document.addEventListener('click', function () { customPanel.style.display = 'none'; }, { once: true });

    var wrap = document.createElement('div');
    wrap.style.cssText = 'position:relative';
    wrap.appendChild(customBtn);
    wrap.appendChild(customPanel);
    bar.appendChild(wrap);

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
      if (!options.hoverToOpen || shouldIgnore(event)) return;
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
      root.querySelectorAll('[data-detail-root], [data-has-detail="true"], aside.anc-detail, .blog-card, .anc-section--gc').forEach(function (el) {
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
      '    <button class="loom-detail-close" type="button" aria-label="Close detail"><i class="ph-bold ph-x"></i></button>',
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

    overlay.querySelector('.loom-detail-backdrop').addEventListener('click', close);
    overlay.querySelector('.loom-detail-close').addEventListener('click', close);
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && overlay.classList.contains('loom-detail--open')) close();
    });
  }

  function open(targetOrId, contentEl) {
    ensureOverlay();
    var target = contentEl || resolveTarget(targetOrId);
    if (!target) return false;

    clearHover();
    renderTarget(target, targetOrId);
    _renderDensityBar(overlay);
    _filterSectionsByDensity(overlay);
    requestAnimationFrame(function () {
      overlay.classList.add('loom-detail--open');
    });
    return true;
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove('loom-detail--open');
  }

  function renderTarget(target, fallbackId) {
    tabsEl.innerHTML = '';
    bodyEl.innerHTML = '';

    var title = getTitle(target) || String(fallbackId || target.getAttribute('data-anc') || 'Detail');
    titleEl.textContent = title;
    subtitleEl.textContent = target.getAttribute('data-detail-subtitle') || target.getAttribute('data-anc') || '';

    var pillRow = target.querySelector('.anc-pill-row, .blog-card-tags');
    pillsEl.innerHTML = pillRow ? pillRow.innerHTML : '';

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

    var clone = cloneSummary(target);
    sections.push({ id: 'full', label: 'Full Section', html: clone.innerHTML });
    return sections;
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
    return el.hasAttribute('data-detail-root') ||
      el.getAttribute('data-has-detail') === 'true' ||
      el.classList.contains('blog-card') ||
      el.classList.contains('anc-section--gc') ||
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
    init({ root: document, clickToOpen: !isCanvas, hoverToOpen: true });
  });
})();
