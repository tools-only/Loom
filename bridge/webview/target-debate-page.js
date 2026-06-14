(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TargetDebatePage = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeTicker(value) {
    const clean = String(value || '').trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '');
    return clean || 'TSLA';
  }

  function target(ticker, name, tags, venue, market, assetType) {
    return {
      ticker,
      name,
      tags,
      venue,
      market,
      asset_type: assetType || 'equity',
    };
  }

  const TARGET_UNIVERSE = [
    {
      id: 'us-mega-cap',
      label: 'US Mega Cap',
      description: 'High-liquidity targets where news, filings, sentiment, and valuation data are usually available.',
      targets: [
        target('NVDA', 'NVIDIA', ['AI', 'semis', 'mega-cap'], 'NASDAQ', 'US'),
        target('MSFT', 'Microsoft', ['AI', 'cloud', 'mega-cap'], 'NASDAQ', 'US'),
        target('AAPL', 'Apple', ['consumer', 'hardware', 'mega-cap'], 'NASDAQ', 'US'),
        target('AMZN', 'Amazon', ['cloud', 'retail', 'mega-cap'], 'NASDAQ', 'US'),
        target('META', 'Meta Platforms', ['ads', 'AI', 'mega-cap'], 'NASDAQ', 'US'),
        target('GOOGL', 'Alphabet', ['ads', 'search', 'AI'], 'NASDAQ', 'US'),
        target('BRK.B', 'Berkshire Hathaway', ['insurance', 'conglomerate', 'value'], 'NYSE', 'US'),
        target('LLY', 'Eli Lilly', ['healthcare', 'obesity', 'mega-cap'], 'NYSE', 'US'),
      ],
    },
    {
      id: 'ai-semiconductors',
      label: 'AI & Semiconductors',
      description: 'Compute, memory, EDA, and semiconductor supply-chain names for evidence-heavy debate.',
      targets: [
        target('AMD', 'Advanced Micro Devices', ['AI', 'semis', 'compute'], 'NASDAQ', 'US'),
        target('AVGO', 'Broadcom', ['AI', 'semis', 'networking'], 'NASDAQ', 'US'),
        target('TSM', 'Taiwan Semiconductor', ['foundry', 'semis', 'supply-chain'], 'NYSE', 'US ADR'),
        target('ASML', 'ASML', ['equipment', 'semis', 'lithography'], 'NASDAQ', 'US ADR'),
        target('MU', 'Micron', ['memory', 'semis', 'cycle'], 'NASDAQ', 'US'),
        target('ARM', 'Arm Holdings', ['IP', 'semis', 'mobile'], 'NASDAQ', 'US ADR'),
        target('MRVL', 'Marvell Technology', ['AI', 'networking', 'semis'], 'NASDAQ', 'US'),
        target('QCOM', 'Qualcomm', ['mobile', 'edge AI', 'semis'], 'NASDAQ', 'US'),
        target('INTC', 'Intel', ['foundry', 'PC', 'turnaround'], 'NASDAQ', 'US'),
        target('SMCI', 'Super Micro Computer', ['AI servers', 'hardware', 'volatile'], 'NASDAQ', 'US'),
      ],
    },
    {
      id: 'software-cloud-security',
      label: 'Software / Cloud / Security',
      description: 'High-multiple software names where growth durability, AI attach, and margin leverage drive debate.',
      targets: [
        target('PLTR', 'Palantir', ['AI', 'software', 'government'], 'NASDAQ', 'US'),
        target('CRM', 'Salesforce', ['SaaS', 'enterprise', 'AI'], 'NYSE', 'US'),
        target('NOW', 'ServiceNow', ['workflow', 'enterprise', 'AI'], 'NYSE', 'US'),
        target('SNOW', 'Snowflake', ['data cloud', 'software', 'AI'], 'NYSE', 'US'),
        target('CRWD', 'CrowdStrike', ['security', 'cloud', 'endpoint'], 'NASDAQ', 'US'),
        target('PANW', 'Palo Alto Networks', ['security', 'platform', 'firewall'], 'NASDAQ', 'US'),
        target('DDOG', 'Datadog', ['observability', 'cloud', 'software'], 'NASDAQ', 'US'),
        target('NET', 'Cloudflare', ['edge', 'security', 'network'], 'NYSE', 'US'),
      ],
    },
    {
      id: 'ev-autonomy',
      label: 'EV & Autonomy',
      description: 'Targets where delivery data, margin pressure, policy, and narrative changes matter.',
      targets: [
        target('TSLA', 'Tesla', ['EV', 'autonomy', 'mega-cap'], 'NASDAQ', 'US'),
        target('RIVN', 'Rivian', ['EV', 'growth', 'cash-burn'], 'NASDAQ', 'US'),
        target('LI', 'Li Auto', ['China ADR', 'EV', 'deliveries'], 'NASDAQ', 'US ADR'),
        target('NIO', 'NIO', ['China ADR', 'EV', 'deliveries'], 'NYSE', 'US ADR'),
        target('XPEV', 'XPeng', ['China ADR', 'EV', 'autonomy'], 'NYSE', 'US ADR'),
        target('BYDDY', 'BYD', ['China', 'EV', 'battery'], 'OTC', 'US ADR'),
        target('GM', 'General Motors', ['auto', 'EV transition', 'legacy'], 'NYSE', 'US'),
        target('F', 'Ford', ['auto', 'EV transition', 'legacy'], 'NYSE', 'US'),
      ],
    },
    {
      id: 'china-adr-internet',
      label: 'China ADR / Internet',
      description: 'Policy, consumption, competition, buyback, and sentiment-driven targets.',
      targets: [
        target('BABA', 'Alibaba', ['China ADR', 'internet', 'commerce'], 'NYSE', 'US ADR'),
        target('PDD', 'PDD Holdings', ['China ADR', 'commerce', 'growth'], 'NASDAQ', 'US ADR'),
        target('JD', 'JD.com', ['China ADR', 'retail', 'logistics'], 'NASDAQ', 'US ADR'),
        target('BIDU', 'Baidu', ['China ADR', 'AI', 'search'], 'NASDAQ', 'US ADR'),
        target('TCEHY', 'Tencent', ['China', 'internet', 'gaming'], 'OTC', 'US ADR'),
        target('NTES', 'NetEase', ['China ADR', 'gaming', 'internet'], 'NASDAQ', 'US ADR'),
        target('BILI', 'Bilibili', ['China ADR', 'video', 'youth'], 'NASDAQ', 'US ADR'),
        target('TCOM', 'Trip.com', ['China ADR', 'travel', 'consumption'], 'NASDAQ', 'US ADR'),
      ],
    },
    {
      id: 'a-share-hk-core',
      label: 'China A / HK Core',
      description: 'China mainland and Hong Kong symbols for policy, consumption, and local-market narratives.',
      targets: [
        target('600519.SS', 'Kweichow Moutai', ['A-share', 'consumer', 'baijiu'], 'SSE', 'China'),
        target('300750.SZ', 'CATL', ['A-share', 'battery', 'EV'], 'SZSE', 'China'),
        target('000858.SZ', 'Wuliangye', ['A-share', 'consumer', 'baijiu'], 'SZSE', 'China'),
        target('601318.SS', 'Ping An Insurance', ['A-share', 'financials', 'insurance'], 'SSE', 'China'),
        target('600036.SS', 'China Merchants Bank', ['A-share', 'bank', 'financials'], 'SSE', 'China'),
        target('000333.SZ', 'Midea Group', ['A-share', 'home appliance', 'consumer'], 'SZSE', 'China'),
        target('601398.SS', 'ICBC', ['A-share', 'bank', 'financials'], 'SSE', 'China'),
        target('601939.SS', 'CCB', ['A-share', 'bank', 'financials'], 'SSE', 'China'),
        target('601288.SS', 'Agricultural Bank of China', ['A-share', 'bank', 'financials'], 'SSE', 'China'),
        target('600276.SS', 'Hengrui Pharma', ['A-share', 'pharma', 'healthcare'], 'SSE', 'China'),
        target('600887.SS', 'Yili', ['A-share', 'consumer', 'dairy'], 'SSE', 'China'),
        target('601888.SS', 'China Tourism Group Duty Free', ['A-share', 'consumer', 'travel'], 'SSE', 'China'),
        target('000002.SZ', 'Vanke', ['A-share', 'property', 'real-estate'], 'SZSE', 'China'),
        target('601166.SS', 'Industrial Bank', ['A-share', 'bank', 'financials'], 'SSE', 'China'),
        target('700.HK', 'Tencent Holdings', ['HK', 'internet', 'gaming'], 'HKEX', 'Hong Kong'),
        target('9988.HK', 'Alibaba Group', ['HK', 'commerce', 'internet'], 'HKEX', 'Hong Kong'),
        target('3690.HK', 'Meituan', ['HK', 'local services', 'consumption'], 'HKEX', 'Hong Kong'),
        target('1211.HK', 'BYD Company', ['HK', 'EV', 'battery'], 'HKEX', 'Hong Kong'),
        target('0941.HK', 'China Mobile', ['HK', 'telecom', 'defensive'], 'HKEX', 'Hong Kong'),
        target('0388.HK', 'HKEX', ['HK', 'exchange', 'market-infra'], 'HKEX', 'Hong Kong'),
        target('2318.HK', 'Ping An Insurance', ['HK', 'insurance', 'financials'], 'HKEX', 'Hong Kong'),
        target('9618.HK', 'JD.com', ['HK', 'commerce', 'internet'], 'HKEX', 'Hong Kong'),
        target('9999.HK', 'NetEase', ['HK', 'gaming', 'internet'], 'HKEX', 'Hong Kong'),
        target('1810.HK', 'Xiaomi', ['HK', 'hardware', 'consumer-tech'], 'HKEX', 'Hong Kong'),
        target('9888.HK', 'Baidu', ['HK', 'AI', 'search'], 'HKEX', 'Hong Kong'),
        target('1024.HK', 'Kuaishou', ['HK', 'video', 'ads'], 'HKEX', 'Hong Kong'),
        target('9961.HK', 'Trip.com', ['HK', 'travel', 'internet'], 'HKEX', 'Hong Kong'),
      ],
    },
    {
      id: 'healthcare-biotech',
      label: 'Healthcare / Biotech',
      description: 'Drug launches, trial data, reimbursement, and growth multiple debates.',
      targets: [
        target('NVO', 'Novo Nordisk', ['obesity', 'diabetes', 'pharma'], 'NYSE', 'US ADR'),
        target('UNH', 'UnitedHealth', ['managed care', 'healthcare', 'policy'], 'NYSE', 'US'),
        target('JNJ', 'Johnson & Johnson', ['pharma', 'medtech', 'defensive'], 'NYSE', 'US'),
        target('MRK', 'Merck', ['pharma', 'oncology', 'pipeline'], 'NYSE', 'US'),
        target('ABBV', 'AbbVie', ['pharma', 'immunology', 'pipeline'], 'NYSE', 'US'),
        target('REGN', 'Regeneron', ['biotech', 'pipeline', 'specialty'], 'NASDAQ', 'US'),
        target('ISRG', 'Intuitive Surgical', ['medtech', 'robotics', 'surgery'], 'NASDAQ', 'US'),
        target('VRTX', 'Vertex', ['biotech', 'rare disease', 'pipeline'], 'NASDAQ', 'US'),
      ],
    },
    {
      id: 'financials-fintech',
      label: 'Financials / Fintech',
      description: 'Rates, credit, capital return, payments, and regulatory pressure.',
      targets: [
        target('JPM', 'JPMorgan Chase', ['bank', 'rates', 'credit'], 'NYSE', 'US'),
        target('BAC', 'Bank of America', ['bank', 'rates', 'credit'], 'NYSE', 'US'),
        target('GS', 'Goldman Sachs', ['investment bank', 'capital markets', 'trading'], 'NYSE', 'US'),
        target('MS', 'Morgan Stanley', ['wealth', 'capital markets', 'bank'], 'NYSE', 'US'),
        target('V', 'Visa', ['payments', 'consumer', 'network'], 'NYSE', 'US'),
        target('MA', 'Mastercard', ['payments', 'consumer', 'network'], 'NYSE', 'US'),
        target('AXP', 'American Express', ['payments', 'credit', 'consumer'], 'NYSE', 'US'),
        target('HOOD', 'Robinhood', ['brokerage', 'retail trading', 'crypto'], 'NASDAQ', 'US'),
      ],
    },
    {
      id: 'consumer-retail-media',
      label: 'Consumer / Retail / Media',
      description: 'Consumer spending, brand strength, advertising, and margin resilience.',
      targets: [
        target('WMT', 'Walmart', ['retail', 'consumer', 'defensive'], 'NYSE', 'US'),
        target('COST', 'Costco', ['retail', 'membership', 'defensive'], 'NASDAQ', 'US'),
        target('HD', 'Home Depot', ['housing', 'retail', 'consumer'], 'NYSE', 'US'),
        target('NKE', 'Nike', ['apparel', 'brand', 'turnaround'], 'NYSE', 'US'),
        target('SBUX', 'Starbucks', ['restaurants', 'China', 'consumer'], 'NASDAQ', 'US'),
        target('MCD', 'McDonald\'s', ['restaurants', 'defensive', 'franchise'], 'NYSE', 'US'),
        target('DIS', 'Disney', ['media', 'parks', 'streaming'], 'NYSE', 'US'),
        target('NFLX', 'Netflix', ['streaming', 'media', 'ads'], 'NASDAQ', 'US'),
      ],
    },
    {
      id: 'energy-industrials-materials',
      label: 'Energy / Industrials / Materials',
      description: 'Commodity cycles, capex, industrial policy, and operating leverage.',
      targets: [
        target('XOM', 'Exxon Mobil', ['energy', 'oil', 'dividend'], 'NYSE', 'US'),
        target('CVX', 'Chevron', ['energy', 'oil', 'dividend'], 'NYSE', 'US'),
        target('SLB', 'SLB', ['oil services', 'energy', 'cycle'], 'NYSE', 'US'),
        target('CAT', 'Caterpillar', ['industrial', 'machinery', 'cycle'], 'NYSE', 'US'),
        target('GE', 'GE Aerospace', ['aerospace', 'industrial', 'engines'], 'NYSE', 'US'),
        target('BA', 'Boeing', ['aerospace', 'turnaround', 'execution'], 'NYSE', 'US'),
        target('FCX', 'Freeport-McMoRan', ['copper', 'materials', 'cycle'], 'NYSE', 'US'),
        target('NEM', 'Newmont', ['gold', 'miner', 'macro'], 'NYSE', 'US'),
      ],
    },
    {
      id: 'global-adr-em',
      label: 'Global ADR / EM',
      description: 'Non-US growth, commodity, and financial proxies with country-specific risk.',
      targets: [
        target('MELI', 'MercadoLibre', ['LatAm', 'commerce', 'fintech'], 'NASDAQ', 'US'),
        target('NU', 'Nu Holdings', ['LatAm', 'fintech', 'banking'], 'NYSE', 'US'),
        target('PBR', 'Petrobras', ['Brazil', 'energy', 'dividend'], 'NYSE', 'US ADR'),
        target('VALE', 'Vale', ['Brazil', 'iron ore', 'materials'], 'NYSE', 'US ADR'),
        target('ITUB', 'Itau Unibanco', ['Brazil', 'bank', 'rates'], 'NYSE', 'US ADR'),
        target('SE', 'Sea Limited', ['Southeast Asia', 'gaming', 'commerce'], 'NYSE', 'US ADR'),
        target('GRAB', 'Grab', ['Southeast Asia', 'mobility', 'fintech'], 'NASDAQ', 'US'),
        target('INFY', 'Infosys', ['India', 'IT services', 'outsourcing'], 'NYSE', 'US ADR'),
      ],
    },
    {
      id: 'japan-korea',
      label: 'Japan / Korea',
      description: 'Japanese and Korean large caps for regional market debates and cross-market comparisons.',
      targets: [
        target('7203.T', 'Toyota', ['Japan', 'auto', 'global'], 'TSE', 'Japan'),
        target('6758.T', 'Sony Group', ['Japan', 'consumer-tech', 'gaming'], 'TSE', 'Japan'),
        target('9984.T', 'SoftBank Group', ['Japan', 'tech', 'holdco'], 'TSE', 'Japan'),
        target('7974.T', 'Nintendo', ['Japan', 'gaming', 'consumer-tech'], 'TSE', 'Japan'),
        target('9432.T', 'NTT', ['Japan', 'telecom', 'defensive'], 'TSE', 'Japan'),
        target('005930.KS', 'Samsung Electronics', ['Korea', 'semis', 'memory'], 'KRX', 'Korea'),
        target('000660.KS', 'SK hynix', ['Korea', 'semis', 'memory'], 'KRX', 'Korea'),
        target('035420.KS', 'Naver', ['Korea', 'internet', 'search'], 'KRX', 'Korea'),
        target('005380.KS', 'Hyundai Motor', ['Korea', 'auto', 'global'], 'KRX', 'Korea'),
        target('373220.KS', 'LG Energy Solution', ['Korea', 'battery', 'EV'], 'KRX', 'Korea'),
      ],
    },
    {
      id: 'hot-market-proxies',
      label: 'Hot Market Proxies',
      description: 'Index, crypto, and risk appetite proxies useful when the target is a market narrative.',
      targets: [
        target('QQQ', 'Nasdaq 100 ETF', ['ETF', 'growth', 'index'], 'NASDAQ', 'US', 'fund'),
        target('SPY', 'S&P 500 ETF', ['ETF', 'index', 'macro'], 'NYSEARCA', 'US', 'fund'),
        target('IWM', 'Russell 2000 ETF', ['ETF', 'small-cap', 'rates'], 'NYSEARCA', 'US', 'fund'),
        target('SMH', 'VanEck Semiconductor ETF', ['ETF', 'semis', 'AI'], 'NASDAQ', 'US', 'fund'),
        target('ARKK', 'ARK Innovation ETF', ['ETF', 'growth', 'speculative'], 'NYSEARCA', 'US', 'fund'),
        target('TLT', '20+ Year Treasury Bond ETF', ['ETF', 'rates', 'duration'], 'NASDAQ', 'US', 'fund'),
        target('GLD', 'Gold Shares ETF', ['ETF', 'gold', 'macro'], 'NYSEARCA', 'US', 'fund'),
        target('USO', 'Oil Fund ETF', ['ETF', 'oil', 'commodity'], 'NYSEARCA', 'US', 'fund'),
        target('FXI', 'China Large-Cap ETF', ['ETF', 'China', 'policy'], 'NYSEARCA', 'US', 'fund'),
        target('KWEB', 'China Internet ETF', ['ETF', 'China internet', 'sentiment'], 'NYSEARCA', 'US', 'fund'),
      ],
    },
    {
      id: 'crypto-risk',
      label: 'Crypto / Risk Assets',
      description: 'Crypto-linked equities and ETFs where flow, policy, and risk appetite dominate.',
      targets: [
        target('IBIT', 'iShares Bitcoin Trust', ['crypto', 'ETF', 'flow'], 'NASDAQ', 'US', 'fund'),
        target('FBTC', 'Fidelity Wise Origin Bitcoin Fund', ['crypto', 'ETF', 'flow'], 'NYSEARCA', 'US', 'fund'),
        target('COIN', 'Coinbase', ['crypto', 'exchange', 'risk'], 'NASDAQ', 'US'),
        target('MSTR', 'MicroStrategy', ['bitcoin proxy', 'leverage', 'software'], 'NASDAQ', 'US'),
        target('MARA', 'MARA Holdings', ['bitcoin miner', 'hashrate', 'crypto'], 'NASDAQ', 'US'),
        target('RIOT', 'Riot Platforms', ['bitcoin miner', 'hashrate', 'crypto'], 'NASDAQ', 'US'),
      ],
    },
  ];

  function buildTargetUniverse() {
    const marketMeta = {
      us: {
        id: 'us',
        label: '美股市场',
        description: 'U.S.-listed equities, ADRs, ETFs, and U.S. risk proxies.',
      },
      hk: {
        id: 'hk',
        label: '港股市场',
        description: 'Hong Kong listed names on HKEX, grouped for market-level debate and search.',
      },
      'a-share': {
        id: 'a-share',
        label: 'A股市场',
        description: 'Shanghai and Shenzhen A-shares, grouped for mainland market debate and search.',
      },
      'japan-korea': {
        id: 'japan-korea',
        label: '日韩市场',
        description: 'Japan and Korea large caps for regional market debate and search.',
      },
    };
    const buckets = { us: [], hk: [], 'a-share': [], 'japan-korea': [] };
    TARGET_UNIVERSE.flatMap(function (group) {
      return group.targets.map(function (target) {
        return { ...target, tags: target.tags.slice(), source_group: group.id, source_group_label: group.label };
      });
    }).forEach(function (target) {
      const bucket = inferMarketBucket(target);
      target.market_bucket = bucket;
      target.market_label = (marketMeta[bucket] && marketMeta[bucket].label) || bucket;
      (buckets[bucket] || buckets.us).push(target);
    });
    return ['us', 'hk', 'a-share', 'japan-korea'].map(function (bucket) {
      const meta = marketMeta[bucket] || {
        id: bucket,
        label: bucket,
        description: '',
      };
      return {
        id: meta.id,
        label: meta.label,
        description: meta.description,
        targets: buckets[bucket],
      };
    });
  }

  function createTargetSelection(initialTickers) {
    const selected = [];
    function has(ticker) {
      return selected.includes(normalizeTicker(ticker));
    }
    function add(ticker) {
      const clean = normalizeTicker(ticker);
      if (!selected.includes(clean)) selected.push(clean);
      return selected.slice();
    }
    function remove(ticker) {
      const clean = normalizeTicker(ticker);
      const idx = selected.indexOf(clean);
      if (idx !== -1) selected.splice(idx, 1);
      return selected.slice();
    }
    function toggle(ticker) {
      return has(ticker) ? remove(ticker) : add(ticker);
    }
    (initialTickers || []).forEach(add);
    return {
      selected,
      add,
      remove,
      toggle,
      has,
    };
  }

  function filterTargetUniverse(query) {
    const q = String(query || '').trim().toLowerCase();
    const all = buildTargetUniverse().flatMap(function (group) {
      return group.targets.map(function (target) {
        return { ...target, group_id: group.id, group_label: group.label };
      });
    });
    if (!q) return all;
    return all.filter(function (target) {
      return (
        target.ticker.toLowerCase().includes(q) ||
        target.name.toLowerCase().includes(q) ||
        target.tags.some(function (tag) { return tag.toLowerCase().includes(q); }) ||
        target.group_label.toLowerCase().includes(q)
      );
    });
  }

  function inferMarketBucket(target) {
    const ticker = String(target && target.ticker || '').toUpperCase();
    const venue = String(target && target.venue || '').toUpperCase();
    const market = String(target && target.market || '').toLowerCase();
    if (ticker.endsWith('.HK') || venue.includes('HKEX') || market.includes('hong kong')) return 'hk';
    if (ticker.endsWith('.SS') || ticker.endsWith('.SZ') || venue.includes('SSE') || venue.includes('SZSE') || market.includes('china')) return 'a-share';
    if (ticker.endsWith('.T') || ticker.endsWith('.KS') || ticker.endsWith('.KQ') || venue.includes('TSE') || venue.includes('KRX') || market.includes('japan') || market.includes('korea')) return 'japan-korea';
    return 'us';
  }

  function findTargetProfiles(tickers) {
    const all = buildTargetUniverse().flatMap(function (group) {
      return group.targets.map(function (item) {
        return { ...item, group_id: group.id, group_label: group.label };
      });
    });
    return (tickers || []).map(function (ticker) {
      const clean = normalizeTicker(ticker);
      const found = all.find(function (item) { return item.ticker === clean; });
      if (found) return found;
      return {
        ticker: clean,
        name: clean,
        tags: ['custom', 'user-entered'],
        venue: 'user-entered',
        market: 'custom',
        asset_type: 'unknown',
        market_bucket: 'custom',
        group_id: 'custom-search',
        group_label: 'Custom Search',
      };
    });
  }

  function buildTargetDebatePlan(input) {
    const selectedTickers = Array.isArray(input && input.tickers) && input.tickers.length
      ? createTargetSelection(input.tickers).selected
      : [normalizeTicker(input && input.ticker)];
    const ticker = selectedTickers[0];
    return {
      owner: 'brain',
      page: 'targeted',
      ticker,
      tickers: selectedTickers,
      active_market: 'us',
      target_profiles: findTargetProfiles(selectedTickers),
      runtime_strategy: 'reuse-existing-brain-hand',
      trigger: {
        source: (input && input.source) || 'selected-or-hot-target',
        optional_seed: (input && input.optionalSeed) || '',
      },
      research_questions: [
        'What is the current market narrative for this target?',
        'Which evidence supports the bull case and how fresh is it?',
        'Which evidence weakens or contradicts the bull case?',
        'What appears priced in versus still under-discounted?',
        'Which watch conditions or reversal conditions should Brain monitor next?',
      ],
      roles: [
        {
          id: 'target-profile-scout',
          label: 'Profile',
          brief: 'Build the company, catalyst, and event context before evidence agents branch out.',
        },
        {
          id: 'bull-evidence-scout',
          label: 'Bull',
          brief: 'Collect source-backed evidence that supports upside, improvement, or re-rating.',
        },
        {
          id: 'bear-evidence-scout',
          label: 'Bear',
          brief: 'Collect counter-evidence, risks, valuation pressure, and narrative failure modes.',
        },
        {
          id: 'valuation-scout',
          label: 'Valuation',
          brief: 'Compare expectations, revisions, multiple pressure, and event-implied risk.',
        },
        {
          id: 'flow-sentiment-scout',
          label: 'Flow',
          brief: 'Inspect price action, crowding, social tone, and unusual attention around the ticker.',
        },
        {
          id: 'skeptic-reviewer',
          label: 'Skeptic',
          brief: 'Audit stale sources, weak inference, missing evidence, and one-sided reasoning.',
        },
        {
          id: 'debate-judge',
          label: 'Judge',
          brief: 'Synthesize conflicts into a verdict, unresolved questions, and monitoring plan.',
        },
      ],
      outputs: [
        'bull_thesis',
        'bear_thesis',
        'evidence_table',
        'key_conflicts',
        'current_verdict',
        'watch_conditions',
        'reversal_conditions',
      ],
      resource_policy: [
        'Use SEC/Finnhub/Yahoo as the primary target resource layer where available.',
        'Use news, social, KOL, and price/volume signals as supporting evidence, not standalone proof.',
        'Require source tier, freshness, and claim linkage for every finding.',
      ],
    };
  }

  function buildBrainAnalyzeRequest(input) {
    const plan = buildTargetDebatePlan(input || {});
    const tickers = plan.tickers;
    const seed = plan.trigger.optional_seed;
    const question = [
      'Run a Brain-owned targeted research debate for: ' + tickers.join(', ') + '.',
      'Use the existing Loom Brain main-process agent and adapter-abstracted hands.',
      'Do not provide trading advice. Produce bull thesis, bear thesis, evidence table, conflicts, verdict, watch conditions, and reversal conditions.',
      seed ? 'Optional user seed: ' + seed : '',
    ].filter(Boolean).join('\n');
    return {
      endpoint: '/loom/analyze',
      body: {
        question,
        domain_hint: 'targeted',
        context: {
          goal_type: 'target_research_debate',
          route: 'targeted',
          selected_tickers: tickers,
          selected_target_profiles: plan.target_profiles,
          primary_ticker: plan.ticker,
          optional_seed: seed,
          runtime_strategy: plan.runtime_strategy,
          target_debate_plan: plan,
          tags: ['targeted', 'target', 'debate'].concat(tickers),
        },
      },
    };
  }

  async function submitTargetDebate(input, fetchFn) {
    const req = buildBrainAnalyzeRequest(input || {});
    const doFetch = fetchFn || (typeof fetch === 'function' ? fetch.bind(globalThis) : null);
    if (!doFetch) throw new Error('fetch is not available');
    const response = await doFetch(req.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
    });
    let data = {};
    try {
      data = await response.json();
    } catch (_) {
      data = {};
    }
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || ('Brain analyze failed with status ' + (response.status || 'unknown')));
    }
    return data;
  }

  function renderRole(role) {
    return [
      '<div class="anc-section anc-section--gc anc-section--arctic target-debate-role" data-anc="targeted.role.' + esc(role.id) + '" data-detail-disabled="true">',
      '<div class="target-debate-role-kicker">' + esc(role.label) + '</div>',
      '<h3>' + esc(role.id) + '</h3>',
      '<p>' + esc(role.brief) + '</p>',
      '</div>',
    ].join('');
  }

  function renderTargetButton(target, selected) {
    const active = selected.includes(target.ticker);
    const bucket = target.market_bucket || inferMarketBucket(target);
    return [
      '<button class="target-market-option' + (active ? ' is-selected' : '') + '" type="button" data-target-ticker="' + esc(target.ticker) + '" data-target-market-bucket="' + esc(bucket) + '" aria-pressed="' + (active ? 'true' : 'false') + '">',
      '<span class="target-market-symbol">' + esc(target.ticker) + '</span>',
      '<span class="target-market-name">' + esc(target.name) + '</span>',
      '<span class="target-market-tags">' + target.tags.map(esc).join(' / ') + '</span>',
      '</button>',
    ].join('');
  }

  function renderTargetMarketPanel(group, selected) {
    if (!group) return '';
    return [
      '<div class="target-market-panel" data-market-panel="' + esc(group.id) + '">',
      '<div class="target-market-panel-head">',
      '<div>',
      '<h3>' + esc(group.label) + '</h3>',
      '<p>' + esc(group.description) + '</p>',
      '</div>',
      '<div class="target-market-panel-count">' + esc(String(group.targets.length)) + ' symbols</div>',
      '</div>',
      '<div class="target-market-options">',
      group.targets.map(function (target) { return renderTargetButton(target, selected); }).join(''),
      '</div>',
      '</div>',
    ].join('');
  }

  function renderTargetMarketMenu(groups, activeBucket) {
    return [
      '<aside class="target-market-menu-card">',
      '<div class="blog-section-label"><i class="ph-bold ph-squares-four"></i> Markets</div>',
      '<div class="target-market-menu">',
      groups.map(function (group) {
        const active = group.id === activeBucket;
        return [
          '<button class="target-market-menu-button' + (active ? ' is-active' : '') + '" type="button" data-market-bucket="' + esc(group.id) + '" aria-pressed="' + (active ? 'true' : 'false') + '">',
          '<span class="target-market-menu-label">' + esc(group.label) + '</span>',
          '<span class="target-market-menu-count">' + esc(String(group.targets.length)) + '</span>',
          '</button>',
        ].join('');
      }).join(''),
      '</div>',
      '</aside>',
    ].join('');
  }

  function renderMarketSelector(plan) {
    const selected = plan.tickers || [plan.ticker];
    const groups = buildTargetUniverse();
    const activeBucket = plan.active_market || 'us';
    const activeGroup = groups.find(function (group) { return group.id === activeBucket; }) || groups[0];
    return [
      '<section class="anc-section anc-section--gc anc-section--aurora target-market-selector" data-anc="targeted.market-selector" data-detail-disabled="true" data-selected-targets="' + esc(selected.join(',')) + '" data-active-market="' + esc(activeBucket) + '">',
      '<div class="target-selector-head">',
      '<div>',
      '<div class="blog-section-label"><i class="ph-bold ph-list-magnifying-glass"></i> Target market</div>',
      '<h2>Choose one or more targets</h2>',
      '<p>Start from a curated market, or search any ticker. Brain will decide how to use adapter-abstracted hands for evidence collection and debate.</p>',
      '</div>',
      '<div class="target-search-box">',
      '<input id="targeted-symbol-search" class="target-symbol-search" type="search" placeholder="Search ticker, company, theme..." autocomplete="off">',
      '<button id="targeted-symbol-add" class="btn btn--sm btn--brand" type="button">Add</button>',
      '</div>',
      '</div>',
      '<div class="target-selector-layout">',
      renderTargetMarketMenu(groups, activeBucket),
      '<div class="target-market-display">',
      '<div id="targeted-market-panel" class="target-market-panel-stack">',
      renderTargetMarketPanel(activeGroup, selected),
      '</div>',
      '</div>',
      '</div>',
      '<div id="targeted-selected-targets" class="target-selected-row">',
      selected.map(function (ticker) { return '<span class="blog-ticker-tag">$' + esc(ticker) + '</span>'; }).join(''),
      '</div>',
      '<div id="targeted-search-results" class="target-search-results" hidden></div>',
      '</section>',
    ].join('');
  }

  function renderTargetSelectorStyles() {
    return [
      '<style data-target-debate-selector-style>',
      '.target-market-selector{--td-ink:#171717;--td-muted:#62646b;--td-line:rgba(23,23,23,.12);--td-accent:#0f766e;box-sizing:border-box;width:100%;max-width:none;grid-column:1/-1;align-self:stretch;color:var(--td-ink)}',
      '.target-market-selector *{box-sizing:border-box}',
      '.target-market-selector .target-selector-head{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,360px);gap:16px;align-items:start}',
      '.target-market-selector .target-selector-head h2{margin:4px 0 6px;font-size:22px;letter-spacing:0}',
      '.target-market-selector .target-selector-head p{margin:0;color:var(--td-muted);max-width:760px}',
      '.target-market-selector .target-search-box{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}',
      '.target-market-selector .target-symbol-search{min-width:0;width:100%;border:1px solid var(--td-line);border-radius:8px;padding:9px 11px;background:#fff;color:var(--td-ink)}',
      '.target-market-selector .target-selector-layout{display:grid;grid-template-columns:minmax(220px,280px) minmax(0,1fr);gap:12px;align-items:start;margin-top:16px}',
      '.target-market-selector .target-market-menu-card{border:1px solid var(--td-line);border-radius:8px;background:rgba(255,255,255,.72);padding:12px;min-width:0}',
      '.target-market-selector .target-market-menu{display:grid;gap:8px;margin-top:8px}',
      '.target-market-selector .target-market-menu-button{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;border:1px solid var(--td-line);border-radius:8px;background:#fff;padding:10px 12px;text-align:left;color:var(--td-ink);cursor:pointer}',
      '.target-market-selector .target-market-menu-button.is-active,.target-market-selector .target-market-menu-button:hover{border-color:var(--td-accent);box-shadow:0 0 0 2px rgba(15,118,110,.10)}',
      '.target-market-selector .target-market-menu-label{font-size:13px;font-weight:800;letter-spacing:0}',
      '.target-market-selector .target-market-menu-count,.target-market-selector .target-market-panel-count{font-size:11px;color:var(--td-muted);white-space:nowrap}',
      '.target-market-selector .target-market-display{min-width:0}',
      '.target-market-selector .target-market-panel-stack{min-width:0}',
      '.target-market-selector .target-market-panel{min-width:0;border:1px solid var(--td-line);border-radius:8px;background:rgba(255,255,255,.66);padding:14px}',
      '.target-market-selector .target-market-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}',
      '.target-market-selector .target-market-panel-head h3{font-size:16px;margin:0 0 4px}',
      '.target-market-selector .target-market-panel-head p{font-size:12px;color:var(--td-muted);margin:0;max-width:760px}',
      '.target-market-selector .target-selected-row{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}',
      '.target-market-selector .target-market-options{display:grid;gap:8px}',
      '.target-market-selector .target-market-option{display:grid;grid-template-columns:64px minmax(0,1fr);gap:2px 8px;width:100%;text-align:left;border:1px solid var(--td-line);border-radius:8px;background:#fff;padding:10px;cursor:pointer;color:var(--td-ink)}',
      '.target-market-selector .target-market-option:hover,.target-market-selector .target-market-option.is-selected{border-color:var(--td-accent);box-shadow:0 0 0 2px rgba(15,118,110,.10)}',
      '.target-market-selector .target-market-symbol{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:800;grid-row:span 2}',
      '.target-market-selector .target-market-name{font-size:13px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.target-market-selector .target-market-tags{font-size:11px;color:var(--td-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.target-market-selector .target-search-results{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin:10px 0 4px}',
      '@media (max-width:760px){.target-market-selector .target-selector-layout,.target-market-selector .target-selector-head{grid-template-columns:1fr}}',
      '</style>',
    ].join('');
  }

  function renderTargetSelector(input) {
    const plan = input && input.owner === 'brain'
      ? input
      : buildTargetDebatePlan(input || {});
    return renderTargetSelectorStyles() + renderMarketSelector(plan);
  }

  function renderTargetDebatePage(input) {
    const plan = buildTargetDebatePlan(input || {});
    const optionalSeed = plan.trigger.optional_seed
      ? '<span class="target-debate-seed">Seed: ' + esc(plan.trigger.optional_seed) + '</span>'
      : '<span class="target-debate-seed">Optional user seed can be added later</span>';

    return [
      '<div class="blog-page blog-page--targeted target-debate-page" data-target-feature="brain-target-debate">',
      '<style>',
      '.target-debate-page{--td-ink:#171717;--td-muted:#62646b;--td-line:rgba(23,23,23,.12);--td-accent:#0f766e;color:var(--td-ink)}',
      '.target-debate-hero{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:18px;align-items:stretch}',
      '.target-debate-hero h1{font-size:clamp(30px,4vw,52px);line-height:1.02;margin:8px 0 12px;letter-spacing:0}',
      '.target-debate-hero p{color:var(--td-muted);max-width:780px}',
      '.target-debate-panel{border:1px solid var(--td-line);border-radius:8px;background:rgba(255,255,255,.72);padding:18px}',
      '.target-debate-ticker{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:42px;font-weight:800}',
      '.target-debate-seed,.target-debate-pill{display:inline-flex;align-items:center;border:1px solid var(--td-line);border-radius:999px;padding:5px 10px;font-size:12px;color:var(--td-muted);background:#fff}',
      '.target-debate-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:18px}',
      '.target-debate-role{padding:16px;border-radius:8px}',
      '.target-debate-role h3{font-size:15px;margin:4px 0 8px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}',
      '.target-debate-role p{font-size:13px;color:var(--td-muted);margin:0}',
      '.target-debate-role-kicker{font-size:11px;text-transform:uppercase;font-weight:800;color:var(--td-accent)}',
      '.target-debate-list{display:grid;gap:8px;margin:12px 0 0;padding:0;list-style:none}',
      '.target-debate-list li{border-left:3px solid var(--td-accent);padding:6px 0 6px 10px;color:var(--td-muted)}',
      '.target-debate-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}',
      '.target-selector-head{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,360px);gap:16px;align-items:start}',
      '.target-selector-head h2{margin:4px 0 6px;font-size:22px;letter-spacing:0}',
      '.target-selector-head p{margin:0;color:var(--td-muted);max-width:760px}',
      '.target-search-box{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}',
      '.target-symbol-search{min-width:0;border:1px solid var(--td-line);border-radius:8px;padding:9px 11px;background:#fff;color:var(--td-ink)}',
      '.target-selected-row{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}',
      '.target-market-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:8px}',
      '.target-market-group{border:1px solid var(--td-line);border-radius:8px;background:rgba(255,255,255,.66);padding:14px}',
      '.target-market-group h3{font-size:15px;margin:0 0 4px}',
      '.target-market-group p{font-size:12px;color:var(--td-muted);margin:0 0 12px}',
      '.target-market-options{display:grid;gap:8px}',
      '.target-market-option{display:grid;grid-template-columns:64px minmax(0,1fr);gap:2px 8px;text-align:left;border:1px solid var(--td-line);border-radius:8px;background:#fff;padding:10px;cursor:pointer;color:var(--td-ink)}',
      '.target-market-option:hover,.target-market-option.is-selected{border-color:var(--td-accent);box-shadow:0 0 0 2px rgba(15,118,110,.10)}',
      '.target-market-symbol{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:800;grid-row:span 2}',
      '.target-market-name{font-size:13px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.target-market-tags{font-size:11px;color:var(--td-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.target-search-results{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin:10px 0 4px}',
      '@media (max-width:760px){.target-debate-hero{grid-template-columns:1fr}.target-debate-ticker{font-size:34px}}',
      '</style>',
      '<section class="anc-section anc-section--gc anc-section--warm target-debate-hero" data-anc="targeted.debate" data-handles="refine,annotate,branch" data-has-detail="true" data-agent-hand="brain-target-debate" data-agent-executor="brain" data-agent-domain="targeted" data-agent-kind="target-debate" data-agent-role="Brain designs the target debate plan, dispatches evidence scouts, reviews gaps, and persists target state.">',
      '<div>',
      '<span class="target-debate-pill">Brain-owned target debate</span>',
      '<h1>Targeted Research Debate</h1>',
      '<p>Brain owns the full program for selected or hot targets: framing the research questions, dispatching bull and bear evidence agents, challenging weak claims, and producing monitoring conditions without changing the existing target thesis page.</p>',
      '<p>Execution reuses the existing Brain-Hand runtime with adapter-abstracted hands; this page only scopes target selection and the debate intent.</p>',
      '<div class="target-debate-actions">',
      optionalSeed,
      '<span class="target-debate-pill">Source: ' + esc(plan.trigger.source) + '</span>',
      '</div>',
      '</div>',
      '<aside class="target-debate-panel">',
      '<div class="target-debate-role-kicker">Active target</div>',
      '<div class="target-debate-ticker">' + esc(plan.ticker) + '</div>',
      '<ul class="target-debate-list">',
      '<li>Target state and debate episodes stay Brain-side.</li>',
      '<li>User reasoning is optional context, not the required starting point.</li>',
      '<li>Outputs include watch conditions and reversal conditions.</li>',
      '</ul>',
      '<button id="targeted-run-brain" class="btn btn--brand btn--sm" type="button">Run Brain Debate</button>',
      '</aside>',
      '</section>',
      renderTargetSelector(plan),
      '<section class="anc-section anc-section--gc anc-section--cool" data-anc="targeted.plan" data-detail-disabled="true">',
      '<div class="blog-section-label"><i class="ph-bold ph-flow-arrow"></i> Brain debate plan</div>',
      '<ul class="target-debate-list">',
      plan.research_questions.map(function (q) { return '<li>' + esc(q) + '</li>'; }).join(''),
      '</ul>',
      '</section>',
      '<section data-anc="targeted.roles" data-detail-disabled="true">',
      '<div class="blog-section-label"><i class="ph-bold ph-users-three"></i> Runtime agent roles</div>',
      '<div class="target-debate-grid">',
      plan.roles.map(renderRole).join(''),
      '</div>',
      '</section>',
      '<section class="anc-section anc-section--gc anc-section--forest" data-anc="targeted.outputs" data-detail-disabled="true">',
      '<div class="blog-section-label"><i class="ph-bold ph-check-circle"></i> Required outputs</div>',
      '<div class="blog-card-tags">',
      plan.outputs.map(function (out) { return '<span class="blog-ticker-tag">' + esc(out) + '</span>'; }).join(''),
      '</div>',
      '</section>',
      '<section class="anc-section anc-section--gc anc-section--arctic" data-anc="targeted.brain-result" data-detail-disabled="true">',
      '<div class="blog-section-label"><i class="ph-bold ph-brain"></i> Brain execution</div>',
      '<div id="targeted-brain-status" class="target-debate-status">Ready to run through /loom/analyze.</div>',
      '<div id="targeted-brain-result" class="target-debate-result"></div>',
      '</section>',
      '</div>',
    ].join('');
  }

  function renderInto(anchor, options) {
    const container = anchor && anchor.container ? anchor.container : document.getElementById('anchor-content');
    if (!container) return;
    const html = renderTargetDebatePage(options || {});
    if (anchor) anchor.currentHtml = html;
    container.innerHTML = html;
    hydrate(container, options || {});
  }

  function hydrate(container, options) {
    const selector = container.querySelector('[data-anc="targeted.market-selector"]');
    if (!selector) return;
    const initial = selector.getAttribute('data-selected-targets')
      ? selector.getAttribute('data-selected-targets').split(',')
      : options.tickers || [options.ticker];
    const selection = createTargetSelection(initial);
    const selectedRow = container.querySelector('#targeted-selected-targets');
    const searchInput = container.querySelector('#targeted-symbol-search');
    const addButton = container.querySelector('#targeted-symbol-add');
    const results = container.querySelector('#targeted-search-results');
    const marketPanel = container.querySelector('#targeted-market-panel');
    const marketButtons = Array.from(container.querySelectorAll('[data-market-bucket]'));
    const runButton = container.querySelector('#targeted-run-brain');
    const status = container.querySelector('#targeted-brain-status');
    const result = container.querySelector('#targeted-brain-result');
    let activeBucket = selector.getAttribute('data-active-market') || 'us';

    function renderMarketPanel(bucket) {
      const groups = buildTargetUniverse();
      const nextBucket = bucket || 'us';
      const group = groups.find(function (item) { return item.id === nextBucket; }) || groups[0];
      activeBucket = group ? group.id : nextBucket;
      selector.setAttribute('data-active-market', activeBucket);
      marketButtons.forEach(function (button) {
        const isActive = button.getAttribute('data-market-bucket') === activeBucket;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      });
      if (marketPanel && group) {
        marketPanel.innerHTML = renderTargetMarketPanel(group, selection.selected);
      }
    }

    function sync() {
      selector.setAttribute('data-selected-targets', selection.selected.join(','));
      container.querySelectorAll('[data-target-ticker]').forEach(function (button) {
        const active = selection.has(button.getAttribute('data-target-ticker'));
        button.classList.toggle('is-selected', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      if (selectedRow) {
        selectedRow.innerHTML = selection.selected.map(function (ticker) {
          return '<span class="blog-ticker-tag">$' + esc(ticker) + '</span>';
        }).join('');
      }
      renderMarketPanel(activeBucket);
    }

    function renderResults() {
      if (!results || !searchInput) return;
      const query = searchInput.value;
      const matches = filterTargetUniverse(query).slice(0, 8);
      results.hidden = !query.trim();
      results.innerHTML = matches.map(function (target) {
        return renderTargetButton(target, selection.selected);
      }).join('');
    }

    selector.addEventListener('click', function (event) {
      const bucketButton = event.target.closest('[data-market-bucket]');
      if (bucketButton) {
        renderMarketPanel(bucketButton.getAttribute('data-market-bucket'));
        renderResults();
        return;
      }
      const button = event.target.closest('[data-target-ticker]');
      if (!button) return;
      selection.toggle(button.getAttribute('data-target-ticker'));
      sync();
      renderResults();
    });
    if (searchInput) {
      searchInput.addEventListener('input', renderResults);
      searchInput.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        selection.add(searchInput.value);
        searchInput.value = '';
        renderResults();
        sync();
      });
    }
    if (addButton && searchInput) {
      addButton.addEventListener('click', function () {
        selection.add(searchInput.value);
        searchInput.value = '';
        renderResults();
        sync();
      });
    }
    if (runButton) {
      runButton.addEventListener('click', async function () {
        runButton.disabled = true;
        if (status) status.textContent = 'Running Brain target debate...';
        if (result) result.innerHTML = '';
        try {
          const data = await submitTargetDebate({
            tickers: selection.selected,
            source: 'targeted-page',
          });
          if (status) {
            status.textContent = 'Brain completed episode ' + (data.episode_id || '(no episode id)');
          }
          if (result) {
            const synthesis = data.synthesis || {};
            result.innerHTML = [
              '<div class="target-debate-panel">',
              '<div class="target-debate-role-kicker">Goal</div>',
              '<p>' + esc(data.goal_id || '') + '</p>',
              '<div class="target-debate-role-kicker">Verdict</div>',
              '<p>' + esc(synthesis.stance || synthesis.summary || 'See Brain-rendered cards for full detail.') + '</p>',
              '</div>',
            ].join('');
          }
        } catch (error) {
          if (status) status.textContent = 'Brain run failed: ' + error.message;
        } finally {
          runButton.disabled = false;
        }
      });
    }
    renderMarketPanel(activeBucket);
    sync();
  }

  return {
    buildTargetUniverse,
    createTargetSelection,
    filterTargetUniverse,
    renderTargetSelector,
    buildBrainAnalyzeRequest,
    submitTargetDebate,
    buildTargetDebatePlan,
    renderTargetDebatePage,
    renderInto,
    hydrate,
  };
});
