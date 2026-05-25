# Trading Workspace — Three-Mode Architecture Design Document

> Version: 1.0
> Date: 2026-05-23
> Status: Draft

---

## 1. Overview

The Trading Workspace expands the current single-file trading canvas into a **three-mode collaborative analysis platform**:

| Mode | Name | Core Function |
|------|------|--------------|
| **A** | 消息推送 (Market Intelligence Push) | AI-curated market briefings, alerts, diversified情报源 |
| **B** | 个人仓位管理 (Personal Position Management) | Position registry, attachments, risk assessment |
| **C** | 标的跟踪分析 (Target Tracking & Logic Analysis) | Long-term ticker tracking with thesis and divergence detection |

Each mode operates as a **独立面板**，shareable via workspace files, and can be combined in a tabbed trading hub.

---

## 2. Data Architecture

### 2.1 File Layout

```
D:\ai-native chrome\logs\
├── market/                      ← Mode A data
│   ├── subscriptions.json       { tickers[], sectors[], alert_types[], created_at, updated_at }
│   ├── briefings/              daily briefing files
│   │   └── YYYY-MM-DD.json     MarketBriefing object
│   ├── alerts/                 triggered alert files
│   │   └── {alert_id}.json     MarketAlert object
│   └── sentiment/              social sentiment cache
│       └── {ticker}_YYYY-MM-DD.json
├── portfolio/                  ← Mode B data
│   ├── positions.json          { positions: Position[], updated_at }
│   └── screenshots/            uploaded image files
│       └── {attachment_id}.{ext}
└── targets/                    ← Mode C data
    ├── targets.json            { targets: Target[], updated_at }
    └── logic_versions/         thesis revision history
        └── {target_id}_{logic_id}.json
```

### 2.2 Shared Event Model

All modes share the **Anchor Event Envelope** format (from `trading-events.cjs`).

New event kinds:

```
# Mode A — Market Intelligence
market.subscription.updated     — user updated ticker/sector subscriptions
market.briefing.generated       — AI generated a briefing card
market.alert.triggered          — market alert condition met
market.alert.dismissed         — user dismissed an alert
market.sentiment.fetched        — social sentiment data received

# Mode B — Position Management
position.registered             — user registered a new position
position.updated                — position size/entry/thesis changed
position.closed                 — position closed (unwound)
position.screenshot.added       — image attachment added
position.link.added             — external link (Notion/Docs) added
position.risk_assessed          — risk assessment computed

# Mode C — Target Tracking
target.registered               — user added a ticker to watchlist
target.logic.recorded           — initial trading logic recorded
target.logic.revised            — thesis/markers/assumptions updated
target.divergence.detected      — divergence score computed
target.divergence.alerted       — divergence alert pushed to user
target.milestone.updated        — expected_marker status changed
```

---

## 3. Mode A — 消息推送 (Market Intelligence Push)

### 3.1 信息来源

| 类别 | 来源 | 说明 |
|------|------|------|
| **价格/行情** | Alpha Vantage (free: 25 req/day) 或 Yahoo Finance (非官方但免费) | 主要价格数据 |
| **政策/新闻** | 金十数据 (jinshi.com) RSS、财联社 RSS、东方财富新闻流 | 政策面信息 |
| **行业动态** | 同花顺行业板块、雪球选股池 | 行业/板块动态 |
| **社交情绪** | 微博财经评论、东方财富股吧评论（单独板块，**仅作参考**） | 散户情绪统计 |

**数据源优先级**：价格/行情 > 政策/新闻 > 行业动态 > 社交情绪（辅助参考）

**轮询策略**：
- 价格数据：每5分钟轮询一次（免费API限制）
- 新闻/政策：每15分钟拉取一次
- 社交情绪：每小时拉取一次

### 3.2 Data Models

#### MarketBriefing

