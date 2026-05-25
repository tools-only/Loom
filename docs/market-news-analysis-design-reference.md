# 市场行情研判新闻页设计参考

> 目标：设计一个从大盘到板块再到核心标的的三层行情研判新闻产品，帮助用户快速判断“市场环境、资金方向、标的赔率与风险”。

## 1. 产品定位

### 核心用户

- 主动投资者：需要每天快速理解美股行情主线、宏观变化、板块轮动和重点股票异动。
- 投研/交易助理：需要把新闻、数据、财报、宏观指标整理成结构化判断。
- 内容编辑/分析师：需要稳定产出盘前、盘中、盘后行情解读。

### 核心问题

- 大盘页：现在市场处于什么环境？
- 板块页：资金、盈利预期和叙事正在流向哪里？
- 核心标的页：哪些股票是行情发动机，哪些是风险源，哪些存在预期差？

### 产品原则

- 事实与观点分离：原始数据、新闻事实、分析结论分层展示。
- 先结论后证据：每页顶部给出一句话结论，再展开依据。
- 从宏观到微观：先看市场水位，再看行业方向，最后看单股催化。
- 所有判断都要有“推翻条件”：明确什么变化会使当前观点失效。

## 2. 整体信息架构

```text
市场行情研判
├── 大盘行情页
│   ├── 今日市场结论
│   ├── 指数与市场宽度
│   ├── 宏观数据
│   ├── 利率、美元与美联储
│   ├── 流动性与信用
│   ├── 波动率与期权
│   ├── 盈利与估值
│   └── 风险事件日历
├── 板块轮动页
│   ├── 板块热力图
│   ├── 相对强弱
│   ├── 资金流向
│   ├── 盈利修正
│   ├── 产业景气
│   ├── 政策监管
│   ├── 板块内部结构
│   └── 轮动判断
└── 核心标的页
    ├── 标的速览
    ├── 今日异动归因
    ├── 行情结构
    ├── 基本面质量
    ├── 财报与预期差
    ├── 估值与隐含预期
    ├── 期权、空头与情绪
    ├── 内部人与机构
    └── 催化剂与风险
```

## 3. 页面一：大盘行情研判页

### 页面目标

回答：今天美股市场到底是在交易什么？是宏观、利率、流动性、盈利，还是情绪和技术面？

### 顶部摘要模块

| 模块 | 字段 | 用途 |
|---|---|---|
| 今日市场状态 | Risk-on / Risk-off / 震荡 / 防御 | 让用户 5 秒内理解市场温度 |
| 一句话结论 | 例如：科技权重股带动指数反弹，但市场宽度偏弱 | 压缩当天核心判断 |
| 三大驱动因素 | 利率下行、AI 龙头财报、美元走弱等 | 解释行情主因 |
| 风险等级 | 低 / 中 / 高 | 标记波动、事件和拥挤度 |
| 下一个关键事件 | CPI、FOMC、非农、财报、期权到期 | 告诉用户下一步看什么 |

### 分析层面与信息源

