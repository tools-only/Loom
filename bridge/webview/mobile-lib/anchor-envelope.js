// mobile-lib/anchor-envelope.js
// Source: extracted from anchor-client.js lines 1486-1669 for mobile-only use.
// Desktop continues using anchor-client.js directly — do NOT import this from desktop.
'use strict';

window.AnchorEnvelope = (function () {

  function snapshotRenderState(container) {
    var anchors = Array.from(container.querySelectorAll('[data-anc]'));
    var anchor_tree = anchors.map(function (el) { return el.getAttribute('data-anc'); });
    var anchor_index = {};
    anchors.forEach(function (el) {
      var id = el.getAttribute('data-anc');
      var handles = (el.getAttribute('data-handles') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      var deps    = (el.getAttribute('data-deps')    || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      anchor_index[id] = { handles: handles, deps: deps };
    });
    return {
      anchor_tree: anchor_tree,
      anchor_index: anchor_index,
      dom_signature: 'sig:' + anchor_tree.length,
      viewport: { scroll_top: window.scrollY | 0, visible_anchors: [] }
    };
  }

  function collectRelevantSubtree(container, target_ref) {
    if (!target_ref) return null;
    var el = container.querySelector('[data-anc="' + target_ref.replace(/"/g, '\\"') + '"]');
    if (!el) return null;

    var target_html = el.outerHTML;

    var depsStr = el.getAttribute('data-deps') || '';
    var forward_ids = depsStr.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    var forward_deps = {};
    forward_ids.forEach(function (id) {
      var depEl = container.querySelector('[data-anc="' + id.replace(/"/g, '\\"') + '"]');
      if (depEl) forward_deps[id] = depEl.outerHTML;
    });

    var reverse_deps = {};
    container.querySelectorAll('[data-deps]').forEach(function (other) {
      var odeps = (other.getAttribute('data-deps') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      if (odeps.indexOf(target_ref) !== -1) {
        var oid = other.getAttribute('data-anc');
        if (oid && oid !== target_ref) reverse_deps[oid] = other.outerHTML;
      }
    });

    return {
      target_ref: target_ref,
      target_html: target_html,
      forward_deps: Object.keys(forward_deps).length > 0 ? forward_deps : undefined,
      reverse_deps: Object.keys(reverse_deps).length > 0 ? reverse_deps : undefined
    };
  }

  function buildEnvelope(opts) {
    var op             = opts.op;
    var target_kind    = opts.target_kind;
    var target_ref     = opts.target_ref;
    var instruction    = opts.instruction || null;
    var selection      = opts.selection   || null;
    var container      = opts.container;
    var sessionId      = opts.sessionId   || null;
    var overrideBundle = opts.overrideBundle || null;

    var eventId = 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);

    var renderState = snapshotRenderState(container);
    if (target_ref && target_kind === 'anchor') {
      renderState.relevant_subtree = collectRelevantSubtree(container, target_ref);
    }

    var bundle = Object.assign({
      memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
      scope_hint: 'standard',
      transient_override: !!overrideBundle
    }, overrideBundle || {});

    var intent = { op: op, target_kind: target_kind };
    if (target_ref != null) intent.target_ref = target_ref;
    if (instruction != null) intent.instruction = instruction;

    return {
      schema_version: '1.0',
      intent: intent,
      selection: selection,
      context_bundle: bundle,
      render_state: renderState,
      domain: null, // TODO: trading domain inference not yet ported to mobile
      provenance: {
        session_id: sessionId || '',
        event_id: eventId,
        parent_event_id: null,
        timestamp: new Date().toISOString(),
        client_version: '0.1.0'
      }
    };
  }

  return { buildEnvelope: buildEnvelope, snapshotRenderState: snapshotRenderState, collectRelevantSubtree: collectRelevantSubtree };
})();
