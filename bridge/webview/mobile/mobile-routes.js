// mobile/mobile-routes.js — Route management for 4-tab mobile shell
'use strict';

window.MobileRoutes = (function () {
  var _current = 'home';

  function _relTime(ts) {
    var diff = Date.now() - ts;
    if (diff < 60000)  return 'just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    return Math.floor(diff / 3600000) + 'hr ago';
  }

  function _renderActivity(events) {
    var el = document.getElementById('mob-activity-list');
    if (!el) return;
    if (!events || !events.length) {
      el.innerHTML = '<p class="mob-empty">No activity yet</p>';
      return;
    }
    var html = '';
    var sorted = events.slice().reverse();
    sorted.forEach(function (evt) {
      var kind    = evt.kind || 'event';
      var summary = (evt.payload && (evt.payload.summary || evt.payload.message || evt.payload.choice)) || kind;
      var time    = evt.ts ? _relTime(evt.ts) : '';
      html += '<div class="mob-activity-card mob-activity-card--' + kind + '">' +
        '<span class="mob-activity-kind">' + kind + '</span>' +
        '<p class="mob-activity-summary">' + _esc(String(summary).slice(0, 200)) + '</p>' +
        (time ? '<time class="mob-activity-time">' + time + '</time>' : '') +
        '</div>';
    });
    el.innerHTML = html;
  }

  function _renderInbox(items) {
    var el = document.getElementById('mob-inbox-list');
    if (!el) return;
    if (!items || !items.length) {
      el.innerHTML = '<p class="mob-empty">No messages yet</p>';
      return;
    }
    var groups = new Map();
    items.forEach(function (item) {
      var d = item.domain || 'general';
      if (!groups.has(d)) groups.set(d, []);
      groups.get(d).push(item);
    });
    var html = '';
    groups.forEach(function (groupItems, domain) {
      html += '<div class="mob-inbox-group"><h3>' + _esc(domain) + '</h3><div class="mob-inbox-items">';
      groupItems.slice(0, 20).forEach(function (item) {
        html += '<div class="mob-inbox-item">' +
          '<span class="mob-inbox-source">' + _esc(String(item.source || '').replace(/^feed:|^webhook:/, '').slice(0, 24)) + '</span>' +
          '<p class="mob-inbox-title">' + _esc(String(item.title || '').slice(0, 100)) + '</p>' +
          '<p class="mob-inbox-summary">' + _esc(String(item.summary || '').slice(0, 120)) + '</p>' +
          '</div>';
      });
      html += '</div></div>';
    });
    el.innerHTML = html;
  }

  function _renderSettings(config) {
    var el = document.getElementById('mob-settings');
    if (!el) return;
    var hand = (config && config.defaultHand) ? config.defaultHand : '(default)';
    el.innerHTML =
      '<h2>AI Hand</h2>' +
      '<div class="mob-settings-row"><span>Active hand</span><span class="mob-settings-val">' + _esc(hand) + '</span></div>' +
      '<h2>Session</h2>' +
      '<div class="mob-settings-row"><span>Status</span><span class="mob-settings-val mob-settings-val--live">Connected</span></div>';
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function mount(name) {
    // Hide all routes
    document.querySelectorAll('[data-route]').forEach(function (s) {
      s.setAttribute('hidden', '');
    });
    // Show target route
    var target = document.querySelector('[data-route="' + name + '"]');
    if (target) target.removeAttribute('hidden');

    // Update bottom nav
    document.querySelectorAll('.mob-nav-btn').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.route === name);
    });

    _current = name;

    // Route-specific re-render
    if (name === 'activity' && window.App) {
      _renderActivity(App.state.activityEvents);
    } else if (name === 'inbox' && window.App) {
      _renderInbox(App.state.inboxItems);
    } else if (name === 'settings' && window.App) {
      _renderSettings(App.state.handsConfig);
    }

    if (window.App && App.events) App.events.emit('route:change', name);
  }

  function current() { return _current; }

  function init() {
    document.querySelectorAll('.mob-nav-btn[data-route]').forEach(function (btn) {
      btn.addEventListener('click', function () { mount(btn.dataset.route); });
    });
    mount('home');

    // Re-render activity/inbox when data arrives (if tab is active)
    if (window.App && App.events) {
      App.events.on('state:activity', function () {
        if (_current === 'activity') _renderActivity(App.state.activityEvents);
      });
      App.events.on('state:inbox', function () {
        if (_current === 'inbox') _renderInbox(App.state.inboxItems);
      });
      App.events.on('state:hands', function () {
        if (_current === 'settings') _renderSettings(App.state.handsConfig);
      });
    }
  }

  return { init: init, mount: mount, current: current };
})();
