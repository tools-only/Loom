// Checkpoint Review Deck — self-mounts on [data-anc="checkpoint-review-deck"] via MutationObserver
// Shows visual queries when bottleneck routing returns "ask", posts user responses.
// Posts to POST /episodes/{episode_id}/checkpoint-response
(function () {
  const BRAIN_URL = 'http://127.0.0.1:3002';
  const ATTR = 'data-crd-mounted';

  function h(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

  function postCheckpoint(epid, queryId, gesture, anchorType, anchorId, cardEl, deckEl, intentEl) {
    var body = JSON.stringify({
      query_id: queryId,
      gesture: gesture,
      anchor_type: anchorType,
      anchor_id: anchorId,
    });

    cardEl.style.opacity = '0.5';
    fetch(BRAIN_URL + '/episodes/' + encodeURIComponent(epid) + '/checkpoint-response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body
    })
    .then(function (r) { return r.ok ? r.json() : {}; })
    .then(function (data) {
      var summary = (data.intent_lens && data.intent_lens.summary) || gesture;
      if (intentEl) intentEl.textContent = summary;
      cardEl.style.opacity = '1';
      cardEl.style.textDecoration = 'line-through';
      setTimeout(function () { cardEl.style.display = 'none'; }, 1500);
    })
    .catch(function () {
      cardEl.style.opacity = '1';
      if (intentEl) intentEl.textContent = 'error — retry';
    });
  }

  function render(el, data) {
    var queries = (data && data.visual_queries) ? data.visual_queries : [];
    var epid = el.getAttribute('data-episode-id') || '';

    if (!queries.length) {
      el.innerHTML = '';
      el.setAttribute(ATTR, '1');
      return;
    }

    var cards = queries.map(function (q) {
      var cardLabel = q.query_type === 'gap_salience' ? 'Should we verify this now?' :
                      q.query_type === 'goal_fork' ? 'Which direction?' :
                      'Can we trust this evidence?';
      return '<div class="crd-card" data-query-id="' + h(q.query_id) +
             '" data-anchor-id="' + h(q.anchor_id) + '" data-anchor-type="' + h(q.anchor_type) +
             '" style="padding:10px 12px;border:1px solid var(--surface-2,rgba(0,0,0,.1));border-radius:10px;margin-bottom:8px;background:var(--paper)">' +
             '<div class="anc-pill-row" style="margin-bottom:4px"><span class="anc-pill anc-pill--review">' +
             h(q.query_type) + '</span></div>' +
             '<div style="font-size:13px;color:var(--ink);margin-bottom:8px">' + cardLabel + '</div>' +
             (q.query_type === 'goal_fork' && q.cards && q.cards.length >= 2 ?
               '<div style="display:flex;gap:8px;margin-bottom:8px">' +
                 '<button class="btn btn--brand btn--sm crd-fork-a" style="flex:1;padding:8px">' + h(q.cards[0].label) + '</button>' +
                 '<button class="btn btn--ghost btn--sm crd-fork-b" style="flex:1;padding:8px">' + h(q.cards[1].label) + '</button>' +
               '</div>' :
               ''             ) +
             '<div style="font-size:12px;color:var(--ink-2);margin-bottom:8px">' +
             (q.cards && q.cards[0] ? h(q.cards[0].label) : '') + '</div>' +
             '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
             '<button class="btn btn--brand btn--sm crd-trust">Trust</button>' +
             '<button class="btn btn--ghost btn--sm crd-contest">Contest</button>' +
             '<button class="btn btn--ghost btn--sm crd-expand">Expand</button>' +
             '<button class="btn btn--ghost btn--sm crd-skip">Skip</button>' +
             '<button class="btn btn--ghost btn--sm crd-pin">Pin</button>' +
             '<button class="btn btn--ghost btn--sm crd-mute">Mute</button>' +
             '</div>' +
             '<div class="crd-intent" style="margin-top:6px;font-size:11px;color:var(--accent)" hidden></div>' +
             '</div>';
    }).join('');

    el.innerHTML =
      '<div class="anc-pill-row" style="margin-bottom:6px"><span class="anc-pill anc-pill--review">Checkpoint</span></div>' +
      '<div style="font-size:12px;color:var(--ink-2);margin-bottom:8px">' + queries.length + ' question(s) need your input</div>' +
      cards;
    el.setAttribute(ATTR, '1');

    // Wire up buttons
    el.querySelectorAll('.crd-card').forEach(function (card) {
      var qid = card.getAttribute('data-query-id');
      var aid = card.getAttribute('data-anchor-id');
      var atype = card.getAttribute('data-anchor-type');
      var intentEl = card.querySelector('.crd-intent');
      card.querySelector('.crd-trust').addEventListener('click', function () {
        postCheckpoint(epid, qid, 'trust', atype, aid, card, el, intentEl);
      });
      card.querySelector('.crd-contest').addEventListener('click', function () {
        postCheckpoint(epid, qid, 'contest', atype, aid, card, el, intentEl);
      });
      card.querySelector('.crd-expand').addEventListener('click', function () {
        postCheckpoint(epid, qid, 'expand', atype, aid, card, el, intentEl);
      });
      card.querySelector('.crd-skip').addEventListener('click', function () {
        card.style.opacity = '0.5';
        card.style.transition = 'opacity 0.3s';
        setTimeout(function () { card.style.display = 'none'; }, 500);
      });
      var pinBtn = card.querySelector('.crd-pin');
      if (pinBtn) {
        pinBtn.addEventListener('click', function () {
          postCheckpoint(epid, qid, 'pin', atype, aid, card, el, intentEl);
        });
      }
      var muteBtn = card.querySelector('.crd-mute');
      if (muteBtn) {
        muteBtn.addEventListener('click', function () {
          postCheckpoint(epid, qid, 'mute', atype, aid, card, el, intentEl);
        });
      }
      var forkA = card.querySelector('.crd-fork-a');
      var forkB = card.querySelector('.crd-fork-b');
      if (forkA) {
        forkA.addEventListener('click', function () {
          postCheckpoint(epid, qid, 'trust', atype, aid, card, el, intentEl);
        });
      }
      if (forkB) {
        forkB.addEventListener('click', function () {
          postCheckpoint(epid, qid, 'contest', atype, aid, card, el, intentEl);
        });
      }
    });
  }

  function loadData(el) {
    var epid = el.getAttribute('data-episode-id') || '';
    if (!epid) {
      el.setAttribute(ATTR, '1');
      return;
    }
    fetch(BRAIN_URL + '/episodes/' + encodeURIComponent(epid) + '/workspace')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) { render(el, data); })
      .catch(function () {
        el.innerHTML = '';
        el.setAttribute(ATTR, '1');
      });
  }

  function mount(el) {
    if (el.hasAttribute(ATTR)) return;
    el.setAttribute(ATTR, '1');
    loadData(el);
  }

  function mountAll(root) {
    (root || document).querySelectorAll(
      '[data-anc="checkpoint-review-deck"]:not([' + ATTR + '])'
    ).forEach(mount);
  }

  var observer = new MutationObserver(function () { mountAll(); });
  observer.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  } else {
    mountAll();
  }

  window.CheckpointReviewDeck = { refresh: function (el) { el.removeAttribute(ATTR); mount(el); }, mountAll: mountAll };
})();
