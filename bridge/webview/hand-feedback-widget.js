// Hand Feedback Widget 鈥?self-mounts on [data-anc^="loom-"] sections via MutationObserver
// Posts reward signals to http://127.0.0.1:3002/feedback
// Uses Bloom tokens only. No new CSS introduced.

(function () {
  const BRAIN_URL = 'http://127.0.0.1:3002';
  const ATTR = 'data-hfw-mounted';

  function extractHandId(ancId) {
    // "loom-market" 鈫?"market"
    return ancId.startsWith('loom-') ? ancId.slice(5) : ancId;
  }

  function buildWidget(el) {
    const ancId = el.getAttribute('data-anc') || '';
    const handId = extractHandId(ancId);
    if (!handId) return;

    const widget = document.createElement('div');
    widget.className = 'hand-feedback-widget';
    widget.style.cssText = [
      'display:flex', 'align-items:flex-start', 'gap:8px',
      'padding:10px 0 4px', 'margin-top:8px',
      'border-top:1px solid var(--surface-2, rgba(0,0,0,.08))',
      'flex-wrap:wrap',
    ].join(';');

    widget.innerHTML = `
      <button class="btn btn--icon hfw-thumb" data-v="up" title="Helpful" style="color:var(--ink-3)">
        <i class="ph-bold ph-thumbs-up"></i>
      </button>
      <button class="btn btn--icon hfw-thumb" data-v="down" title="Needs revision" style="color:var(--ink-3)">
        <i class="ph-bold ph-thumbs-down"></i>
      </button>
      <input class="hfw-note" type="text" placeholder="Note (optional)..."
        style="flex:1;min-width:120px;padding:6px 10px;border-radius:999px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);outline:none;">
      <button class="btn btn--sm btn--ghost hfw-submit" style="display:none">Submit</button>
      <span class="hfw-sent" style="display:none;font-size:12px;color:var(--ink-3)">Recorded</span>
    `;

    let selectedVote = null;

    widget.querySelectorAll('.hfw-thumb').forEach(btn => {
      btn.addEventListener('click', () => {
        selectedVote = btn.dataset.v;
        widget.querySelectorAll('.hfw-thumb').forEach(b => {
          b.style.color = b.dataset.v === selectedVote
            ? (selectedVote === 'up' ? 'var(--accent-green, #22c55e)' : 'var(--accent-rose, #f43f5e)')
            : 'var(--ink-3)';
        });
        widget.querySelector('.hfw-submit').style.display = '';
      });
    });

    widget.querySelector('.hfw-note').addEventListener('keydown', e => {
      if (e.key === 'Enter') widget.querySelector('.hfw-submit').click();
    });

    widget.querySelector('.hfw-submit').addEventListener('click', async () => {
      const note = widget.querySelector('.hfw-note').value.trim();
      const episodeId = el.getAttribute('data-episode-id') || el.dataset.episodeId || '';
      const object_ref = el.getAttribute('data-object-ref') || el.getAttribute('data-orchestration-ref') || ('hand:' + handId);
      const object_type = el.getAttribute('data-object-type') || (object_ref.split(':')[0] || 'hand');
      const event = {
        hand_id: handId,
        type: 'explicit_feedback',
        raw_signal: selectedVote === 'up' ? 'thumbs_up' : 'thumbs_down',
        vote: selectedVote,
        episode_id: episodeId,
        object_ref,
        object_type,
        orchestration_ref: object_ref,
        note: note || null,
        comment: note || '',
        ui_scope: {
          anchor_id: ancId,
          object_ref,
          selection: '',
        },
        ts: Date.now() / 1000,
      };
      try {
        const response = await fetch(`${BRAIN_URL}/feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(event),
        });
        const data = await response.json().catch(() => null);
        if (data && data.intent_lens) {
          widget.dataset.intentLens = JSON.stringify(data.intent_lens);
          widget.querySelector('.hfw-sent').textContent = data.intent_lens.summary || 'Intent lens recorded';
        }
      } catch (_) { /* offline - ignore */ }
      widget.querySelector('.hfw-submit').style.display = 'none';
      widget.querySelector('.hfw-note').value = '';
      const sent = widget.querySelector('.hfw-sent');
      sent.style.display = '';
      setTimeout(() => { sent.style.display = 'none'; }, 2000);
      selectedVote = null;
      widget.querySelectorAll('.hfw-thumb').forEach(b => { b.style.color = 'var(--ink-3)'; });
    });

    el.setAttribute(ATTR, '1');
    el.appendChild(widget);
  }

  function mountAll(root) {
    (root || document).querySelectorAll('[data-anc^="loom-"]:not([' + ATTR + '])').forEach(buildWidget);
  }

  // MutationObserver 鈥?self-mount when sections appear
  const observer = new MutationObserver(() => mountAll());
  observer.observe(document.body, { childList: true, subtree: true });

  // Mount on anything already in DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => mountAll());
  } else {
    mountAll();
  }
})();

