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
      <div class="hsp-runtime-section" style="padding:12px;border:1px solid var(--surface-2,rgba(0,0,0,.12));border-radius:10px;background:var(--paper)">
        <div style="font-size:12px;font-weight:700;color:var(--ink-2);margin-bottom:8px;display:flex;align-items:center;gap:6px">
          <i class="ph-bold ph-cpu"></i> 运行 Agent
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <select class="hsp-runtime-select" style="min-width:0;flex:1;padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink)"></select>
          <button class="btn btn--brand btn--sm hsp-runtime-save">应用</button>
        </div>
        <div class="hsp-runtime-status" style="margin-top:6px;font-size:11px;color:var(--ink-3)"></div>
        <label style="display:flex;gap:7px;align-items:flex-start;margin-top:9px;font-size:12px;color:var(--ink-2)">
          <input type="checkbox" class="hsp-brain-default" style="margin-top:2px">
          <span>同时作为 Brain 动态任务的默认 Agent（复杂任务由 Brain 生成临时 Hand 时使用）</span>
        </label>
        <details class="hsp-adapter-register" style="margin-top:10px">
          <summary style="cursor:pointer;font-size:12px;font-weight:600;color:var(--ink-2)">接入新的 Agent</summary>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">
            <select class="hsp-adapter-kind" style="padding:8px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);color:var(--ink)">
              <option value="codex-sdk">Codex App Server · SDK</option>
              <option value="codex-raw">Codex App Server · Raw RPC</option>
              <option value="http-openai">OpenAI-compatible HTTP</option>
              <option value="http-loom">Loom Agent HTTP</option>
            </select>
            <input class="hsp-adapter-id" placeholder="adapter id，例如 codex-local" style="padding:8px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);color:var(--ink)">
            <input class="hsp-adapter-target" placeholder="Codex Home，例如 D:\\agent\\.codex" style="grid-column:1/-1;padding:8px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);color:var(--ink);font-family:monospace">
            <input class="hsp-adapter-token-env" placeholder="Token 环境变量（可选）" style="padding:8px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);color:var(--ink)">
            <button class="btn btn--ghost btn--sm hsp-adapter-add">注册并选择</button>
          </div>
          <div class="hsp-adapter-status" style="margin-top:6px;font-size:11px;color:var(--ink-3)"></div>
        </details>
      </div>
      <hr class="anc-divider" style="margin:14px 0">
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

    const runtimeSelect = panel.querySelector('.hsp-runtime-select');
    const runtimeStatus = panel.querySelector('.hsp-runtime-status');
    const brainDefault = panel.querySelector('.hsp-brain-default');
    const adapterKind = panel.querySelector('.hsp-adapter-kind');
    const adapterIdInput = panel.querySelector('.hsp-adapter-id');
    const adapterTarget = panel.querySelector('.hsp-adapter-target');
    const adapterTokenEnv = panel.querySelector('.hsp-adapter-token-env');
    const adapterStatus = panel.querySelector('.hsp-adapter-status');

    function addRuntimeOption(value, label) {
      if ([...runtimeSelect.options].some(option => option.value === value)) return;
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      runtimeSelect.appendChild(option);
    }

    async function loadRuntimeState(selectAdapterId = '') {
      runtimeSelect.disabled = true;
      runtimeStatus.textContent = '正在读取运行 Agent…';
      try {
        const r = await fetch(`${BRAIN_URL}/hand/${handId}/runtime`);
        const data = await r.json();
        if (!data.ok) throw new Error(data.error || '读取失败');
        runtimeSelect.innerHTML = '';
        addRuntimeOption('default', `跟随 Hand 默认 (${data.declared_runtime || 'sdk'})`);
        addRuntimeOption('sdk', 'Loom 内置 SDK');
        for (const adapter of (data.adapters || [])) {
          const detail = [adapter.protocol, adapter.transport].filter(Boolean).join(' / ');
          addRuntimeOption(adapter.id, detail ? `${adapter.id} · ${detail}` : adapter.id);
        }
        runtimeSelect.value = selectAdapterId || data.configured_runtime || 'default';
        if (!runtimeSelect.value) runtimeSelect.value = 'default';
        brainDefault.checked = data.default_runtime_adapter === runtimeSelect.value;
        runtimeStatus.textContent = `当前生效：${data.effective_runtime}`;
      } catch (error) {
        runtimeStatus.textContent = error.message || '无法连接 Loom Brain';
      } finally {
        runtimeSelect.disabled = false;
      }
    }

    async function saveRuntime(adapterId) {
      const r = await fetch(`${BRAIN_URL}/hand/${handId}/runtime`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ adapter_id: adapterId }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || '应用失败');
      runtimeStatus.textContent = `当前生效：${data.effective_runtime}`;
      return data;
    }

    async function saveBrainDefault(adapterId) {
      if (!adapterId || ['default', 'sdk'].includes(adapterId)) {
        throw new Error('请选择已注册的 Agent Adapter 作为 Brain 默认执行器');
      }
      const r = await fetch(`${BRAIN_URL}/adapters/default-runtime`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ adapter_id: adapterId }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || 'Brain 默认 Agent 设置失败');
      return data;
    }

    panel.querySelector('.hsp-runtime-save').addEventListener('click', async () => {
      runtimeStatus.textContent = '正在应用…';
      try {
        await saveRuntime(runtimeSelect.value);
        if (brainDefault.checked) await saveBrainDefault(runtimeSelect.value);
      } catch (error) {
        runtimeStatus.textContent = error.message || '应用失败';
      }
    });

    adapterKind.addEventListener('change', () => {
      const kind = adapterKind.value;
      adapterTarget.placeholder = kind === 'codex-sdk'
        ? 'Codex Home，例如 D:\\agent\\.codex'
        : kind === 'codex-raw'
          ? '启动命令，例如 codex app-server --listen stdio://'
          : 'Agent endpoint URL';
    });

    panel.querySelector('.hsp-adapter-add').addEventListener('click', async () => {
      const adapterId = adapterIdInput.value.trim();
      const kind = adapterKind.value;
      const target = adapterTarget.value.trim();
      if (!adapterId) { adapterStatus.textContent = '请填写 adapter id'; return; }
      const isCodex = kind.startsWith('codex-');
      const isRaw = kind === 'codex-raw';
      const config = {
        adapter_id: adapterId,
        transport: isCodex ? 'process' : 'http',
        protocol: isCodex ? 'codex' : (kind === 'http-openai' ? 'openai' : 'loom'),
        codex_backend: isRaw ? 'raw' : 'sdk',
        command: isRaw ? (target || 'codex app-server --listen stdio://') : [],
        endpoint: isCodex ? '' : target,
        auth_token_env: adapterTokenEnv.value.trim(),
        codex_home: isCodex && !isRaw ? target : '',
        capabilities: ['runtime.hand', 'workspace.patch'],
        set_default_runtime: brainDefault.checked,
        persist: true,
      };
      adapterStatus.textContent = '正在注册…';
      try {
        const r = await fetch(`${BRAIN_URL}/adapters/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        const data = await r.json();
        if (!data.ok) throw new Error(data.error || '注册失败');
        await loadRuntimeState(adapterId);
        await saveRuntime(adapterId);
        adapterStatus.textContent = `已注册并选择 ${adapterId}`;
      } catch (error) {
        adapterStatus.textContent = error.message || '注册失败';
      }
    });

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
      if (!isOpen) { await loadRuntimeState(); await loadConfig(); await refreshMountState(); }
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

    el.setAttribute(ATTR, '1');
    el.appendChild(panel);
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
