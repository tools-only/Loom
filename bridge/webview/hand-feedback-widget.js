// Hand Feedback Widget — self-mounts on [data-anc^="loom-"] sections via MutationObserver
// Posts reward signals to http://127.0.0.1:3001/feedback
// Uses Bloom tokens only. No new CSS introduced.

(function () {
  const BRAIN_URL = 'http://127.0.0.1:3001';
  const ATTR = 'data-hfw-mounted';

  function extractHandId(ancId) {
    // "loom-market" → "market"
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
      <button class="btn btn--icon hfw-thumb" data-v="up" title="有帮助" style="color:var(--ink-3)">
        <i class="ph-bold ph-thumbs-up"></i>
      </button>
      <button class="btn btn--icon hfw-thumb" data-v="down" title="需要改进" style="color:var(--ink-3)">
        <i class="ph-bold ph-thumbs-down"></i>
      </button>
      <input class="hfw-note" type="text" placeholder="备注（可选）..."
        style="flex:1;min-width:120px;padding:6px 10px;border-radius:999px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);outline:none;">
      <button class="btn btn--sm btn--ghost hfw-submit" style="display:none">提交</button>
      <span class="hfw-sent" style="display:none;font-size:12px;color:var(--ink-3)">✓ 已记录</span>
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
      const event = {
        hand_id: handId,
        type: 'explicit_feedback',
        vote: selectedVote,
        note: note || null,
        ts: Date.now() / 1000,
      };
      try {
        await fetch(`${BRAIN_URL}/feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(event),
        });
      } catch (_) { /* offline — ignore */ }
      widget.querySelector('.hfw-submit').style.display = 'none';
      widget.querySelector('.hfw-note').value = '';
      const sent = widget.querySelector('.hfw-sent');
      sent.style.display = '';
      setTimeout(() => { sent.style.display = 'none'; }, 2000);
      selectedVote = null;
      widget.querySelectorAll('.hfw-thumb').forEach(b => { b.style.color = 'var(--ink-3)'; });
    });

    el.appendChild(widget);
    el.setAttribute(ATTR, '1');
  }

  function mountAll(root) {
    (root || document).querySelectorAll('[data-anc^="loom-"]:not([' + ATTR + '])').forEach(buildWidget);
  }

  // MutationObserver — self-mount when sections appear
  const observer = new MutationObserver(() => mountAll());
  observer.observe(document.body, { childList: true, subtree: true });

  // Mount on anything already in DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => mountAll());
  } else {
    mountAll();
  }
})();
