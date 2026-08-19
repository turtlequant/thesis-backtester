# 分析算子库 (Operators)

算子 = 一个独立的、可复用的分析指令单元。每个算子是一个 `.md` 文件，包含 YAML frontmatter（元数据 + 输出字段定义）和 Markdown 正文（分析指令）。

策略通过在 `strategy.yaml` 中组合算子构建完整的分析框架，无需编写 template 或手动拼接 prompt。

## 目录结构

```
operators/
├── screening/       # 筛选类 — 前置排除、数据核查、快速过滤
├── fundamental/     # 基本面 — 财务结构、周期、现金流、管理层
├── valuation/       # 估值类 — FCF、股息、PE陷阱、安全边际、所有者收益
├── decision/        # 决策类 — 买卖模型、仓位管理、压力测试
└── special/         # 特殊策略 — 烟蒂股、轻资产模式
```

## 算子清单 (21个)

### screening/ — 筛选类 (4个)

| id | 名称 | 输出字段 |
|----|------|----------|
| `data_source_grading` | 数据源分级与可信度体系 | data_confidence, data_warnings |
| `geopolitical_exclusion` | 地缘政治风险排除 | geo_risk_level, geo_risk_reason, geo_excluded |
| `quick_screen_5min` | 5分钟快速排除法 | price_position_pct, debt_ratio_pct, consecutive_profit_years, pass_screening, screening_notes |
| `soe_identification` | 央国企背景识别与分类 | is_soe, soe_type, controlling_shareholder |

### fundamental/ — 基本面 (6个)

| id | 名称 | 输出字段 |
|----|------|----------|
| `cash_trend_5y` | 5年现金趋势分析 | cash_trend_5y, latest_cash_balance |
| `cycle_analysis` | 周期位置与拐点分析 | is_cyclical, cycle_position |
| `debt_structure` | 负债结构拆解 | interest_bearing_debt, zero_interest_debt, debt_structure_assessment, cycle_debt_tolerance |
| `management_integrity` | 管理人诚信评估 | management_integrity, integrity_red_flags |
| `performance_restoration` | 业绩还原与投资视角分离 | reported_profit, non_cash_adjustments, adjusted_profit |
| `stream_classification` | 投资流派分类 | investment_stream, stream_reasoning |

### valuation/ — 估值类 (6个)

| id | 名称 | 输出字段 |
|----|------|----------|
| `owner_earnings` | 巴菲特所有者收益计算 | owner_earnings, owner_earnings_formula, fcf, maintenance_capex |
| `pe_trap_detection` | PE陷阱识别与规避 | pe_trap_warning, pe_trap_reasons, valuation_method |
| `safety_margin` | 动态安全边际（市场周期联动） | safety_margin_pct, market_condition, buy_point, sell_point |
| `valuation_dividend` | 债券视角股息估值法 | dividend_yield_pct, dividend_sustainable |
| `valuation_fcf` | 自由现金流(FCF)完整估值 | net_cash, ev, ev_fcf_multiple, turtle_rating, fair_value_per_share, topdown_return_pct |
| `valuation_repair` | 估值修复框架与目标价设定 | repair_target, repair_catalyst, expected_repair_return_pct |

### decision/ — 决策类 (3个)

| id | 名称 | 输出字段 |
|----|------|----------|
| `apple_trading_model` | 苹果买卖估值修复模型 | apple_normal_price, apple_buy_price, apple_sell_price, buy_logic_statement |
| `position_management` | 持仓与仓位管理 | recommendation, position_type, suggested_position_pct, exit_conditions, macro_event_impact |
| `stress_test` | 极端情景压力测试 | revenue_after_3y_decline, still_profitable, dividend_sustainable_under_stress, stress_test_result |

### special/ — 特殊策略 (2个)

| id | 名称 | 输出字段 |
|----|------|----------|
| `cigar_butt` | 烟蒂股深度价值分析框架 | is_cigar_butt, liquidation_value |
| `light_asset_model` | 轻资产商业模式分析框架 | is_light_asset, recurring_revenue_pct |

## 文件格式

每个算子 `.md` 文件由 YAML frontmatter + Markdown 正文组成：

```markdown
---
id: debt_structure
name: 负债结构拆解
category: fundamental
tags: [fundamental, debt, balance_sheet]
data_needed: [balancesheet, income]
outputs:
  - field: interest_bearing_debt
    type: float
    desc: "有息负债总额（亿）"
  - field: debt_structure_assessment
    type: str
    desc: "健康/可接受/警惕/危险"
---

## 负债结构深度拆解

### 一、负债分类树
...
```