```typescript
interface MarketBriefing {
  briefing_id: string;           // "brf_{timestamp}_{rand}"
  generated_at: string;          // ISO 8601
  date: string;                  // "YYYY-MM-DD"
  type: "daily" | "sector_update" | "policy_alert";

  // Sentiment from price data
  sentiment: "bullish" | "bearish" | "neutral";
  sentiment_score: number;       // -1.0 to +1.0

  // Sources (authoritative first)
  sources: {
    name: string;
    url: string;
    content_snippet: string;
    fetched_at: string;
  }[];

  // Key analysis points
  key_points: {
    text: string;
    relevance: "high" | "medium" | "low";
    source_ref?: string;         // references sources[].name
  }[];

  // Catalysts and risks
  catalysts: string[];           // what's driving the market
  risks: string[];               // downside risks

  // Tickers covered
  watchlist: string[];          // tickers mentioned in briefing

  // Social sentiment (独立板块，不影响主判断)
  social_sentiment?: {
    platform: string;
    bullish_pct: number;
    bearish_pct: number;
    sample_size: number;
    fetched_at: string;
  };
}
```

#### MarketAlert

```typescript
interface MarketAlert {
  alert_id: string;              // "alrt_{timestamp}_{rand}"
  triggered_at: string;          // ISO 8601
  type: "price_spike" | "price_drop" | "volume_surge" | "news" | "sector_rotation" | "earnings";
  ticker?: string;               // null for market-wide alerts
  severity: "info" | "warning" | "critical";

  headline: string;              // 简短标题
  description: string;           // 详细描述
  source: {
    name: string;
    url: string;
  };

  // Price data (if applicable)
  price_data?: {
    current: number;
    change_pct: number;
    volume?: number;
  };

  action: "watch" | "review" | "act";
  dismissed: boolean;
  dismissed_at?: string;
}
```

#### Subscriptions

```typescript
interface Subscriptions {
  tickers: string[];              // ["AAPL", "NVDA", "MSFT"]
  sectors: string[];             // ["semiconductor", "AI", "fintech"]
  alert_types: AlertType[];      // ["price_spike", "news", "earnings"]
  notify_via: ("webview" | "browser")[];

  created_at: string;
  updated_at: string;
}
```

### 3.3 API Endpoints

```
GET  /market/subscriptions
     → { ok, subscriptions: Subscriptions }

POST /market/subscriptions
     body: { tickers?, sectors?, alert_types? }
     → { ok, subscriptions: Subscriptions }

GET  /market/briefing/:date
     date = "YYYY-MM-DD" or "latest"
     → { ok, briefing: MarketBriefing }

GET  /market/briefings
     query: ?since=YYYY-MM-DD&limit=10
     → { ok, briefings: MarketBriefing[] }

GET  /market/alerts
     query: ?since=YYYY-MM-DD&severity=warning&limit=20
     → { ok, alerts: MarketAlert[], unread_count: number }

POST /market/alerts/:id/dismiss
     → { ok }

GET  /market/sentiment/:ticker
     ticker = "AAPL"
     → { ok, sentiment: SocialSentiment, cached_at: string }
     Note: 返回结果**独立显示**，不参与主流程决策

POST /market/briefing/generate
     body: { type: "daily" | "sector_update", tickers?: string[] }
     → { ok, briefing: MarketBriefing }
```

### 3.4 Market Data Provider Interface

```javascript
// market-data-provider.cjs — 抽象接口
class MarketDataProvider {
  // 价格数据
  async getQuote(ticker) → { ticker, price, change_pct, volume, timestamp }
  async getQuotes(tickers[]) → Quote[]

  // 新闻/政策
  async getNews(options?: { sector?, limit? }) → NewsItem[]

  // 社交情绪
  async getSentiment(ticker) → { platform, bullish_pct, bearish_pct, sample_size }

  // 数据源状态
  getStatus() → { source: string, status: "ok"|"rate_limited"|"error", last_fetch: string }
}
```