| 分析层面 | 要回答的问题 | 关键指标 | 推荐信息源 |
|---|---|---|---|
| 指数表现 | 三大指数和风格指数怎么走？ | S&P 500、Nasdaq 100、Dow、Russell 2000、成长/价值、等权指数 | Yahoo Finance、Bloomberg、Reuters、TradingView、Nasdaq |
| 市场宽度 | 上涨是否健康？ | 涨跌家数、新高新低、等权指数/市值加权指数、成分股高于 50/200 日均线比例 | NYSE/Nasdaq market breadth、StockCharts、Koyfin、TradingView |
| 宏观数据 | 经济是在加速还是放缓？ | CPI、PCE、非农、失业率、ISM、GDP、零售销售、消费者信心 | BLS、BEA、FRED、ISM、Conference Board |
| 利率环境 | 估值压力来自哪里？ | 2Y/10Y 美债收益率、实际利率、收益率曲线、term premium | U.S. Treasury、FRED、CME、Bloomberg |
| 美联储政策 | 市场是在交易宽松还是紧缩？ | FOMC 声明、点阵图、会议纪要、官员讲话、降息概率 | Federal Reserve、CME FedWatch、Reuters、Bloomberg |
| 美元与跨资产 | 风险偏好是否被美元压制？ | DXY、黄金、原油、铜、比特币、日元、信用债 ETF | ICE、FRED、TradingView、Yahoo Finance |
| 流动性 | 市场水位是在上升还是下降？ | Fed 资产负债表、银行准备金、TGA、逆回购、QT/QE、财政发债 | Fed H.4.1、Daily Treasury Statement、FRED |
| 信用环境 | 风险资产有没有信用压力？ | 高收益债利差、投资级利差、HYG/LQD、银行股表现 | FRED、ICE/BofA indices、Bloomberg、Koyfin |
| 波动率与期权 | 市场恐慌还是过度乐观？ | VIX、VVIX、Put/Call Ratio、skew、0DTE 成交、gamma exposure | Cboe、OCC、SpotGamma、OptionMetrics |
| 资金流 | 谁在买？谁在卖？ | ETF 净流入、主动基金仓位、货币基金规模、margin debt | ETF.com、FactSet、EPFR、ICI、FINRA |
| 盈利周期 | 大盘上涨有没有盈利支撑？ | S&P 500 EPS 增速、利润率、盈利上修/下修、beat rate | FactSet Earnings Insight、Refinitiv I/B/E/S、Bloomberg、公司财报 |
| 估值 | 市场贵不贵，贵在哪里？ | Forward PE、ERP、CAPE、FCF yield、PEG、相对债券收益率 | FactSet、S&P Global、Yardeni、Koyfin、Bloomberg |
| 新闻催化 | 今天改变预期的新闻是什么？ | 宏观数据、Fed 发言、地缘政治、财政政策、财报、监管 | Reuters、Bloomberg、WSJ、FT、CNBC、官方公告 |
| 风险事件 | 什么可能推翻当前判断？ | CPI、FOMC、非农、财报密集期、期权到期、财政拍卖 | 经济日历、Nasdaq 财报日历、CME、Treasury auction schedule |

### 推荐版式

- 第一屏：市场状态条 + 三大指数卡片 + 今日主线。
- 第二屏：四象限分析区：宏观、利率流动性、盈利估值、情绪技术。
- 第三屏：新闻归因流，将新闻按“宏观、政策、财报、地缘、市场结构”分类。
- 底部：未来 7 天风险日历 + 当前判断的推翻条件。

### 大盘页输出模板

```text
今日判断：
市场处于 [Risk-on/Risk-off/震荡]。主要驱动是 [因素 1]、[因素 2]、[因素 3]。

关键证据：
1. 指数层面：[指数表现与市场宽度]
2. 宏观层面：[数据/利率/美元变化]
3. 流动性层面：[Fed/TGA/RRP/信用]
4. 盈利估值：[EPS 修正/估值变化]

风险提示：
若 [关键指标/事件] 出现 [变化]，当前判断需要下修/上修。
```

## 4. 页面二：板块轮动研判页

### 页面目标

回答：资金正在从哪些板块流出，流向哪些板块？这是短期反弹，还是趋势性轮动？

### 顶部摘要模块

| 模块 | 字段 | 用途 |
|---|---|---|
| 今日领涨板块 | 板块名称、涨幅、成交额变化 | 快速识别市场主线 |
| 今日拖累板块 | 板块名称、跌幅、拖累原因 | 识别风险和避险方向 |
| 轮动状态 | 成长进攻 / 周期修复 / 防御占优 / 全面扩散 | 判断资金风格 |
| 最强相对趋势 | 板块 vs SPY 相对强弱 | 过滤单日噪音 |
| 资金确认 | ETF flows 是否配合 | 判断行情持续性 |

### 分析层面与信息源

