// Hand Settings Panel — self-mounts gear button on [data-anc^="loom-"] sections
// Reads/writes http://127.0.0.1:3002/hand/:id/config
// Uses Bloom tokens only. No new CSS introduced.

(function () {
  const BRAIN_URL = 'http://127.0.0.1:3002';
  const ATTR = 'data-hsp-mounted';

  const SCHEMA_LABELS = {
    market:    { watched_sectors: '关注板块', kol_feeds: 'KOL RSS 列表', macro_themes: '宏观主题' },
    sentiment: { reddit_subs: 'Reddit 社区', watched_tickers: '关注标的' },
    target:    { tickers: '目标标的' },
    position:  { risk_profile: '风险偏好', positions: '持仓数据' },
  };

  function extractHandId(ancId) {
    return ancId.startsWith('loom-') ? ancId.slice(5) : ancId;
  }

  function buildPanel(el) {
    const ancId = el.getAttribute('data-anc') || '';
    const handId = extractHandId(ancId);
    if (!handId || !SCHEMA_LABELS[handId]) return;

    // Gear button — insert into first h2/h3 if present, else prepend to section
    const heading = el.querySelector('h2, h3');
    const gearBtn = document.createElement('button');
    gearBtn.className = 'btn btn--icon btn--sm';
    gearBtn.title = `${handId} 设置`;
    gearBtn.style.cssText = 'float:right;margin-left:8px;color:var(--ink-3)';
    gearBtn.innerHTML = '<i class="ph-bold ph-gear-six"></i>';

    if (heading) {
      heading.style.display = 'flex';
      heading.style.alignItems = 'center';
      heading.style.justifyContent = 'space-between';
      heading.appendChild(gearBtn);
    } else {
      el.prepend(gearBtn);
    }

    // Settings panel (hidden by default)
    const panel = document.createElement('div');
    panel.className = 'anc-section anc-section--gc hsp-panel';
    panel.style.cssText = 'display:none;margin-top:12px;padding:14px 16px;background:var(--surface-1,rgba(0,0,0,.03));border-radius:12px;';
    panel.innerHTML = `
      <div class="hsp-fields" style="display:flex;flex-direction:column;gap:10px"></div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button class="btn btn--brand btn--sm hsp-save">保存</button>
        <button class="btn btn--ghost btn--sm hsp-cancel">取消</button>
        <span class="hsp-status" style="font-size:12px;color:var(--ink-3);align-self:center;display:none"></span>
      </div>
      <hr class="anc-divider" style="margin:14px 0">
      <div class="hsp-mount-section">
        <div style="font-size:12px;font-weight:700;color:var(--ink-2);margin-bottom:8px;display:flex;align-items:center;gap:6px">
          <i class="ph-bold ph-plug"></i> 挂载外部 Agent
          <span class="hsp-mount-badge" style="display:none;font-size:11px;font-weight:500;padding:2px 8px;border-radius:999px;background:var(--pastel-mint,#e8f8f1);color:var(--accent-emerald,#22c55e)">已挂载</span>
        </div>
        <div class="hsp-mount-form" style="display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:12px;font-weight:600;color:var(--ink-2)">Endpoint URL</label>
            <input class="hsp-endpoint" type="url" placeholder="http://localhost:8080/v1/chat/completions"
              style="padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);font-family:monospace">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:12px;font-weight:600;color:var(--ink-2)">功能描述（可选）</label>
            <textarea class="hsp-description" rows="2" placeholder="例如：专注于 A 股量化信号和板块轮动分析"
              style="padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);resize:vertical;font-family:inherit"></textarea>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            <button class="btn btn--brand btn--sm hsp-mount-btn">挂载</button>
            <button class="btn btn--ghost btn--sm hsp-unmount-btn" style="display:none">卸载</button>
            <span class="hsp-mount-status" style="font-size:12px;color:var(--ink-3)"></span>
          </div>
        </div>
      </div>
    `;

    let currentConfig = {};

    async function loadConfig() {
      try {
        const r = await fetch(`${BRAIN_URL}/hand/${handId}/config`);
        if (r.ok) currentConfig = (await r.json()).config || {};
      } catch (_) { currentConfig = {}; }
      renderFields();
    }

    function renderFields() {
      const fieldsEl = panel.querySelector('.hsp-fields');
      fieldsEl.innerHTML = '';
      const schema = SCHEMA_LABELS[handId] || {};
      for (const [key, label] of Object.entries(schema)) {
        const val = currentConfig[key];
        const isArray = Array.isArray(val) || (val === undefined && key !== 'risk_profile');
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'display:flex;flex-direction:column;gap:4px';
        const lbl = document.createElement('label');
        lbl.textContent = label;
        lbl.style.cssText = 'font-size:12px;font-weight:600;color:var(--ink-2)';
        const inp = document.createElement('textarea');
        inp.dataset.key = key;
        inp.rows = isArray ? 3 : 2;
        inp.style.cssText = 'padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);resize:vertical;font-family:inherit;';
        inp.placeholder = isArray ? '每行一个值' : '输入描述';
        inp.value = isArray
          ? (Array.isArray(val) ? val.join('\n') : '')
          : (val || '');
        wrapper.appendChild(lbl);
        wrapper.appendChild(inp);
        fieldsEl.appendChild(wrapper);
      }
    }

    function collectConfig() {
      const out = { ...currentConfig };
      const schema = SCHEMA_LABELS[handId] || {};
      panel.querySelectorAll('textarea[data-key]').forEach(inp => {
        const key = inp.dataset.key;
        const isArray = Array.isArray(currentConfig[key]) || (currentConfig[key] === undefined && key !== 'risk_profile');
        out[key] = isArray
          ? inp.value.split('\n').map(s => s.trim()).filter(Boolean)
          : inp.value.trim();
      });
      return out;
    }

    // ── mount / unmount ──────────────────────────────────────────────────
    const mountBtn    = panel.querySelector('.hsp-mount-btn');
    const unmountBtn  = panel.querySelector('.hsp-unmount-btn');
    const mountStatus = panel.querySelector('.hsp-mount-status');
    const mountBadge  = panel.querySelector('.hsp-mount-badge');
    const endpointInp = panel.querySelector('.hsp-endpoint');
    const descInp     = panel.querySelector('.hsp-description');

    async function refreshMountState() {
      try {
        const r = await fetch(`${BRAIN_URL}/hand/${handId}/mount`);
        if (!r.ok) return;
        const data = await r.json();
        if (data.mounted) {
          endpointInp.value = data.endpoint || '';
          endpointInp.disabled = true;
          descInp.disabled = true;
          mountBtn.style.display = 'none';
          unmountBtn.style.display = '';
          mountBadge.style.display = '';
          mountStatus.textContent = data.endpoint || '';
        } else {
          endpointInp.disabled = false;
          descInp.disabled = false;
          mountBtn.style.display = '';
          unmountBtn.style.display = 'none';
          mountBadge.style.display = 'none';
          mountStatus.textContent = '';
        }
      } catch (_) {}
    }

    mountBtn.addEventListener('click', async () => {
      const endpoint = endpointInp.value.trim();
      if (!endpoint) { mountStatus.textContent = '请填写 Endpoint URL'; return; }
      mountStatus.textContent = '挂载中…';
      try {
        const r = await fetch(`${BRAIN_URL}/hand/${handId}/mount`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint, description: descInp.value.trim() }),
        });
        const data = await r.json();
        if (data.ok) {
          mountStatus.textContent = '✓ 已挂载';
          await refreshMountState();
        } else {
          mountStatus.textContent = data.error || '挂载失败';
        }
      } catch (e) { mountStatus.textContent = '网络错误'; }
    });

    unmountBtn.addEventListener('click', async () => {
      mountStatus.textContent = '卸载中…';
      try {
        await fetch(`${BRAIN_URL}/hand/${handId}/mount`, { method: 'DELETE' });
        mountStatus.textContent = '';
        await refreshMountState();
      } catch (_) { mountStatus.textContent = '卸载失败'; }
    });

    gearBtn.addEventListener('click', async () => {
      const isOpen = panel.style.display !== 'none';
      panel.style.display = isOpen ? 'none' : 'block';
      if (!isOpen) { await loadConfig(); await refreshMountState(); }
    });

    panel.querySelector('.hsp-save').addEventListener('click', async () => {
      const config = collectConfig();
      const status = panel.querySelector('.hsp-status');
      try {
        const r = await fetch(`${BRAIN_URL}/hand/${handId}/config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        if (r.ok) {
          currentConfig = config;
          status.textContent = '✓ 已保存';
          status.style.display = '';
          setTimeout(() => { status.style.display = 'none'; }, 2000);
        }
      } catch (_) {
        status.textContent = '保存失败';
        status.style.display = '';
      }
    });

    panel.querySelector('.hsp-cancel').addEventListener('click', () => {
      panel.style.display = 'none';
    });

    el.appendChild(panel);
    el.setAttribute(ATTR, '1');
  }

  function mountAll(root) {
    (root || document).querySelectorAll('[data-anc^="loom-"]:not([' + ATTR + '])').forEach(buildPanel);
  }

  const observer = new MutationObserver(() => mountAll());
  observer.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => mountAll());
  } else {
    mountAll();
  }
})();
