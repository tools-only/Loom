const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, 'target-debate-page.js');

function loadModule() {
  const sandbox = { window: {}, module: { exports: {} }, exports: {} };
  const source = fs.readFileSync(sourcePath, 'utf8');
  vm.runInNewContext(source, sandbox, { filename: sourcePath });
  return sandbox.module.exports;
}

test('renders a dedicated #targeted Brain target debate page separate from legacy target cards', () => {
  const { renderTargetDebatePage } = loadModule();

  const html = renderTargetDebatePage({
    ticker: 'TSLA',
    source: 'hot-target',
    optionalSeed: 'delivery rebound',
  });

  assert.match(html, /data-anc="targeted\.debate"/);
  assert.match(html, /data-target-feature="brain-target-debate"/);
  assert.doesNotMatch(html, /data-anc="target\.card\./);
  assert.match(html, /Brain-owned target debate/i);
  assert.match(html, /TSLA/);
  assert.match(html, /delivery rebound/);
});

test('exposes Brain-owned agent roles, outputs, and monitoring conditions', () => {
  const { buildTargetDebatePlan, renderTargetDebatePage } = loadModule();

  const plan = buildTargetDebatePlan({ ticker: 'NVDA' });
  const html = renderTargetDebatePage({ ticker: 'NVDA' });

  assert.equal(plan.owner, 'brain');
  assert.deepEqual(
    Array.from(plan.roles, (role) => String(role.id)),
    [
      'target-profile-scout',
      'bull-evidence-scout',
      'bear-evidence-scout',
      'valuation-scout',
      'flow-sentiment-scout',
      'skeptic-reviewer',
      'debate-judge',
    ],
  );
  assert.ok(plan.outputs.includes('watch_conditions'));
  assert.ok(plan.outputs.includes('reversal_conditions'));
  assert.match(html, /bull-evidence-scout/);
  assert.match(html, /bear-evidence-scout/);
  assert.match(html, /skeptic-reviewer/);
  assert.match(html, /watch conditions/i);
  assert.match(html, /reversal conditions/i);
});

test('anchor client binds targeted hash route without replacing the target inbox route', () => {
  const anchorClient = fs.readFileSync(path.join(__dirname, 'anchor-client.js'), 'utf8');
  const indexHtml = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

  assert.match(anchorClient, /route\s*===\s*'targeted'/);
  assert.match(anchorClient, /TargetDebatePage\.renderInto/);
  assert.match(anchorClient, /\['market','position','target','sentiment'\]\.includes\(route\)/);
  assert.match(indexHtml, /target-debate-page\.js/);
});

test('provides market groups, searchable symbols, and multi-select target state', () => {
  const {
    buildTargetUniverse,
    createTargetSelection,
    filterTargetUniverse,
    renderTargetDebatePage,
  } = loadModule();

  const universe = buildTargetUniverse();
  assert.equal(universe.length, 4);
  assert.ok(universe.some((group) => group.id === 'us'));
  assert.ok(universe.some((group) => group.id === 'hk'));
  assert.ok(universe.some((group) => group.id === 'a-share'));
  assert.ok(universe.some((group) => group.id === 'japan-korea'));
  assert.ok(universe.some((group) => Array.from(group.targets, (t) => t.ticker).includes('NVDA')));
  assert.ok(universe.some((group) => Array.from(group.targets, (t) => t.ticker).includes('700.HK')));
  assert.ok(universe.some((group) => Array.from(group.targets, (t) => t.ticker).includes('600519.SS')));
  assert.ok(universe.some((group) => Array.from(group.targets, (t) => t.ticker).includes('7203.T')));
  assert.ok(universe.flatMap((group) => group.targets).length >= 90);
  assert.ok(
    universe.flatMap((group) => group.targets).every((target) => (
      target.asset_type &&
      target.market &&
      target.venue
    )),
  );

  const selection = createTargetSelection(['nvda', ' tsla ']);
  assert.deepEqual(Array.from(selection.selected), ['NVDA', 'TSLA']);
  selection.toggle('NVDA');
  selection.add('msft');
  assert.deepEqual(Array.from(selection.selected), ['TSLA', 'MSFT']);

  const filtered = filterTargetUniverse('semi');
  assert.ok(filtered.some((target) => target.ticker === 'NVDA'));

  const html = renderTargetDebatePage({ tickers: ['NVDA', 'TSLA'] });
  assert.match(html, /data-anc="targeted\.market-selector"/);
  assert.match(html, /id="targeted-symbol-search"/);
  assert.match(html, /data-target-ticker="NVDA"/);
  assert.match(html, /data-target-ticker="TSLA"/);
  assert.match(html, /data-selected-targets="NVDA,TSLA"/);
});

test('legacy target route embeds the reusable target selector before existing target cards', () => {
  const anchorClient = fs.readFileSync(path.join(__dirname, 'anchor-client.js'), 'utf8');
  const { renderTargetSelector } = loadModule();
  const selectorHtml = renderTargetSelector({ tickers: ['NVDA'] });

  assert.match(selectorHtml, /<style[^>]*data-target-debate-selector-style/);
  assert.match(selectorHtml, /data-market-bucket="us"/);
  assert.match(selectorHtml, /data-market-bucket="hk"/);
  assert.match(selectorHtml, /data-market-bucket="a-share"/);
  assert.match(selectorHtml, /data-market-bucket="japan-korea"/);
  assert.match(selectorHtml, /data-active-market="us"/);
  assert.match(selectorHtml, /target-market-menu-card/);
  assert.match(selectorHtml, /data-anc="targeted\.market-selector"/);
  assert.match(selectorHtml, /id="targeted-symbol-search"/);
  assert.match(anchorClient, /TargetDebatePage\.renderTargetSelector/);
  assert.match(anchorClient, /TargetDebatePage\.hydrate/);
  assert.match(anchorClient, /domain === 'target'/);
});

test('target page renders the selector as a global band rather than inside the blog grid', () => {
  const { renderTargetSelector } = loadModule();
  const selectorHtml = renderTargetSelector({ tickers: ['NVDA'] });

  assert.match(selectorHtml, /target-market-menu-card/);
  assert.match(selectorHtml, /target-market-panel/);
  assert.match(selectorHtml, /data-market-bucket="us"/);
  assert.match(selectorHtml, /data-active-market="us"/);
});

test('states that targeted debate reuses the existing Brain-Hand runtime', () => {
  const { buildTargetDebatePlan, renderTargetDebatePage } = loadModule();

  const plan = buildTargetDebatePlan({ ticker: 'AMD' });
  const html = renderTargetDebatePage({ ticker: 'AMD' });

  assert.equal(plan.runtime_strategy, 'reuse-existing-brain-hand');
  assert.match(html, /existing Brain-Hand runtime/i);
  assert.match(html, /adapter-abstracted hands/i);
  assert.doesNotMatch(html, /rewrite/i);
});

test('builds a Brain analyze request for selected targets through the existing proxy', () => {
  const { buildBrainAnalyzeRequest } = loadModule();

  const req = buildBrainAnalyzeRequest({
    tickers: ['NVDA', '600519.SS'],
    optionalSeed: 'margin pressure versus policy shock',
  });

  assert.equal(req.endpoint, '/loom/analyze');
  assert.equal(req.body.domain_hint, 'targeted');
  assert.equal(Object.prototype.hasOwnProperty.call(req.body, 'hands'), false);
  assert.match(req.body.question, /NVDA, 600519\.SS/);
  assert.match(req.body.question, /adapter-abstracted hands/i);
  assert.equal(req.body.context.goal_type, 'target_research_debate');
  assert.deepEqual(Array.from(req.body.context.selected_tickers), ['NVDA', '600519.SS']);
  assert.equal(req.body.context.selected_target_profiles[0].ticker, 'NVDA');
  assert.equal(req.body.context.selected_target_profiles[0].venue, 'NASDAQ');
  assert.equal(req.body.context.selected_target_profiles[1].ticker, '600519.SS');
  assert.equal(req.body.context.selected_target_profiles[1].market_bucket, 'a-share');
  assert.equal(req.body.context.target_debate_plan.owner, 'brain');
  assert.equal(req.body.context.runtime_strategy, 'reuse-existing-brain-hand');
});

test('submits the targeted debate request to Brain without requiring extra API config', async () => {
  const { submitTargetDebate } = loadModule();
  const calls = [];
  const result = await submitTargetDebate(
    { tickers: ['AMD'] },
    async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        async json() {
          return { ok: true, episode_id: 'ep_1', goal_id: 'goal_1', synthesis: { stance: 'watch' } };
        },
      };
    },
  );

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/loom/analyze');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(JSON.parse(calls[0].options.body).context.selected_tickers[0], 'AMD');
  assert.equal(result.episode_id, 'ep_1');
  assert.equal(result.goal_id, 'goal_1');
});