| 分析层面 | 要回答的问题 | 关键指标 | 推荐信息源 |
|---|---|---|---|
| 板块热力图 | 今天谁领涨，谁拖累？ | 11 个 GICS 板块涨跌、成交额、贡献度 | S&P Sector Indices、State Street Select Sector ETFs、TradingView |
| 相对强弱 | 板块是否跑赢大盘？ | 板块/SPY 相对收益、20/50/200 日均线、RSI、动量排名 | Koyfin、TradingView、Bloomberg |
| 资金流向 | 资金是否持续进入？ | 行业 ETF 净流入、成交量放大、主动基金配置变化 | ETF.com、FactSet、EPFR、Bloomberg |
| 盈利预期 | 上涨靠盈利还是估值？ | EPS revision、营收增速、利润率变化、beat/miss | FactSet、Refinitiv、Bloomberg、公司财报 |
| 估值分位 | 板块是否透支预期？ | Forward PE、EV/EBITDA、P/S、FCF yield、历史分位、相对大盘溢价 | S&P Global、FactSet、Koyfin |
| 宏观敏感度 | 板块吃什么宏观因子？ | 利率敏感、美元敏感、油价敏感、经济周期敏感、信用敏感 | FRED、Treasury、EIA、BLS、BEA |
| 产业景气 | 行业本身是否改善？ | 订单、库存、价格、产能、资本开支、供需缺口 | 行业协会、公司指引、PMI、Gartner、IDC、SEMI、EIA、OPEC、SIA |
| 政策监管 | 是否有政策红利或监管压制？ | 反垄断、药价、银行资本规则、AI/芯片出口管制、能源政策 | SEC、FTC、DOJ、FDA、EPA、Commerce Department、White House |
| 内部结构 | 是普涨还是龙头独涨？ | 板块内涨跌家数、等权 ETF、龙头贡献度、子行业分化 | S&P GICS、ETF 持仓、Koyfin、TradingView |
| 龙头观察 | 哪些股票决定板块方向？ | 权重股涨跌、财报、新闻、技术位置、期权异动 | ETF holdings、公司 IR、SEC EDGAR、Cboe、Nasdaq |
| 新闻归因 | 今天板块为什么动？ | 财报、评级、政策、商品价格、利率变化、并购 | Reuters、Bloomberg、WSJ、行业媒体、公司公告 |
| 轮动判断 | 下一步资金可能去哪？ | 防御/周期/成长/价值切换、主题强弱、资金持续性 | 板块相对强弱、ETF flows、宏观因子、盈利修正 |

### 板块分类建议

| 板块类型 | 典型板块 | 主要驱动 |
|---|---|---|
| 成长进攻型 | 信息技术、通信服务、可选消费 | 利率下行、盈利上修、AI/云/广告叙事 |
| 周期复苏型 | 工业、材料、能源、金融 | GDP、PMI、油价、信用、收益率曲线 |
| 防御现金流型 | 公用事业、必需消费、医疗保健 | 避险需求、股息收益率、经济放缓 |
| 利率敏感型 | 房地产、公用事业、金融、成长股 | 长端收益率、实际利率、融资成本 |
| 政策敏感型 | 医疗、能源、军工、半导体、银行 | 监管、补贴、出口管制、财政预算 |

### 推荐版式

- 第一屏：GICS 热力图 + 领涨/领跌排行榜 + 今日轮动状态。
- 第二屏：板块卡片，每张卡片包含涨跌、资金流、盈利修正、估值分位、新闻主因。
- 第三屏：轮动地图，将板块放入“进攻、防御、周期、利率敏感”坐标系。
- 底部：板块机会观察名单 + 风险板块观察名单。

### 板块页输出模板

```text
今日板块主线：
[板块 A] 领涨，主要受 [驱动因素] 影响；[板块 B] 承压，原因是 [风险因素]。

资金确认：
ETF flows 显示 [流入/流出]，成交量 [放大/收缩]，说明 [持续性判断]。

轮动判断：
当前市场偏向 [成长/周期/防御/价值]。若 [宏观或盈利条件] 继续出现，资金可能继续流向 [候选板块]。
```

## 5. 页面三：热门核心标的研判页

### 页面目标

回答：某只核心股票为什么动？行情是基本面变化、预期差、估值重定价、期权推动，还是纯情绪？

### 顶部摘要模块

| 模块 | 字段 | 用途 |
|---|---|---|
| 标的一句话结论 | 例如：财报上修带动突破，但估值已接近历史高位 | 快速形成判断 |
| 今日异动原因 | 财报、评级、产品、监管、并购、期权、宏观 | 归因当天行情 |
| 所属主线 | AI、半导体、云、减肥药、能源、金融等 | 连接板块页 |
| 对指数贡献 | 对 S&P 500 / Nasdaq 100 贡献点数 | 判断是否影响大盘 |
| 风险等级 | 低 / 中 / 高 | 标记拥挤和事件风险 |

### 分析层面与信息源

