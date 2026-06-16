(function () {
  const URLS = {
    intent: 'http://localhost:3002/intent-stream/data',
    feedback: 'http://localhost:3002/feedback',
    flywheel: 'http://localhost:3002/flywheel?limit=100',
    goals: 'http://localhost:3002/goals?status=all',
  };

  const PATHS = {
    feedback: 'D:\\ai-native chrome\\logs\\feedback.jsonl',
    flywheel: 'D:\\ai-native chrome\\brain\\flywheel',
    intent: 'D:\\ai-native chrome\\brain\\context\\intent-stream.jsonl',
    wiki: 'D:\\ai-native chrome\\brain\\intent_wiki\\intents.json',
  };

  function esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmt(value) {
    if (value === null || value === undefined || value === '') return '-';
    return esc(value);
  }

  function pct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    return `${Math.round(n * 100)}%`;
  }

  function shortId(value, n = 18) {
    const text = String(value || '');
    if (text.length <= n) return esc(text || '-');
    return `${esc(text.slice(0, n))}<span class="lii-muted">...</span>`;
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  async function safeFetch(url) {
    try {
      return { ok: true, data: await fetchJson(url) };
    } catch (error) {
      return { ok: false, error: error.message || String(error) };
    }
  }

  function groupBy(items, keyFn) {
    const groups = new Map();
    for (const item of items) {
      const key = keyFn(item) || 'unknown';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    return groups;
  }

  function renderStat(label, value, icon, tone = '') {
    return `
      <div class="lii-stat ${tone}">
        <i class="ph-bold ${icon}"></i>
        <span>${esc(label)}</span>
        <strong>${fmt(value)}</strong>
      </div>`;
  }

  function emptyState(title, path, detail = '') {
    return `
      <div class="lii-empty">
        <i class="ph-bold ph-database"></i>
        <strong>${esc(title)}</strong>
        <span>${esc(detail || 'No records have been written yet.')}</span>
        <code>${esc(path)}</code>
      </div>`;
  }

  function errorState(results) {
    const errors = Object.entries(results)
      .filter(([, result]) => !result.ok)
      .map(([name, result]) => `<li><strong>${esc(name)}</strong>: ${esc(result.error)}</li>`)
      .join('');
    return `
      <section class="lii-page">
        <div class="lii-hero lii-hero--error">
          <div>
            <span class="lii-eyebrow">Brain service unavailable</span>
            <h1>Intelligence Ledger</h1>
            <p>Start Loom Brain on port 3002, then refresh this page.</p>
          </div>
          <button class="btn btn--sm btn--brand" type="button" data-lii-refresh>
            <i class="ph-bold ph-arrow-clockwise"></i> Refresh
          </button>
        </div>
        <div class="lii-panel">
          <h2>Failed data sources</h2>
          <ul class="lii-error-list">${errors}</ul>
        </div>
      </section>`;
  }

  function renderMetadataLayer(nodes, zones) {
    if (!nodes.length) return emptyState('No Intent Wiki nodes', PATHS.wiki);
    const zoneMeta = new Map(zones.map(zone => [zone.id, zone]));
    const rows = nodes
      .slice()
      .sort((a, b) => String(a.zone).localeCompare(String(b.zone)) || Number(b.confidence || 0) - Number(a.confidence || 0))
      .map(node => {
        const hints = node.activation_hints || {};
        const keywords = asArray(hints.keywords).slice(0, 5).map(k => `<span>${esc(k)}</span>`).join('');
        const zone = zoneMeta.get(node.zone) || {};
        return `
          <article class="lii-intent-row ${node.is_active ? 'is-active' : ''}">
            <div>
              <div class="lii-row-title">${fmt(node.label)}</div>
              <div class="lii-row-sub">${fmt(zone.label || node.zone)} / ${fmt(node.status)} / evidence ${fmt(node.evidence_count)}</div>
            </div>
            <div class="lii-score">
              <strong>${pct(node.confidence)}</strong>
              <span>confidence</span>
            </div>
            <div class="lii-tags">${keywords || '<span>no keywords</span>'}</div>
            <div class="lii-row-time">
              <span>${fmt(node.updated_at)}</span>
              <small>${fmt(node.last_evidence_ts)}</small>
            </div>
          </article>`;
      }).join('');
    return `<div class="lii-intent-table">${rows}</div>`;
  }

  function renderAbstractLayer(nodes, zones) {
    if (!nodes.length) return emptyState('No abstracted intents yet', PATHS.wiki);
    const grouped = groupBy(nodes, node => node.zone);
    const zoneLookup = new Map(zones.map(zone => [zone.id, zone]));
    return Array.from(grouped.entries()).map(([zoneId, zoneNodes]) => {
      const active = zoneNodes.filter(node => node.is_active);
      const inactive = zoneNodes.filter(node => !node.is_active);
      const zone = zoneLookup.get(zoneId) || {};
      const items = zoneNodes
        .slice()
        .sort((a, b) => Number(b.is_active) - Number(a.is_active) || Number(b.confidence || 0) - Number(a.confidence || 0))
        .map(node => `
          <li class="${node.is_active ? 'is-active' : ''}">
            <span>${fmt(node.label)}</span>
            <small>${node.is_active ? 'active' : 'inactive'} / ${pct(node.confidence)} / ${fmt(node.evidence_count)} evidence</small>
          </li>`).join('');
      return `
        <section class="lii-zone-band">
          <div class="lii-zone-head">
            <div>
              <h3>${fmt(zone.label || zoneId)}</h3>
              <p>${fmt(zone.description)}</p>
            </div>
            <span>${active.length} active / ${inactive.length} inactive</span>
          </div>
          <ul class="lii-zone-list">${items}</ul>
        </section>`;
    }).join('');
  }

  function renderPolicyLayer(intentData) {
    const graph = intentData.intent_graph || {};
    const activation = graph.latest_activation || {};
    const harness = intentData.intent_harness || {};
    const latestReward = harness.latest_reward || null;
    const policies = asArray(harness.policies);
    const active = asArray(activation.active_intents);
    const policyRows = policies
      .slice()
      .sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0))
      .map(policy => `
        <article class="lii-policy-row">
          <div>
            <strong>${fmt(policy.label)}</strong>
            <span>${fmt(policy.policy_id)}</span>
          </div>
          <div class="lii-policy-metrics">
            <span>weight ${pct(policy.weight)}</span>
            <span>avg ${pct(policy.average_reward)}</span>
            <span>${fmt(policy.reward_count)} rewards</span>
          </div>
        </article>`).join('');
    const activeRows = active.map(item => `
      <li>
        <span>${fmt(item.label)}</span>
        <small>${fmt(item.zone)} / score ${fmt(item.score)} / ${fmt(item.reason)}</small>
      </li>`).join('');
    return `
      <div class="lii-policy-grid">
        <section class="lii-subpanel">
          <h3>Latest activation</h3>
          ${activeRows ? `<ul class="lii-zone-list">${activeRows}</ul>` : emptyState('No active intents in latest activation', PATHS.wiki)}
        </section>
        <section class="lii-subpanel">
          <h3>Reward state</h3>
          ${latestReward ? `
            <div class="lii-reward-card">
              <strong>${pct(latestReward.overall_reward)}</strong>
              <span>${fmt(latestReward.diagnosis)}</span>
              <code>${fmt(latestReward.plan_id)}</code>
            </div>` : emptyState('No reward ledger entry yet', 'D:\\ai-native chrome\\brain\\intent_harness\\reward_ledger.jsonl')}
          <div class="lii-policy-list">${policyRows || emptyState('No policies configured', 'D:\\ai-native chrome\\brain\\intent_harness\\policies.json')}</div>
        </section>
      </div>`;
  }

  function renderFeedback(events) {
    if (!events.length) {
      return emptyState('No raw feedback events', PATHS.feedback, 'Submit thumbs up/down from a hand card or emit feedback.signal from an adapter.');
    }
    return events.slice().reverse().map(event => {
      const type = event.type || event.signal || 'feedback';
      const vote = event.vote || event.signal || '';
      return `
        <article class="lii-feedback-row">
          <div class="lii-feedback-mark">${esc(String(vote || type).slice(0, 2).toUpperCase())}</div>
          <div>
            <strong>${fmt(event.hand_id || event.episode_id || 'unscoped')}</strong>
            <span>${fmt(type)}${vote ? ` / ${fmt(vote)}` : ''}</span>
            ${event.note || event.comment ? `<p>${fmt(event.note || event.comment)}</p>` : ''}
          </div>
          <code>${fmt(event.ts)}</code>
        </article>`;
    }).join('');
  }

  function renderFlywheel(records) {
    if (!records.length) return emptyState('No flywheel episodes', PATHS.flywheel, 'Run /analyze to create episode records.');
    const rows = records.map(record => `
      <tr>
        <td><code>${shortId(record.episode_id, 24)}</code></td>
        <td><code>${shortId(record.goal_id, 20)}</code></td>
        <td>${fmt(record.domain)}</td>
        <td>${fmt(record.stance)}</td>
        <td>${pct(record.confidence)}</td>
        <td>${fmt(record.hand_count)}</td>
        <td>${record.cold_start ? 'yes' : 'no'}</td>
      </tr>`).join('');
    return `
      <div class="lii-table-wrap">
        <table class="lii-ledger-table">
          <thead><tr><th>Episode</th><th>Goal</th><th>Domain</th><th>Stance</th><th>Confidence</th><th>Hands</th><th>Cold</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function renderGoals(goals, flywheelRecords) {
    if (!goals.length) return emptyState('No goal attribution records', 'D:\\ai-native chrome\\brain\\goal_context');
    return `
      <div class="lii-goal-grid">
        ${goals.map(goal => {
          const episodeIds = flywheelRecords
            .filter(record => record.goal_id && record.goal_id === goal.goal_id)
            .map(record => record.episode_id)
            .filter(Boolean);
          const episodeList = episodeIds.length
            ? `<div class="lii-episode-links">${episodeIds.slice(0, 8).map(id => `<code>${shortId(id, 22)}</code>`).join('')}</div>`
            : `<span class="lii-muted">No linked episodes in the current flywheel window.</span>`;
          return `
          <article class="lii-goal-card">
            <div>
              <strong>${fmt(goal.title || goal.goal_id)}</strong>
              <span>${fmt(goal.goal_type)} / ${fmt(goal.status)}</span>
            </div>
            <div class="lii-goal-meta">
              <span>${fmt(goal.episode_count)} episodes</span>
              <span>${fmt(goal.latest_stance)}</span>
            </div>
            <code>${fmt(goal.goal_id)}</code>
            ${episodeList}
          </article>`;
        }).join('')}
      </div>`;
  }

  function renderPage(data) {
    const intentData = data.intent.data || {};
    const graph = intentData.intent_graph || {};
    const nodes = asArray(graph.nodes);
    const zones = asArray(graph.zones);
    const activeNodes = nodes.filter(node => node.is_active);
    const feedbackEvents = asArray((data.feedback.data || {}).events);
    const flywheelRecords = asArray((data.flywheel.data || {}).records);
    const goals = asArray((data.goals.data || {}).goals);
    const reward = (intentData.intent_harness || {}).latest_reward;

    return `
      <section class="lii-page">
        <div class="lii-hero">
          <div>
            <span class="lii-eyebrow">Loom Intelligence Ledger</span>
            <h1>Intent Wiki + Feedback Attribution</h1>
            <p>Read-only view over durable intent state, raw feedback, flywheel episodes, and goal attribution.</p>
          </div>
          <button class="btn btn--sm btn--brand" type="button" data-lii-refresh>
            <i class="ph-bold ph-arrow-clockwise"></i> Refresh
          </button>
        </div>

        <div class="lii-stat-strip">
          ${renderStat('Intent nodes', nodes.length, 'ph-tree-structure')}
          ${renderStat('Active intents', activeNodes.length, 'ph-lightning', 'lii-stat--hot')}
          ${renderStat('Feedback events', feedbackEvents.length, 'ph-thumbs-up', 'lii-stat--feedback')}
          ${renderStat('Flywheel episodes', flywheelRecords.length, 'ph-database', 'lii-stat--ledger')}
          ${renderStat('Latest reward', reward ? pct(reward.overall_reward) : '-', 'ph-gauge', 'lii-stat--reward')}
        </div>

        <section class="lii-panel">
          <div class="lii-panel-head">
            <div><span>Intent Wiki</span><h2>Layered intent structure</h2></div>
            <code>${esc(PATHS.wiki)}</code>
          </div>
          <div class="lii-layer-grid">
            <section class="lii-layer lii-layer--wide">
              <h3>Metadata layer</h3>
              ${renderMetadataLayer(nodes, zones)}
            </section>
            <section class="lii-layer">
              <h3>Abstracted intent layer</h3>
              ${renderAbstractLayer(nodes, zones)}
            </section>
            <section class="lii-layer">
              <h3>Policy / activation layer</h3>
              ${renderPolicyLayer(intentData)}
            </section>
          </div>
        </section>

        <section class="lii-panel">
          <div class="lii-panel-head">
            <div><span>Feedback / Episode Attribution</span><h2>Recorded correction signals</h2></div>
            <code>${esc(PATHS.feedback)}</code>
          </div>
          <div class="lii-feedback-grid">
            <section class="lii-layer">
              <h3>Raw feedback</h3>
              ${renderFeedback(feedbackEvents)}
            </section>
            <section class="lii-layer lii-layer--wide">
              <h3>Episode ledger</h3>
              ${renderFlywheel(flywheelRecords)}
            </section>
            <section class="lii-layer lii-layer--wide">
              <h3>Goal attribution</h3>
              ${renderGoals(goals, flywheelRecords)}
            </section>
          </div>
        </section>
      </section>`;
  }

  const LoomIntelligencePage = {
    async renderInto(anchor) {
      const container = anchor?.container || document.getElementById('anchor-content');
      if (!container) return;
      container.innerHTML = `
        <section class="lii-page">
          <div class="lii-loading">
            <i class="ph-bold ph-spinner-gap"></i>
            <span>Loading intelligence ledger...</span>
          </div>
        </section>`;

      const [intent, feedback, flywheel, goals] = await Promise.all([
        safeFetch(URLS.intent),
        safeFetch(URLS.feedback),
        safeFetch(URLS.flywheel),
        safeFetch(URLS.goals),
      ]);
      const results = { intent, feedback, flywheel, goals };

      if (!results.intent.ok && !results.feedback.ok && !results.flywheel.ok && !results.goals.ok) {
        container.innerHTML = errorState(results);
      } else {
        for (const key of Object.keys(results)) {
          if (!results[key].ok) results[key].data = {};
        }
        container.innerHTML = renderPage(results);
      }
      container.querySelector('[data-lii-refresh]')?.addEventListener('click', () => this.renderInto(anchor));
    },
  };

  window.LoomIntelligencePage = LoomIntelligencePage;
})();
