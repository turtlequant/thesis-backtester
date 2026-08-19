# 分析算子库 v2

算子是边界明确、可复用的研究能力。每个 `.md` 文件由 YAML frontmatter 和 Markdown 指令正文组成：frontmatter 声明标识、适用范围、输入与输出契约，正文说明分析步骤、证据要求和判定边界。

当前目录包含：

- **37 个用户可见研究算子**：可在算子库查看并被研究框架引用。
- **5 个内部历史实现**：只在严格历史验证中替换仅当前可用的算子，不显示为普通算子。
- `misc/test_placeholder.md`：测试夹具，不计入产品算子。

## 目录与数量

| 目录 | 数量 | 作用 |
|---|---:|---|
| `screening/` | 4 | 数据可信度、快速排除和背景识别 |
| `fundamental/` | 6 | 负债、周期、现金流、管理层与业绩质量 |
| `valuation/` | 6 | 所有者收益、估值陷阱、安全边际和目标区间 |
| `decision/` | 3 | 压力测试、仓位和最终决策 |
| `special/` | 2 | 烟蒂股、轻资产等特殊模式 |
| `forward_risk/` | 5 | AI、政策、行业、情绪和新闻风险 |
| `bank/` | 4 | 银行资产质量、息差、压力测试和 PB-ROE 估值 |
| `manufacturing/` | 3 | 产能周期、供应链地位和 ROIC |
| `consumer/` | 2 | 品牌护城河和成长质量 |
| `tech/` | 2 | 科技成长和估值 |
| `history_adapters/` | 5 | 严格历史验证的内部等价实现 |

## 用户可见算子

### 通用算子（26 个）

| 分类 | 算子 ID |
|---|---|
| 筛选 | `data_source_grading`、`geopolitical_exclusion`、`quick_screen_5min`、`soe_identification` |
| 基本面 | `cash_trend_5y`、`cycle_analysis`、`debt_structure`、`management_integrity`、`performance_restoration`、`stream_classification` |
| 估值 | `owner_earnings`、`pe_trap_detection`、`safety_margin`、`valuation_dividend`、`valuation_fcf`、`valuation_repair` |
| 决策 | `apple_trading_model`、`position_management`、`stress_test` |
| 特殊策略 | `cigar_butt`、`light_asset_model` |
| 前瞻风险 | `ai_disruption`、`policy_risk`、`industry_position`、`market_sentiment`、`news_signal` |

### 行业专项算子（11 个）

| 分类 | 算子 ID |
|---|---|
| 银行 | `bank_asset_quality`、`bank_nim`、`bank_stress_test`、`pb_roe_valuation` |
| 制造业 | `capacity_cycle`、`mfg_supply_chain_position`、`roic_analysis` |
| 消费 | `consumer_brand_moat`、`consumer_growth` |
| 科技 | `tech_growth`、`tech_valuation` |

算子是否适用于某个行业、需要哪些上下文以及可否用于历史时点，由文件本身的元数据声明。框架引用算子 ID，不复制算子正文。

## 严格历史验证

新闻、当前情绪、当前行业上下文等信息不能直接用于过去的分析日。框架验证在执行前检查所有算子的时间边界，并只允许以下两种结果：

1. 算子本身可以严格按历史时点执行，直接使用原算子。
2. 仅当前可用的算子存在输出字段和类型完全一致的历史实现，运行时切换到该实现。

若两者都不满足，验证在启动前失败。系统不会静默跳过算子，也不会把当前资讯填入历史截面。

| 当前分析算子 | 内部历史实现 |
|---|---|
| `valuation_dividend` | `valuation_dividend_history` |
| `policy_risk` | `policy_risk_history` |
| `industry_position` | `industry_position_history` |
| `market_sentiment` | `market_sentiment_history` |
| `news_signal` | `news_signal_history` |

历史实现的 `execution_mode` 为 `history_adapter`。注册表默认隐藏这类资产，框架校验还会逐字段比较它与原算子的输出契约。

## 创建或修改算子

1. 在对应业务分类中创建 `<operator_id>.md`。
2. 在 YAML frontmatter 中至少声明 `id`、`name` 和 `outputs`，并补充数据需求、行业门控和时间边界。
3. 在正文中写清分析步骤、证据优先级、异常处理和判定标准。
4. 通过算子库校验后，在 `strategies/<name>/strategy.yaml` 的章节中引用该 ID。
5. 运行框架校验和相关测试，确认输出契约没有破坏下游章节。

不要在算子内隐藏股票池筛选、跨章节调度或最终组合规则。这些职责分别属于截面策略、研究框架和综合章节。

## 版本约定

- `operators/v1/` 是历史冻结基线，用于复现实验，不接受常规功能修改。
- `operators/v2/` 是当前产品算子库。
- 本文的 37 个是仓库内置业务算子。`OperatorRegistry.list_all()` 默认排除内部历史实现，但仍会包含用户后来创建的算子；测试夹具不计入内置产品数量。

更完整的元数据和编排约束见 [算子设计](../../../docs/design/operators.md)。