| 分析层面 | 要回答的问题 | 关键指标 | 推荐信息源 |
|---|---|---|---|
| 标的速览 | 这只股票今天为什么重要？ | 涨跌幅、成交额、新闻触发、所属主题、指数贡献 | Nasdaq、NYSE、Yahoo Finance、Bloomberg、Reuters |
| 行情结构 | 是趋势突破还是事件冲击？ | 价格位置、成交量、跳空、均线、支撑阻力、相对板块强弱 | TradingView、Koyfin、broker data |
| 期权与情绪 | 是否存在短期拥挤交易？ | 期权成交、IV rank、put/call、gamma exposure、最大痛点、短空比例 | Cboe、OCC、Ortex、S3 Partners、FINRA、SpotGamma |
| 基本面质量 | 公司长期质量如何？ | 收入增速、毛利率、经营利润率、FCF、ROIC、资产负债表 | SEC EDGAR、公司 10-K/10-Q、公司 IR |
| 财报与指引 | 最新财报改变了什么？ | EPS/revenue beat、guidance、订单、backlog、利润率、管理层口径 | 公司 earnings release、earnings call transcript、Nasdaq/Yahoo 财报日历 |
| 预期差 | 市场预期是否过高或过低？ | 分析师上修/下修、目标价变化、consensus EPS、whisper number | FactSet、Refinitiv、Bloomberg、Zacks、Visible Alpha |
| 估值 | 当前股价隐含什么增长？ | Forward PE、PEG、EV/Sales、EV/EBITDA、FCF yield、DCF 敏感性 | FactSet、Koyfin、Capital IQ、公司财务模型 |
| 竞争格局 | 护城河是否变化？ | 市占率、定价权、客户集中度、替代品、供应链议价能力 | 10-K 风险因素、行业报告、Gartner、IDC、SEMI、竞品财报 |
| 主题暴露 | 它是不是行情主线核心表达？ | AI/云/芯片/药品/能源/加密等主题收入贡献和新闻热度 | 公司披露、财报电话会、行业媒体、ETF 持仓 |
| 资本动作 | 管理层如何使用资本？ | 回购、分红、并购、发债、增发、股权激励、稀释 | SEC 8-K、10-Q、10-K、公司公告 |
| 内部人与机构 | 聪明钱在做什么？ | Form 4 内部人买卖、13F、机构增减持、空头仓位 | SEC EDGAR Form 4/13F、WhaleWisdom、Fintel、Nasdaq institutional holdings |
| 监管与法律 | 最大非经营风险是什么？ | 诉讼、反垄断、FDA 审批、出口限制、会计调查、数据隐私 | SEC filings、DOJ、FTC、FDA、法院文件、公司公告 |
| 新闻时间线 | 过去 30 天发生了什么？ | 财报、评级、产品发布、政策、竞品消息、管理层发言 | Reuters、Bloomberg、WSJ、公司 IR、PR Newswire |
| 催化剂 | 接下来什么会重新定价？ | 财报日期、产品发布、投资者日、除权日、宏观敏感窗口 | Nasdaq Earnings Calendar、公司 IR、经济日历 |

### 核心标的分类建议

| 标的类型 | 典型特征 | 重点看什么 |
|---|---|---|
| 指数权重股 | 对 Nasdaq/S&P 贡献大 | 指数贡献、机构仓位、估值扩张 |
| 主题龙头 | 绑定强叙事，如 AI、减肥药、加密 | 叙事强度、订单、资本开支、竞争格局 |
| 财报驱动股 | 财报后大涨大跌 | guidance、margin、analyst revision |
| 高波动交易股 | 期权/空头/散户热度高 | IV、short interest、gamma、社媒情绪 |
| 监管敏感股 | 医疗、金融、平台、能源 | 政策、诉讼、监管文件 |

### 推荐版式

- 第一屏：标的速览 + 今日异动归因 + 所属主线 + 风险等级。
- 第二屏：五栏研判：行情结构、基本面、预期差、估值、事件。
- 第三屏：新闻时间线 + 财报电话会摘要 + 分析师修正。
- 底部：未来催化剂、关键价位、推翻逻辑。

### 核心标的页输出模板

```text
标的判断：
[Ticker] 今日上涨/下跌主要由 [驱动因素] 触发，属于 [基本面/估值/情绪/技术/期权] 驱动。

关键证据：
1. 基本面：[财报、收入、利润率、指引]
2. 预期差：[分析师修正、市场共识变化]
3. 估值：[当前估值与历史/同行对比]
4. 交易结构：[成交量、期权、空头、技术位置]

后续关注：
若 [催化剂] 兑现，行情可能延续；若 [推翻条件] 出现，应下修判断。
```

## 6. 信息源优先级