Implementations:
- `AlphaVantageProvider` — free tier, rate-limited
- `YahooFinanceProvider` — non-official but free and higher rate limit
- `JinshiDataProvider` — policy/news RSS feeds
- `CailianPressProvider` — 财联社 RSS
- `SocialSentimentProvider` — 微博/股吧 aggregation

### 3.5 UI Layout — Mode A

```
┌─────────────────────────────────────────────────┐
│ [Market Intelligence]              [Subscriptions] │
│                                                  │
│  ┌─ Daily Briefing ─────────────────────────────┐ │
│  │ 📅 2026-05-23  ·  🟢 Bullish  ·  Sentiment +0.32│ │
│  │                                               │ │
│  │ Key Points:                                    │ │
│  │ • NVDA +4.2% on AI infrastructure buildout     │ │
│  │ • AAPL earnings beat; services revenue +15%    │ │
│  │ • Fed minutes: rates to remain elevated        │ │
│  │                                               │ │
│  │ Catalysts:                                     │ │
│  │ • OpenAI new model announcement today          │ │
│  │                                               │ │
│  │ Risks:                                          │ │
│  │ • Semiconductor supply constraints persist      │ │
│  └───────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Social Sentiment (独立参考) ───────────────┐ │
│  │ Platform: 东方财富股吧 · Sample: 12,847    │ │
│  │ 🟢 Bullish 58%  🟢 Bearish 42%              │ │
│  │ (注：社交情绪仅作参考，不影响主分析判断)    │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Live Alerts ────────────────────────────────┐ │
│  │ 🔴 NVDA hit $950 — Price target reached      │ │
│  │ 🟡 AAPL volume surged 3x 7-day average       │ │
│  │ 🟡 MSFT earnings in 3 days                  │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  Subscribed: [AAPL] [NVDA] [MSFT]  Sectors: [AI] │
└─────────────────────────────────────────────────┘
```

**Component Specifications:**

| Component | Style | Behavior |
|-----------|-------|----------|
| Daily Briefing Card | `anc-section anc-section--gc anc-section--aurora` | Expandable, click header to collapse |
| Social Sentiment Card | `anc-section anc-section--gc anc-section--dusk` | Always collapsed by default, shows only summary |
| Alert Card | `anc-section anc-section--gc` + severity color | Click to expand evidence; dismiss button |
| Subscription Manager | Inline tag list | Click tag to remove; "+" button to add |

---

## 4. Mode B — 个人仓位管理 (Personal Position Management)

### 4.1 Data Models

#### Position

```typescript
interface Position {
  position_id: string;          // "pos_{timestamp}_{rand}"
  ticker: string;                // "AAPL"
  size: number;                 // shares
  entry_price: number;          // average entry price
  entry_date: string;           // ISO date

  // Thesis
  thesis: string;               // user's reasoning for this position

  // Status
  status: "open" | "closed" | "watching";

  // Attachments (screenshot / Notion / Google Docs / URL)
  attachments: Attachment[];

  // Risk assessment (computed on registration and on update)
  risk_assessment: RiskAssessment;

  // P&L tracking
  current_price?: number;        // updated on market data fetch
  unrealized_pnl?: number;       // computed
  unrealized_pnl_pct?: number;   // computed

  created_at: string;
  updated_at: string;
  closed_at?: string;
}

interface Attachment {
  attachment_id: string;        // "att_{timestamp}_{rand}"
  type: "image" | "notion" | "googledocs" | "url";
  url: string;                  // local path for image, external URL for links
  label: string;                // "Screenshot 2026-05-20" or "Notion Doc"
  added_at: string;
}

interface RiskAssessment {
  concentration_pct: number;    // % of total portfolio value
  sector: string;               // "technology", "healthcare", etc.
  sector_exposure_pct: number; // % of portfolio in same sector
  correlated_positions: string[]; // position_ids with similar tickers/sectors
  risk_score: "low" | "medium" | "high";
  flags: RiskFlag[];            // e.g., "high_concentration", "sector_overweight"
  assessed_at: string;
}

type RiskFlag =
  | "high_concentration"         // single position > 30% of portfolio
  | "sector_overweight"          // sector > 50% of portfolio
  | "correlated_positions"       // multiple positions with high correlation
  | "no_thesis"                 // position has empty thesis
  | "high_volatility";          // position volatility > threshold
```

