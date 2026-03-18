# 分析算子库 v2 (26 个)

算子 = 一个独立的、可复用的分析指令单元。`.md` 文件，包含 YAML frontmatter（元数据 + 输出字段 + 行业门控）和 Markdown 正文（分析指令）。

## 目录结构

```
operators/v2/
├── screening/       # 筛选类 — 数据核查、地缘排除、快速过滤、央国企识别
├── fundamental/     # 基本面 — 负债、周期、现金流、管理层、流派、业绩还原
├── valuation/       # 估值类 — FCF、股息、PE陷阱、安全边际、所有者收益、修复
├── decision/        # 决策类 — 苹果模型、仓位管理、压力测试
├── special/         # 特殊策略 — 烟蒂股、轻资产模式
└── forward_risk/    # 前瞻风险（v2 新增）— AI冲击、政策、行业地位、市场情绪、新闻
```

## 算子清单

### screening/ — 筛选类 (4 个)

| id | 名称 | 关键输出 |
|----|------|---------|
| `data_source_grading` | 数据源分级与可信度 | data_confidence, data_warnings |
| `geopolitical_exclusion` | 地缘政治风险排除 | geo_risk_level, geo_excluded |
| `quick_screen_5min` | 5 分钟快速排除 | price_position_pct, pass_screening |
| `soe_identification` | 央国企背景识别 | is_soe, soe_type |

### fundamental/ — 基本面 (6 个)

| id | 名称 | 关键输出 |
|----|------|---------|
| `cash_trend_5y` | 5 年现金趋势 | cash_trend_5y, fcf_trend, cash_to_profit_ratio |
| `cycle_analysis` | 周期位置与拐点 | is_cyclical, cycle_position, reversal_signal |
| `debt_structure` | 负债结构拆解 | debt_structure_assessment, cycle_debt_tolerance |
| `management_integrity` | 管理人诚信评估 | management_integrity, integrity_red_flags |
| `performance_restoration` | 业绩还原 | reported_profit, adjusted_profit |
| `stream_classification` | 投资流派分类 | investment_stream, stream_reasoning |

### valuation/ — 估值类 (6 个)

| id | 名称 | 关键输出 | 门控 |
|----|------|---------|------|
| `owner_earnings` | 所有者收益计算 | owner_earnings, fcf | 排除：银行/保险/证券/多元金融 |
| `pe_trap_detection` | PE 陷阱识别 | pe_trap_warning, valuation_method | |
| `safety_margin` | 动态安全边际 | safety_margin_pct, buy_point, sell_point | |
| `valuation_dividend` | 股息估值法 | dividend_yield_pct, dividend_sustainable | |
| `valuation_fcf` | FCF 完整估值 | ev_fcf_multiple, fair_value_per_share | 排除：银行/保险/证券/多元金融 |
| `valuation_repair` | 估值修复目标价 | repair_target, repair_catalyst | |

### decision/ — 决策类 (3 个)

| id | 名称 | 关键输出 |
|----|------|---------|
| `apple_trading_model` | 苹果买卖模型 | apple_normal_price, apple_buy_price, apple_sell_price |
| `position_management` | 持仓与仓位管理 | recommendation, position_type, suggested_position_pct |
| `stress_test` | 极端情景压力测试 | still_profitable, stress_test_result |

### special/ — 特殊策略 (2 个)

| id | 名称 | 关键输出 |
|----|------|---------|
| `cigar_butt` | 烟蒂股深度价值 | is_cigar_butt, liquidation_value |
| `light_asset_model` | 轻资产模式分析 | is_light_asset, recurring_revenue_pct |

### forward_risk/ — 前瞻风险 (5 个，v2 新增)

| id | 名称 | 关键输出 |
|----|------|---------|
| `ai_disruption_risk` | AI/大模型冲击风险 | disruption_level, revenue_at_risk_pct, disruption_timeline |
| `policy_shift_risk` | 政策转向风险 | policy_exposure, policy_direction, strategic_alignment |
| `industry_position` | 行业地位与竞争格局 | market_position, competitive_moat, pricing_power |
| `market_sentiment` | 市场情绪与资金面 | sentiment_level, fund_flow_trend, contrarian_flag |
| `news_signal` | 新闻与公告信号 | news_sentiment, risk_flags, earnings_impact_pct |

前瞻风险算子依赖实时增强数据（新闻、资金流、大盘、行业），通过 `query_market_context` Tool 按需获取。回测模式下自动降级。

## 版本说明

- **v1**（21 个）：冻结，与回测结果 +7.1pp alpha 绑定，不可修改
- **v2**（26 个）：活跃开发，v1 全部算子 + 5 个前瞻风险算子 + 输出字段增强 + 行业门控

## 创建新算子

1. 在对应分类目录下创建 `.md` 文件（文件名 = id）
2. 编写 YAML frontmatter（id、name、outputs 必填）
3. 编写 Markdown 正文（分析指令、步骤、判定标准）
4. 在策略的 `strategy.yaml` 章节中引用该算子 id