| 优先级 | 类型 | 典型来源 | 用途 |
|---|---|---|---|
| A | 官方/原始数据 | Fed、Treasury、BLS、BEA、SEC、Cboe、FINRA、公司 IR | 事实基准、不可替代的原始数据 |
| B | 交易与数据供应商 | Bloomberg、FactSet、Refinitiv、S&P Global、Koyfin、TradingView | 结构化行情、估值、盈利、资金流 |
| C | 主流财经新闻 | Reuters、Bloomberg News、WSJ、FT、CNBC | 新闻事实、事件归因、市场反应 |
| D | 行业垂直来源 | Gartner、IDC、SEMI、EIA、OPEC、SIA、FDA、行业协会 | 产业景气和行业变量 |
| E | 市场情绪来源 | X/Twitter、Reddit、Stocktwits、Google Trends、YouTube | 情绪、叙事、散户热度 |
| F | 二次解读 | Newsletter、券商策略、KOL、播客、博客 | 观点补充，只能作为参考 |

使用规则：

- A/B 层用于确定事实。
- C/D 层用于解释事件。
- E/F 层只用于观察情绪和叙事，不直接作为投资判断依据。
- 所有新闻结论都应回链到至少一个原始数据或可信新闻来源。

## 7. 页面组件清单

### 通用组件

| 组件 | 功能 | 关键状态 |
|---|---|---|
| MarketStatusBar | 展示市场状态、风险等级、更新时间 | normal、stale、loading、error |
| DriverTags | 展示行情驱动标签 | macro、earnings、liquidity、policy、technical、sentiment |
| SourceBadge | 标记信息源等级 | official、data-vendor、news、industry、social |
| EvidencePanel | 展示判断证据 | collapsed、expanded、missing-data |
| RiskCalendar | 展示未来事件 | today、this-week、high-impact |
| NewsTimeline | 按时间展示新闻 | grouped、filtered、empty |
| ConfidenceMeter | 判断置信度 | low、medium、high |
| ReversalCondition | 推翻条件 | active、triggered |

### 大盘页组件

- IndexSummaryCards
- MarketBreadthPanel
- MacroDataGrid
- RatesAndFedPanel
- LiquidityDashboard
- VolatilityOptionsPanel
- EarningsValuationPanel
- CrossAssetStrip

### 板块页组件

- SectorHeatmap
- SectorRankingTable
- SectorFlowPanel
- RelativeStrengthChart
- SectorCard
- RotationMap
- IndustryCatalystList
- SectorLeadershipTable

### 核心标的页组件

- TickerHero
- MoveAttributionPanel
- PriceStructureChart
- FundamentalsSnapshot
- EarningsExpectationPanel
- ValuationImpliedGrowthCard
- OptionsSentimentPanel
- InsiderInstitutionalPanel
- CatalystRiskTimeline

## 8. 数据字段建议

### 大盘实体

```json
{
  "market_date": "YYYY-MM-DD",
  "session": "pre_market|regular|after_hours|post_close",
  "market_state": "risk_on|risk_off|mixed|defensive",
  "primary_drivers": ["rates", "earnings", "liquidity"],
  "indices": [],
  "breadth": {},
  "macro_events": [],
  "rates": {},
  "liquidity": {},
  "volatility": {},
  "earnings": {},
  "valuation": {},
  "risk_events": [],
  "conclusion": "",
  "reversal_conditions": []
}
```

### 板块实体

```json
{
  "sector_id": "information_technology",
  "sector_name": "Information Technology",
  "gics_code": "45",
  "daily_return": 0,
  "relative_return_vs_spy": 0,
  "etf_flows": {},
  "earnings_revision": {},
  "valuation_percentile": 0,
  "macro_sensitivity": ["rates", "usd"],
  "top_constituents": [],
  "news_drivers": [],
  "rotation_status": "leading|improving|weakening|lagging",
  "view": "",
  "reversal_conditions": []
}
```

### 标的实体

```json
{
  "ticker": "NVDA",
  "company_name": "NVIDIA Corp.",
  "sector": "Information Technology",
  "theme_tags": ["AI", "semiconductors"],
  "daily_return": 0,
  "volume_change": 0,
  "move_attribution": [],
  "fundamentals": {},
  "earnings": {},
  "valuation": {},
  "options": {},
  "institutional": {},
  "insider": {},
  "news_timeline": [],
  "catalysts": [],
  "risks": [],
  "view": "",
  "reversal_conditions": []
}
```

## 9. 交互设计建议