#### Portfolio Summary

```typescript
interface PortfolioSummary {
  total_value: number;          // sum of (size × current_price) for all open positions
  cash_balance: number;         // user-provided or estimated
  total_value_invested: number; // sum of (size × entry_price)

  positions_count: number;
  open_positions_count: number;
  closed_positions_count: number;

  sector_breakdown: Record<string, number>; // sector → % of portfolio
  risk_score: "low" | "medium" | "high";

  updated_at: string;
}
```

### 4.2 API Endpoints

```
GET  /position/list
     → { ok, positions: Position[], portfolio: PortfolioSummary }

POST /position/register
     body: { ticker, size, entry_price, entry_date?, thesis?, status?: "open"|"watching" }
     → { ok, position: Position, portfolio: PortfolioSummary }
     Note: 首次注册时 risk_assessment 自动计算

PATCH /position/:id
     body: { size?, entry_price?, thesis?, status? }
     → { ok, position: Position, portfolio: PortfolioSummary }

POST /position/:id/close
     body: { exit_price, exit_date?, pnl_note? }
     → { ok, position: Position, portfolio: PortfolioSummary }

POST /position/:id/attachment
     Content-Type: multipart/form-data
     fields: { file: binary, type: "image"|"notion"|"googledocs"|"url", label?: string }
     → { ok, attachment: Attachment }
     Note: image文件存入 logs/portfolio/screenshots/{attachment_id}.{ext}

GET  /position/:id/attachment/:attachment_id
     → redirect to screenshot file or external URL

DELETE /position/:id/attachment/:attachment_id
     → { ok }

GET  /portfolio/summary
     → { ok, portfolio: PortfolioSummary }

POST /portfolio/sentiment/sync
     body: { position_id, current_price }
     → { ok, position: Position, portfolio: PortfolioSummary }
     Note: 更新当前价格并重新计算 unrealized_pnl
```

### 4.3 Screenshot Storage

```
logs/portfolio/screenshots/
├── att_abc123_def456.png       ← user-uploaded screenshots
├── att_789xyz_uvw123.jpg
```

- Max file size: 10MB
- Allowed formats: PNG, JPG, JPEG, WebP
- Thumbnail: 200×200px auto-generated for display
- Original preserved for full-screen view

### 4.4 UI Layout — Mode B

```
┌─────────────────────────────────────────────────┐
│ [Portfolio]                    [+ Add Position]   │
│                                                  │
│  ┌─ Portfolio Summary ───────────────────────┐ │
│  │ 💼 Total: $248,500   Cash: $50,000         │ │
│  │ 📊 Positions: 4 open / 1 closed            │ │
│  │ 🟢 Risk: Low    Sector: Tech 60%            │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ AAPL 100 shares @ $178.50 ────────────────┐ │
│  │ Entry: $178.50 · Curr: $185.20 · +3.75%   │ │
│  │ Thesis: Services growth +15% driven by    │ │
│  │ App Store subscriptions expansion         │ │
│  │                                          │ │
│  │ [📷 Screenshot] [📄 Notion] [🔗 Docs]     │ │
│  │                                          │ │
│  │ Risk: 🟢 Low · Concentration: 7.5%       │ │
│  │ Sector: Technology · Exposure: 45%       │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ NVDA 50 shares @ $820.00 ────────────────┐ │
│  │ Entry: $820 · Curr: $950 · +15.85% 🔺      │ │
│  │ Thesis: AI infrastructure buildout cycle  │ │
│  │ ...                                        │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Component Specifications:**

| Component | Style | Behavior |
|-----------|-------|----------|
| Portfolio Summary | `anc-kpi-grid` with `anc-kpi--aurora` cards | Read-only KPIs |
| Position Card | `anc-section anc-section--gc anc-section--ocean` | Expandable; edit on click |
| Attachment Thumbnail | 48×48 image thumbnail, border-radius 6px | Click → open full image in new tab |
| Attachment Link Button | `btn btn--ghost btn--sm` with icon | Click → open URL in system browser |
| Risk Badge | `anc-pill anc-pill--active|warn|lock` | Color-coded: low=green, medium=yellow, high=red |
| Add Position Form | `anc-section anc-section--gc` | Expandable form with validation |

---

## 5. Mode C — 标的跟踪分析 (Target Tracking & Logic Analysis)

### 5.1 Data Models

#### Target

```typescript
interface Target {
  target_id: string;            // "tgt_{timestamp}_{rand}"
  ticker: string;                // "NVDA"
  status: "watching" | "owned" | "exited" | "archived";