### Frontmatter 字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `id` | 是 | str | 唯一标识符，与文件名一致（不含 `.md`） |
| `name` | 是 | str | 显示名称 |
| `category` | 否 | str | 所属分类：screening / fundamental / valuation / decision / special |
| `tags` | 否 | list | 标签列表，用于筛选和搜索 |
| `data_needed` | 否 | list | 所需数据类型（如 balancesheet, income, cashflow, daily_indicators 等） |
| `outputs` | 否 | list | 输出字段定义，每项含 `field`、`type`、`desc` |
| `weight` | 否 | float | LLM 评分权重，默认 1.0 |
| `score_range` | 否 | str | 评分范围，默认 "0-100" |

### outputs 字段类型

| type 值 | 映射 | 说明 |
|---------|------|------|
| `str` | string | 文本 |
| `float` | number | 数值 |
| `int` | integer | 整数 |
| `bool` | boolean | 布尔 |
| `list` | array of strings | 字符串列表 |

## 引擎加载机制

### 解析优先级

1. `strategies/<name>/operators/` — 策略私有算子（同名覆盖全局）
2. `operators/` — 全局共享算子（递归扫描子目录，跳过 README）

### 核心 API (`OperatorRegistry`)

```python
from src.engine.operators import OperatorRegistry

# 初始化（可选传入策略目录加载私有算子）
registry = OperatorRegistry(strategy_dir=Path("strategies/v6_value"))

# 按 ID 获取
op = registry.get("debt_structure")

# 批量解析（保持顺序，跳过缺失）
ops = registry.resolve(["debt_structure", "cycle_analysis"])

# 列出全部
all_ops = registry.list_all()

# 按标签筛选
debt_ops = registry.list_by_tag("debt")

# 合并多个算子的 content 为分析指令
prompt_text = registry.compose_content(["debt_structure", "cycle_analysis"])

# 合并 data_needed（去重）
data_types = registry.compose_data_needed(["debt_structure", "cycle_analysis"])

# 自动生成 outputs schema 描述（注入 system prompt）
schema_text = registry.compose_schema_text(["debt_structure", "cycle_analysis"])
```

### 自动 Schema 生成

`compose_schema_text()` 从算子的 `outputs` 定义自动生成结构化输出描述，无需手写 `output_schema.py`：

```
字段列表：
- **interest_bearing_debt** (number) — 有息负债总额（亿）
- **debt_structure_assessment** (string) — 健康/可接受/警惕/危险
- **cycle_debt_tolerance** (string) — 周期容忍判定(可接受/需观察/排除/不适用)
```

## 在策略中使用

章节和算子组合直接定义在 `strategy.yaml` 的 `framework.chapters` 中：

```yaml
framework:
  chapters:
  - id: ch01_screening
    chapter: 1
    title: 数据核查与快速筛选
    operators: [data_source_grading, geopolitical_exclusion, quick_screen_5min]
    dependencies: []

  - id: ch02_fundamental
    chapter: 2
    title: 基本面分析
    operators: [soe_identification, stream_classification, debt_structure, cycle_analysis, management_integrity]
    dependencies: [ch01_screening]

  - id: ch04_valuation
    chapter: 4
    title: 估值与安全边际
    operators: [pe_trap_detection, valuation_fcf, valuation_dividend, safety_margin]
    dependencies: [ch02_fundamental, ch03_cashflow]
```

运行分析时，引擎按章节顺序加载算子内容 → 聚合 data_needed → 生成 output schema → 构建 prompt → 调用 LLM。

## 创建新算子

1. 在对应分类目录下创建 `.md` 文件（文件名 = id）
2. 编写 YAML frontmatter（id、name、outputs 必填）
3. 编写 Markdown 正文（分析指令、步骤、判定标准、输出模板）
4. 在策略的 `strategy.yaml` 章节中引用该算子 id

算子应做到**独立完整**——单独阅读即可理解全部分析逻辑，不依赖其他算子的上下文。

## 创建新策略

只需两步：

1. 创建 `strategies/<name>/strategy.yaml`（定义筛选条件、章节算子组合、LLM 配置等）
2. 运行：
   ```bash
   # 量化筛选
   python -m src.engine.launcher strategies/<name>/strategy.yaml screen 2024-06-30

   # Agent 深度分析
   python -m src.engine.launcher strategies/<name>/strategy.yaml agent-analyze 601288.SH 2024-06-30
   ```
