(function () {
  const BRAIN_URL = 'http://127.0.0.1:3002';
  const PANEL_ID = 'anchor-channel-panel';

  const state = {
    available: [],
    channels: [],
    configChannels: [],
    defaultChannel: 'generic'
  };

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function ensurePanel() {
    let panel = document.getElementById(PANEL_ID);
    if (panel) return panel;
    panel = document.createElement('aside');
    panel.id = PANEL_ID;
    panel.className = 'anc-side-panel channel-panel collapsed';
    panel.innerHTML = `
      <div class="side-panel-header">
        <span class="side-panel-title">Channels</span>
        <button class="side-panel-toggle" type="button" data-channel-close title="Close">x</button>
      </div>
      <div class="side-panel-body channel-panel-body">
        <div class="channel-panel-status" data-channel-status>Loading...</div>
        <div class="channel-list" data-channel-list></div>
        <form class="channel-form" data-channel-form>
          <h3>Add or Update Channel</h3>
          <label>Platform<select name="platform" data-platform></select></label>
          <div class="channel-dynamic-fields" data-channel-fields></div>
          <label class="channel-check"><input name="set_default" type="checkbox"> Set as default</label>
          <button class="btn btn--brand btn--sm" type="submit">Save Channel</button>
        </form>
      </div>
    `;
    document.body.appendChild(panel);
    panel.querySelector('[data-channel-close]').addEventListener('click', () => panel.classList.add('collapsed'));
    panel.querySelector('[data-channel-form]').addEventListener('submit', submitForm);
    panel.querySelector('[data-platform]').addEventListener('change', (event) => {
      renderFormFields(event.currentTarget.value, {});
    });
    return panel;
  }

  async function loadChannels() {
    const panel = ensurePanel();
    const status = panel.querySelector('[data-channel-status]');
    status.textContent = 'Loading...';
    try {
      const [summary, config] = await Promise.all([
        fetch(`${BRAIN_URL}/social/channels`).then((res) => res.json()),
        fetch(`${BRAIN_URL}/social/channels/config`).then((res) => res.json()).catch(() => ({}))
      ]);
      state.available = summary.available_channel_types || [];
      state.channels = summary.channels || [];
      state.defaultChannel = summary.default_channel || config.default_channel || 'generic';
      state.configChannels = config.channels || [];
      render();
      status.textContent = `Default: ${state.defaultChannel}`;
    } catch (err) {
      status.textContent = `Failed to load channels: ${err.message || err}`;
    }
  }

  function render() {
    const panel = ensurePanel();
    const select = panel.querySelector('[data-platform]');
    select.innerHTML = state.available.map((item) => {
      return `<option value="${esc(item.platform)}">${esc(item.label)} (${esc(item.platform)})</option>`;
    }).join('');
    if (!select.value && state.available[0]) select.value = state.available[0].platform;
    renderRows();
    renderFormFields(select.value || 'generic', {});
  }

  function renderRows() {
    const panel = ensurePanel();
    const rows = (state.channels || []).map((channel) => {
      const config = findConfigChannel(channel.id) || {};
      const enabled = channel.enabled ? 'enabled' : 'disabled';
      const badge = channel.status || channel.mode || 'bridge';
      const isDefault = channel.id === state.defaultChannel;
      return `
        <div class="channel-row">
          <div class="channel-row-main">
            <strong>${esc(channel.label || channel.id)}${isDefault ? ' *' : ''}</strong>
            <span>${esc(channel.id)} / ${esc(channel.platform)} / ${esc(enabled)} / ${esc(badge)}</span>
          </div>
          <div class="channel-row-actions">
            <button type="button" data-channel-edit="${esc(channel.id)}" title="Edit">Edit</button>
            <button type="button" data-channel-toggle="${esc(channel.id)}" title="Enable or disable">${channel.enabled ? 'Disable' : 'Enable'}</button>
            <button type="button" data-channel-default="${esc(channel.id)}" title="Set default">Default</button>
            ${channel.id === 'generic' ? '' : `<button type="button" data-channel-delete="${esc(channel.id)}" title="Delete">Delete</button>`}
          </div>
        </div>
      `;
    }).join('');
    panel.querySelector('[data-channel-list]').innerHTML = rows || '<p>No channels configured.</p>';
    panel.querySelectorAll('[data-channel-edit]').forEach((btn) => {
      btn.addEventListener('click', () => editChannel(btn.dataset.channelEdit));
    });
    panel.querySelectorAll('[data-channel-toggle]').forEach((btn) => {
      btn.addEventListener('click', () => toggleChannel(btn.dataset.channelToggle));
    });
    panel.querySelectorAll('[data-channel-default]').forEach((btn) => {
      btn.addEventListener('click', () => setDefault(btn.dataset.channelDefault));
    });
    panel.querySelectorAll('[data-channel-delete]').forEach((btn) => {
      btn.addEventListener('click', () => deleteChannel(btn.dataset.channelDelete));
    });
  }

  function renderFormFields(platform, values) {
    const panel = ensurePanel();
    const fields = fieldSpecsFor(platform);
    const html = fields.map((field) => renderField(field, values)).join('');
    panel.querySelector('[data-channel-fields]').innerHTML = html;
  }

  function renderField(field, values) {
    const name = field.name;
    const value = values[name] != null ? values[name] : field.default || '';
    const placeholder = field.placeholder ? ` placeholder="${esc(field.placeholder)}"` : '';
    if (field.kind === 'select') {
      const options = (field.options || []).map((option) => {
        const selected = String(option.value) === String(value) ? ' selected' : '';
        return `<option value="${esc(option.value)}"${selected}>${esc(option.label || option.value)}</option>`;
      }).join('');
      return `<label>${esc(field.label || name)}<select name="${esc(name)}" data-field-name="${esc(name)}">${options}</select></label>`;
    }
    if (field.kind === 'boolean') {
      const checked = value === true || value === 'true' ? ' checked' : '';
      return `<label class="channel-check"><input name="${esc(name)}" data-field-name="${esc(name)}" type="checkbox"${checked}> ${esc(field.label || name)}</label>`;
    }
    if (field.kind === 'tri_state_boolean') {
      const normalized = value === true ? 'true' : value === false ? 'false' : '';
      return `
        <label>${esc(field.label || name)}
          <select name="${esc(name)}" data-field-name="${esc(name)}">
            <option value=""${normalized === '' ? ' selected' : ''}>default</option>
            <option value="true"${normalized === 'true' ? ' selected' : ''}>true</option>
            <option value="false"${normalized === 'false' ? ' selected' : ''}>false</option>
          </select>
        </label>
      `;
    }
    const textValue = Array.isArray(value)
      ? value.join(',')
      : field.kind === 'json' && value && typeof value === 'object'
        ? JSON.stringify(value)
        : value;
    const inputType = field.kind === 'password' ? 'password' : field.kind === 'number' ? 'number' : 'text';
    return `<label>${esc(field.label || name)}<input name="${esc(name)}" data-field-name="${esc(name)}" type="${inputType}" value="${esc(textValue)}"${placeholder}></label>`;
  }

  function fieldSpecsFor(platform) {
    const spec = state.available.find((item) => item.platform === platform);
    return spec && Array.isArray(spec.fields) ? spec.fields : [
      { name: 'channel_id', label: 'Channel ID', kind: 'text' },
      { name: 'label', label: 'Label', kind: 'text' },
      { name: 'allowFrom', label: 'Allow From', kind: 'list', default: ['*'], aliases: ['allow_from'] }
    ];
  }

  function collectFormPayload(form) {
    const platform = form.platform.value || 'generic';
    const fields = fieldSpecsFor(platform);
    const payload = { platform, set_default: form.set_default.checked };
    fields.forEach((field) => {
      const input = Array.from(form.querySelectorAll('[data-field-name]'))
        .find((item) => item.dataset.fieldName === field.name);
      if (!input) return;
      payload[field.name] = readFieldValue(input, field);
    });
    payload.channel_id = String(payload.channel_id || platform).trim();
    payload.label = String(payload.label || payload.channel_id).trim();
    if (payload.enabled == null || payload.enabled === '') payload.enabled = true;
    return payload;
  }

  function readFieldValue(input, field) {
    if (field.kind === 'boolean') return Boolean(input.checked);
    if (field.kind === 'tri_state_boolean') {
      if (input.value === 'true') return true;
      if (input.value === 'false') return false;
      return null;
    }
    if (field.kind === 'list') {
      return input.value.split(',').map((item) => item.trim()).filter(Boolean);
    }
    if (field.kind === 'number') {
      if (input.value.trim() === '') return '';
      const value = Number(input.value);
      return Number.isFinite(value) ? value : input.value.trim();
    }
    if (field.kind === 'json') {
      if (!input.value.trim()) return {};
      try {
        return JSON.parse(input.value);
      } catch (_) {
        return input.value.trim();
      }
    }
    return input.value.trim();
  }

  async function submitForm(event) {
    event.preventDefault();
    const payload = collectFormPayload(event.currentTarget);
    await fetch(`${BRAIN_URL}/social/channels/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    event.currentTarget.reset();
    await loadChannels();
  }

  function editChannel(channelId) {
    const panel = ensurePanel();
    const config = findConfigChannel(channelId) || state.channels.find((item) => item.id === channelId) || {};
    const platform = config.platform || 'generic';
    const select = panel.querySelector('[data-platform]');
    select.value = platform;
    renderFormFields(platform, normalizeConfigForForm(config));
    panel.querySelector('[name="set_default"]').checked = channelId === state.defaultChannel;
  }

  async function toggleChannel(channelId) {
    const config = findConfigChannel(channelId);
    if (!config) return;
    await fetch(`${BRAIN_URL}/social/channels/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...config, enabled: !config.enabled, set_default: false })
    });
    await loadChannels();
  }

  async function setDefault(channelId) {
    await fetch(`${BRAIN_URL}/social/channels/default`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channelId })
    });
    await loadChannels();
  }

  async function deleteChannel(channelId) {
    await fetch(`${BRAIN_URL}/social/channels/${encodeURIComponent(channelId)}`, { method: 'DELETE' });
    await loadChannels();
  }

  function findConfigChannel(channelId) {
    return state.configChannels.find((item) => item.channel_id === channelId || item.id === channelId);
  }

  function normalizeConfigForForm(config) {
    const normalized = { ...config };
    if (!normalized.channel_id && normalized.id) normalized.channel_id = normalized.id;
    const platform = normalized.platform || 'generic';
    fieldSpecsFor(platform).forEach((field) => {
      if (normalized[field.name] != null) return;
      (field.aliases || []).some((alias) => {
        if (normalized[alias] == null) return false;
        normalized[field.name] = normalized[alias];
        return true;
      });
    });
    return normalized;
  }

  function bind() {
    async function openPanel() {
      const panel = ensurePanel();
      panel.classList.toggle('collapsed');
      if (!panel.classList.contains('collapsed')) await loadChannels();
    }
    const btn = document.getElementById('anchor-channels-config-btn');
    if (btn && !btn.dataset.channelPanelBound) {
      btn.dataset.channelPanelBound = '1';
      btn.addEventListener('click', openPanel);
    }
    document.addEventListener('click', (event) => {
      const target = event.target && event.target.closest
        ? event.target.closest('#anchor-channels-config-btn')
        : null;
      if (!target || target.dataset.channelPanelBound === '1') return;
      event.preventDefault();
      openPanel();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