  // Trading logic — the thesis and its components
  trading_logic: TradingLogic;

  // Divergence tracking
  divergence_tracking: DivergenceTracking;

  // Meta
  tags: string[];               // ["long-term", "AI", "earnings-play"]
  notes: string;

  // Linkage to Position (Mode B)
  linked_position_id?: string;   // if user owns this ticker

  created_at: string;
  updated_at: string;
}

interface TradingLogic {
  logic_id: string;              // "log_{timestamp}_{rand}"
  thesis: string;                // "NVDA benefits from AI infrastructure..."

  expected_markers: ExpectedMarker[];
  assumptions: string[];         // key assumptions
  invalidation_triggers: string[]; // conditions that invalidate thesis

  original_entry_price?: number;
  original_entry_date?: string;

  recorded_at: string;
  revised_at?: string;
  revision_count: number;       // increments on each revision
}

interface ExpectedMarker {
  marker_id: string;
  type: "price_target" | "fundamentals" | "news_event" | "time_horizon";
  description: string;          // "NVDA revenue > $50B"
  target_value?: string | number; // "$50B" or 50000000000
  deadline?: string;             // ISO date
  status: "pending" | "achieved" | "missed" | "invalidated";
  updated_at?: string;
}

interface DivergenceTracking {
  last_checked_at: string;
  divergence_score: number;      // 0.0 to 1.0 (1.0 = complete divergence)
  divergence_reasons: DivergenceReason[];

  // Alert configuration
  alert_threshold: number;       // default 0.6
  alert_sent: boolean;
  alerted_at?: string;
}

interface DivergenceReason {
  reason_id: string;
  type: "earnings" | "news" | "price_action" | "competitor" | "macro" | "thesis_reversal";
  description: string;          // "Q1 revenue missed by 10%"
  evidence: string;             // source or data point
  severity: "minor" | "moderate" | "major";
  detected_at: string;
}
```

### 5.2 Divergence Detection Engine

**触发机制（Real-time Push via SSE）：**

1. **Market Data Update** → 价格/新闻/社交情绪变化
2. **Comparison Engine** → AI 对比新数据 vs. thesis/assumptions/invalidation_triggers
3. **Score Computation** → `divergence_score = Σ(severity_weight × reason_match) / len(invalidation_triggers)`
4. **Threshold Check** → 如果 `divergence_score > alert_threshold`
5. **SSE Push** → 服务器通过 SSE 向 webview 推送 `{ type: "divergence_alert", target_id, ... }`
6. **Webview Display** → 显示 toast + 更新 Target 卡片 divergence badge

**比对维度：**

| 维度 | 检测方法 |
|------|---------|
| 价格偏离 | 当前价格 vs. expected_markers.price_target ±阈值 |
| 基本面变化 | 财报数据 vs. assumptions 中的财务假设 |
| 新闻事件 | news headline embedding vs. thesis keywords (余弦相似度) |
| 竞争对手 | 竞品动态是否影响 thesis 成立 |
| 宏观因素 | 利率/政策变化是否触发 invalidation_triggers |

### 5.3 API Endpoints

```
GET  /target/list
     query: ?status=watching|owned|exited|archived
     → { ok, targets: Target[], summary: { watching, owned, exited } }