- 所有页面都提供“证据展开”：用户可以从结论展开到指标、新闻和原始来源。
- 页面顶部固定一个轻量状态栏：市场状态、更新时间、数据延迟、风险等级。
- 新闻列表支持按驱动因素过滤：宏观、政策、财报、行业、技术、情绪。
- 每个判断旁边显示置信度和来源等级，避免把弱信号包装成强结论。
- 板块页点击板块进入该板块详情，再点击核心标的进入标的页。
- 标的页支持对比：标的 vs 板块 ETF vs SPY。
- 关键事件到期前，页面自动提高相关模块权重，例如 CPI 前突出利率和通胀。

## 10. 视觉与设计系统建议

### 视觉风格

- 定位：专业、密集、可扫读、偏交易终端，但比 Bloomberg 更轻。
- 避免：营销式大卡片、过大的 hero、装饰性渐变、纯单色主题。
- 推荐：紧凑表格、分层信息密度、清晰标签、少量强调色。

### 颜色语义

| Token | 用途 |
|---|---|
| `--color-bg` | 页面背景，建议近白或深灰两套主题 |
| `--color-panel` | 模块背景 |
| `--color-border` | 分割线和弱边框 |
| `--color-text-primary` | 主文本 |
| `--color-text-secondary` | 次级信息 |
| `--color-positive` | 上涨、流入、上修 |
| `--color-negative` | 下跌、流出、下修 |
| `--color-warning` | 高波动、事件风险 |
| `--color-info` | 中性提示、政策/宏观标签 |

### 信息密度

- 大盘页：摘要密度高，图表多，新闻流在下方。
- 板块页：卡片和表格结合，强调横向比较。
- 标的页：纵向叙事更强，强调时间线、财报和预期差。

## 11. 空态、加载和错误状态

| 场景 | 展示策略 |
|---|---|
| 数据未更新 | 显示最后更新时间和 stale 标记 |
| 某项数据缺失 | 显示缺失来源，不隐藏模块 |
| 新闻源不可用 | 降级到其他来源，并标记 source fallback |
| 指标冲突 | 同时展示冲突证据，不强行给单一结论 |
| 市场休市 | 切换为“上个交易日回顾 + 下个交易日预览” |
| 高波动盘中 | 提示部分结论为盘中暂态，收盘后重算 |

## 12. 内容生成规则

### 好的行情结论

- 包含方向：市场/板块/标的是上涨、下跌，还是震荡。
- 包含原因：至少 2 个证据支撑。
- 包含强弱：说明该信号是强、中、弱。
- 包含风险：明确推翻条件。

### 避免的写法

- “市场因多重因素波动”但不解释哪些因素。
- “投资者担忧”但没有来源或指标。
- “估值合理”但不说明相对谁、相对什么历史区间。
- “资金流入明显”但没有 ETF flows、成交量或机构数据支持。

## 13. MVP 范围建议

### 第一阶段

- 大盘页：指数、宽度、利率、VIX、新闻归因、风险日历。
- 板块页：GICS 热力图、板块涨跌、ETF flows、板块新闻。
- 标的页：价格、新闻、财报摘要、估值、催化剂。

### 第二阶段

- 加入盈利修正、流动性、期权结构、内部人交易、13F。
- 加入判断置信度和推翻条件。
- 支持自定义观察列表。

### 第三阶段

- 自动生成盘前、盘中、盘后研报。
- 做多源新闻归因和冲突证据检测。
- 建立主题图谱：宏观因子 -> 板块 -> 标的。

## 14. 关键来源链接

- Federal Reserve Monetary Policy: https://www.federalreserve.gov/monetarypolicy.htm
- Fed H.4.1 Balance Sheet: https://www.federalreserve.gov/releases/h41/Current/
- Daily Treasury Statement: https://home.treasury.gov/data/receipts-outlays
- BLS Data: https://www.bls.gov/data/
- BEA GDP: https://www.bea.gov/products/gross-domestic-product-gdp
- CME FedWatch: https://www.cmegroup.com/fedwatch
- SEC EDGAR: https://www.sec.gov/edgar/searchedgar/companysearch
- Cboe Market Statistics: https://www.cboe.com/markets/us/options/market-statistics/daily
- FINRA Margin Statistics: https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics
- S&P Sector Indices: https://www.spglobal.com/spdji/en/index-family/equity/us-equity/sp-sectors/
- ETF.com Tools: https://www.etf.com/tools
- Nasdaq Earnings Calendar: https://www.nasdaq.com/market-activity/earnings

