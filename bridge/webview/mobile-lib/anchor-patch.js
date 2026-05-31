// mobile-lib/anchor-patch.js
// Source: extracted from anchor-client.js lines 908-918 for mobile-only use.
// Pure swap loop — no handle/collapse re-injection (mobile uses inline action rows instead).
'use strict';

window.AnchorPatch = (function () {

  function applyPatches(container, patches, opts) {
    opts = opts || {};
    var results = [];
    patches.forEach(function (p) {
      var el = container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (!el) {
        results.push({ anchor_id: p.anchor_id, replaced: false });
        return;
      }
      if (opts.onBeforeSwap) opts.onBeforeSwap(p.anchor_id, el);
      el.outerHTML = p.html_fragment;
      var newEl = container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (opts.onAfterSwap) opts.onAfterSwap(p.anchor_id, newEl);
      results.push({ anchor_id: p.anchor_id, replaced: true });
    });
    return results;
  }

  return { applyPatches: applyPatches };
})();