POST /target/register
     body: { ticker, status?: "watching"|"owned", tags?: string[] }
     → { ok, target: Target }

GET  /target/:id
     → { ok, target: Target }

PATCH /target/:id
     body: { status?, tags?, notes? }
     → { ok, target: Target }

PUT  /target/:id/logic
     body: { thesis?, expected_markers?, assumptions?, invalidation_triggers?,
             original_entry_price?, original_entry_date? }
     → { ok, target: Target, logic_id: string }
     Note: 旧 logic 存档到 logic_versions/

GET  /target/:id/divergence
     → { ok, divergence_tracking: DivergenceTracking }

POST /target/:id/check-divergence
     → { ok, divergence_tracking: DivergenceTracking, new_reasons?: DivergenceReason[] }
     Note: 手动触发偏离检测

GET  /target/:id/logic/history
     → { ok, versions: LogicVersion[] }

GET  /target/:id/markers
     → { ok, markers: ExpectedMarker[], completed: number, total: number }

PATCH /target/:id/markers/:marker_id
     body: { status?, target_value? }
     → { ok, marker: ExpectedMarker }

GET  /target/stream
     → SSE stream: Content-Type: text/event-stream
     Events:
       event: divergence_alert  data: { target_id, ticker, divergence_score, reasons }
       event: marker_updated    data: { target_id, marker_id, status }
       event: price_update       data: { ticker, price, change_pct }

POST /target/link-position
     body: { target_id, position_id }
     → { ok, target: Target }
```

### 5.4 UI Layout — Mode C

```
┌─────────────────────────────────────────────────┐
│ [Targets]                        [+ Add Target]   │
│                                                  │
│  Filter: [Watching] [Owned] [Exited]  Sort: [Divergence] [Ticker] │
│                                                  │
│  ┌─ NVDA · Owned ─────────────────────────────┐ │
│  │ 🟢 Thesis Intact · Divergence: 12%         │ │
│  │ 📈 $950 (+15.85%) · Target: $1,100          │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ TSLA · Watching ──────────────────────────┐ │
│  │ 🟡 Divergence: 47% · ⚠️ Moderate           │ │
│  │ 📉 $248 (-8.2%) · Thesis: EV adoption...    │ │
│  │ Reasons: Price below $260 support; macro... │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
└─────────────────────────────────────────────────┘

Target Detail View (click NVDA row):
┌─────────────────────────────────────────────────┐
│ ← Back to Watchlist                              │
│                                                  │
│  NVDA · Owned                                    │
│  Tags: [long-term] [AI] [+ Add]                 │
│                                                  │
│  ┌─ Trading Logic ─────────────────────────────┐ │
│  │ Thesis:                                     │ │
│  │ "NVDA 在 AI 基础设施建周期中处于主导地位，   │ │
│  │  数据中心 capex 持续增长推动收入"           │ │
│  │                                              │ │
│  │ Expected Markers:                           │ │
│  │ ✅ NVDA revenue > $50B (Q4 2026)           │ │
│  │ ✅ Data center capex +20% YoY               │ │
│  │ ⏳ AI model market share > 80%               │ │
│  │                                              │ │
│  │ Assumptions:                                 │ │
│  │ • Hyperscaler capex 持续增长                │ │
│  │ • AMD 无法在 CUDA 生态形成有效竞争          │ │
│  │ • 游戏显卡需求保持稳定                      │ │
│  │                                              │ │
│  │ Invalidation Triggers:                       │ │
│  │ • Intel AMD GPU 生态占有率 > 30%            │ │
│  │ • GPU 出口管制收紧                          │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Divergence Status ─────────────────────────┐ │
│  │          12%                                │ │
│  │    ═══════●━━━━━━━━━ 1.0                   │ │
│  │    Divergence Score                          │ │
│  │                                              │ │
│  │ Last checked: 2026-05-23 14:30              │ │
│  │                                          │ │
│  │ No significant divergence detected.         │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  [Edit Logic] [Archive Target] [Link Position]   │
└─────────────────────────────────────────────────┘
```

**Component Specifications:**

| Component | Style | Behavior |
|-----------|-------|----------|
| Target Row | `workspace-node` style with divergence badge | Click → open detail view |
| Divergence Badge | `anc-pill anc-pill--active|warn|lock` | Score 0-30%=green, 31-60%=yellow, 61-100%=red |
| Divergence Score Bar | Custom CSS progress bar, gradient green→yellow→red | Animated on score change |
| Logic Editor | `anc-section anc-section--gc` with form fields | Auto-save on field blur |
| Marker Item | Checkbox-style list item | Click → cycle status pending/achieved/missed |
| SSE Alert Toast | `toast toast--warning` | Auto-dismiss 10s, click to expand |

---

## 6. Cross-Mode Interactions

```
Market Feed (A)
    │
    ├── Alert triggered for ticker X
    │       ↓
    │   If Mode C has X as target → divergence check triggered
    │   If Mode B has X as position → risk alert triggered
    │
    └── Briefing mentions ticker Y
            ↓
        If Mode C has Y as target → suggestion to update logic

Position (B)
    │
    └── Position opened for ticker Z
            ↓
        If Mode C has Z as target → prompt to link position to target

Target (C)
    │
    └── Divergence detected for ticker W
            ↓
        If Mode B has W as position → push risk alert to portfolio view
```

---

## 7. Implementation Phases

| Phase | 内容 | 文件 |
|-------|------|------|
| **Phase 1** | Mode A 基础：market-routes + market-canvas-renderer + market-data-provider（多源） | `trading/market-*.cjs`, `logs/market/` |
| **Phase 2** | Mode B 基础：position-routes + position-canvas-renderer + 截图存储 | `trading/position-*.cjs`, `logs/portfolio/` |
| **Phase 3** | Mode C 基础：target-routes + target-canvas-renderer + logic editor | `trading/target-*.cjs`, `logs/targets/` |
| **Phase 4** | Mode C 实时推送：divergence-engine + SSE stream + webview SSE listener | `trading/divergence-engine.cjs`, server SSE, anchor-client.js |
| **Phase 5** | Webview 集成：tab bar + mode路由 + cross-mode interaction | `index.html`, `anchor-client.js` |

---

## 8. CSS/Style Requirements

All mode-specific UI elements use the **Bloom Design System** (`bridge/webview/styles.css`):

| Element | CSS Classes |
|---------|-------------|
| Mode tab bar | `.trading-mode-tabs` on `.anc-tabs` or toolbar |
| Briefing card | `.anc-section anc-section--gc anc-section--aurora` |
| Alert card | `.anc-section anc-section--gc` + severity modifier |
| Position card | `.anc-section anc-section--gc anc-section--ocean` |
| Target row | `.workspace-node workspace-node--target` |
| Divergence bar | `.divergence-bar` + `.divergence-bar--low/medium/high` |
| Risk badge | `.anc-pill anc-pill--active|warn|lock` |
| Attachment thumbnail | `.trading-attachment-thumb` |

---

## 9. Open Decisions

1. **Market data API key management** — env vars vs. user-provided at runtime?
2. **SSE reconnection** — automatic reconnect with exponential backoff in anchor-client.js?
3. **Image thumbnail generation** — server-side (sharp) or CSS-based (object-fit: cover)?
4. **Divergence scoring algorithm** — keyword embedding vs. LLM-based comparison?
5. **Social sentiment polling interval** — hourly sufficient, or more frequent for active tickers?
6. **Briefing generation trigger** — scheduled (daily) vs. on-demand vs. on significant market events?
7. **Position risk computation** — user provides total portfolio value, or estimate from position sizes alone?