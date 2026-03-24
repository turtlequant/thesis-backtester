# 定量与定性算子设计

## 概念

算子（Operator/Factor）是系统中最小的可复用分析单元。分为两类：

| | 定量因子 (Factor) | 定性算子 (Operator) |
|--|-------------------|-------------------|
| **载体** | Python `.py` 文件 | Markdown `.md` 文件 |
| **目录** | `factors/` | `operators/` |
| **执行者** | 计算引擎（Pandas） | LLM Agent |
| **输出** | 数值（float / Series） | 文本分析 + 结构化 JSON |
| **预计算** | 是（存储为 Parquet） | 否（每次 Agent 运行时实时生成） |
| **用途** | 量化筛选、评分 | 章节分析指令 |

## 定量因子 (Factor)

### 文件规范

每个因子是一个独立的 `.py` 文件，包含 `META` 字典和 `compute` 函数。

```python
# factors/example_factor.py

META = {
    'id': 'factor_id',           # 唯一标识，也是存储列名
    'name': '因子显示名',         # 中文名
    'type': 'cross_section',     # cross_section | timeseries
    'description': '因子说明',
    'data_needed': ['indicator'], # 依赖数据类型
}

def compute(...):
    """计算逻辑"""
    ...
```

### 两种因子类型

#### 截面因子 (Cross-Section)

在某个交易日，对全市场所有股票计算一个值。

```python
# factors/dv.py — 股息率
META = {'id': 'dv', 'name': '股息率(%)', 'type': 'cross_section', 'data_needed': ['indicator']}

def compute(df: pd.DataFrame) -> pd.Series:
    return df['dv_ttm'].fillna(0).round(2)
```

**存储**: `data/tushare/daily/factors/{YYYY-MM}.parquet`

#### 时序因子 (Time-Series)

读取单只股票的历史数据，计算一个静态属性值。

```python
# factors/profit_growth_5y.py — 5年利润增速
META = {'id': 'profit_growth_5y', 'name': '5年利润增速(%)', 'type': 'timeseries', 'data_needed': ['income']}

def compute(ts_code: str, api) -> float:
    inc = api.get_income(ts_code)
    annual = inc[inc['end_date'].str.endswith('12-31')]
    # ... CAGR 计算
    return round(cagr * 100, 2)
```

**存储**: `data/tushare/daily/ts_factors/latest.parquet`

### FactorRegistry

`src/engine/factors.py` — 自动发现和加载因子文件。

```python
class FactorRegistry:
    def __init__(self, strategy_dir=None):
        # 加载顺序：
        # 1. factors/ (全局因子)
        # 2. strategies/<name>/factors/ (策略私有因子，同 id 覆盖全局)

    def list_all(self) -> List[Factor]
    def list_cross_section(self) -> List[Factor]
    def list_timeseries(self) -> List[Factor]
    def compute_all(self, df) -> pd.DataFrame          # 批量计算截面因子
    def compute_timeseries_one(self, factor, ts_code)   # 计算单只股票的时序因子
```

### 新增因子步骤

1. 在 `factors/` 目录创建 `.py` 文件
2. 定义 `META` 字典（id, name, type, data_needed）
3. 实现 `compute` 函数
4. 执行预计算：
   - 截面因子：`python -m src.engine.launcher data recalc-factors`
   - 时序因子：`python -m src.engine.launcher data recalc-ts-factors`

系统自动发现新文件，无需修改任何配置。

## 定性算子 (Operator)

### 文件规范

每个算子是一个 `.md` 文件，包含 YAML frontmatter + Markdown 分析指令。

```markdown
---
id: operator_id               # 唯一标识
name: 算子显示名               # 中文名
category: valuation            # 分类目录
tags: [tag1, tag2]             # 分类标签
data_needed: [income, balance] # 需要查询的数据类型
outputs:                       # 输出字段定义 (用于自动 schema 生成)
  - field: field_name
    type: float
    desc: 字段说明
---

## 分析框架

这里是给 LLM Agent 的详细分析指令...
```

### 关键特性：自动 Schema 生成

v6 最重要的变化：**输出 Schema 从算子 frontmatter 的 `outputs` 字段自动生成**，不再需要手写 `output_schema.py`。

```python
# OperatorRegistry 方法
def compose_schema_text(self, op_ids: List[str]) -> str:
    """合并多个算子的 outputs，生成 JSON schema 文本"""
    fields = []
    for op_id in op_ids:
        op = self.get(op_id)
        for out in op.outputs:
            fields.append(f'  "{out.field}": {out.type}  // {out.desc}')
    return "```json\n{\n" + ",\n".join(fields) + "\n}\n```"
```

Agent 在 system prompt 中收到合并后的 schema，输出时用 `json` 代码块包裹结构化结论。

### 行业门控机制

部分算子包含**前置排除门控**，防止对不适用的行业/类型产生误导性分析：

| 算子 | 门控条件 | 排除后输出 |
|------|---------|-----------|
| `valuation_fcf` | 银行/保险/证券 | ev_fcf_multiple=0, turtle_rating="不适用" |
| `owner_earnings` | 银行/保险/证券/多元金融 | fcf=0, 改用 PPOP/内含价值等替代方法 |
| `cigar_butt` | 持续盈利企业/金融行业/大市值央国企 | is_cigar_butt=false, liquidation_value=0 |
| `light_asset_model` | 银行/保险/证券/地产/高负债 | is_light_asset=false |

门控逻辑写在算子 Markdown 正文中，由 LLM Agent 在分析时自行执行。

### 算子注册与组合

`src/engine/operators.py` — `OperatorRegistry`

```python
class OperatorRegistry:
    def __init__(self, config=None):
        # 加载顺序：
        # 1. operators/ (全局算子)
        # 2. strategies/<name>/operators/ (策略私有)

    def get(self, op_id) -> Operator
    def resolve(self, op_ids) -> List[Operator]         # 按 ID 列表解析，保序
    def compose_content(self, op_ids) -> str             # 合并多个算子的 Markdown
    def compose_data_needed(self, op_ids) -> List        # 合并数据需求（去重）
    def compose_schema_text(self, op_ids) -> str         # 合并输出 schema
    def list_by_tag(self, tag) -> List[Operator]
```

### 算子与章节的绑定

v6 中章节定义内联在 `strategy.yaml` 的 `framework.chapters` 中（不再使用独立的 `chapters.yaml`）：

```yaml
framework:
  analyst_role: 严谨的价值投资分析师
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
```

当 Agent 执行某章节时，系统自动：
1. 通过 `OperatorRegistry.resolve()` 加载该章节引用的算子
2. 通过 `compose_content()` 合并算子 Markdown 正文到 system prompt
3. 通过 `compose_schema_text()` 生成合并后的输出 JSON schema
4. 通过 `compose_data_needed()` 合并数据需求（用于 Agent 工具调用）

### 现有算子清单（37 个）

> v2 算子库包含 26 个通用算子 + 11 个行业专项算子（4 银行 + 3 制造 + 2 消费 + 2 科技）。

#### 筛选与排除类 (`operators/screening/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `quick_screen_5min` | 5分钟快速排除 | pass_screen, exclude_reason |
| `data_source_grading` | 数据源分级 | data_grade (A/B/C) |
| `geopolitical_exclusion` | 地缘政治排除 | geopolitical_risk_level |
| `soe_identification` | 央国企识别 | is_soe, controller_type |

#### 基本面分析类 (`operators/fundamental/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `debt_structure` | 负债结构分析 | debt_risk_level, interest_bearing_ratio |
| `cycle_analysis` | 周期分析 | cycle_position, cycle_adjusted_view |
| `cash_trend_5y` | 5年现金趋势 | fcf_trend, cash_conversion_rate |
| `management_integrity` | 管理层诚信 | integrity_score, red_flags |
| `stream_classification` | 流派分类 | investment_stream |
| `performance_restoration` | 业绩修复判断 | restoration_probability |

#### 估值类 (`operators/valuation/`)

| 算子 ID | 名称 | 输出字段 | 行业门控 |
|---------|------|---------|---------|
| `valuation_fcf` | FCF 估值 | ev_fcf_multiple, turtle_rating | 金融行业排除 |
| `valuation_dividend` | 股息估值 | dividend_yield_assessment |  |
| `owner_earnings` | 所有者收益 | owner_earnings, fcf, maintenance_capex | 金融行业替代 |
| `safety_margin` | 安全边际 | safety_margin_pct, margin_level |  |
| `pe_trap_detection` | PE 陷阱检测 | is_pe_trap, trap_type |  |
| `valuation_repair` | 估值修复 | repair_target, repair_catalyst |  |

#### 决策类 (`operators/decision/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `stress_test` | 极端压力测试 | survives_stress, stress_scenarios |
| `apple_trading_model` | 苹果交易模型 | normal_price, buy_price, sell_price |
| `position_management` | 仓位管理 | position_size, entry_strategy |

#### 特殊分析类 (`operators/special/`)

| 算子 ID | 名称 | 输出字段 | 行业门控 |
|---------|------|---------|---------|
| `cigar_butt` | 烟蒂股深度价值 | is_cigar_butt, liquidation_value | 盈利企业/金融/大市值央国企排除 |
| `light_asset_model` | 轻资产模式 | is_light_asset, asset_lightness_score | 金融/地产/高负债排除 |

#### 银行专项类 (`operators/bank/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `nim_analysis` | 净息差分析 | nim_trend, nim_sustainability |
| `asset_quality` | 资产质量 | npl_ratio_trend, provision_coverage |
| `capital_adequacy` | 资本充足性 | car_level, capital_buffer |
| `ppop_valuation` | PPOP 估值 | ppop_multiple, ppop_trend |

#### 制造业专项类 (`operators/manufacturing/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `capacity_cycle` | 产能周期 | capacity_utilization, cycle_phase |
| `cost_structure` | 成本结构 | cost_breakdown, cost_advantage |
| `order_book` | 订单簿分析 | order_visibility, backlog_months |

#### 消费专项类 (`operators/consumer/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `brand_moat` | 品牌护城河 | brand_strength, pricing_power |
| `channel_analysis` | 渠道分析 | channel_mix, channel_efficiency |

#### 科技专项类 (`operators/tech/`)

| 算子 ID | 名称 | 输出字段 |
|---------|------|---------|
| `rd_efficiency` | 研发效率 | rd_roi, capitalization_ratio |
| `platform_lockin` | 平台锁定 | switching_cost, network_effect |

### v6 章节分配

```
Ch01 数据核查      ← data_source_grading, geopolitical_exclusion, quick_screen_5min
Ch02 基本面分析    ← soe_identification, stream_classification, debt_structure, cycle_analysis, management_integrity
Ch03 现金流质量    ← cash_trend_5y, performance_restoration, owner_earnings
Ch04 估值安全边际  ← pe_trap_detection, valuation_fcf, valuation_dividend, safety_margin
Ch05 压力与特殊    ← stress_test, cigar_butt, light_asset_model
Ch06 投资决策      ← apple_trading_model, valuation_repair, position_management
```

## 定量 + 定性协同

```
                    strategy.yaml
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
     screening:    framework:   factors/
     (引用因子)    chapters:    operators/
                  (引用算子)
            │           │
            ▼           ▼
    ┌───────────┐ ┌──────────┐
    │ Screener  │ │  Agent   │
    │ 读取预计算 │ │ 按算子指令│
    │ 因子值    │ │ 分析数据  │
    └─────┬─────┘ └────┬─────┘
          │            │
          ▼            ▼
    50只候选股    结构化分析结论
          │            │
          └──────┬─────┘
                 ▼
          Backtest 验证
```

**筛选阶段**（定量）：因子提供快速过滤和排序的数值指标
**分析阶段**（定性）：算子指导 Agent 对候选股票进行深度定性分析

两者共享同一个 `strategy.yaml` 配置，但执行路径完全独立。

## 扩展指南

### 定量因子扩展

| 场景 | 方案 |
|------|------|
| 新截面指标（如 PS_TTM） | 新建 `.py`，`compute(df)` 从 indicator 列计算 |
| 新时序属性（如 10年ROE趋势） | 新建 `.py`，`compute(ts_code, api)` 读取财报计算 |
| 策略私有因子 | 放在 `strategies/<name>/factors/`，同 id 覆盖全局 |
| 复合因子（依赖其他因子） | `compute(df)` 中引用已有因子列（如 `df['ep'] * df['dv']`） |

### 定性算子扩展

| 场景 | 方案 |
|------|------|
| 新分析维度（如 ESG） | 新建 `.md`，编写 frontmatter（含 outputs）+ 分析框架 |
| 修改分析深度 | 编辑现有 `.md` 的 Markdown 内容 |
| 添加行业门控 | 在 Markdown 正文中添加"前置排除门控"章节 |
| 策略私有算子 | 放在 `strategies/<name>/operators/` |
| 算子复用 | 多个章节引用同一个算子 ID |

## v5.5.6 → v6 关键变更

| 维度 | v5.5.6 | v6 |
|------|--------|-----|
| 章节定义 | `chapters.yaml` 独立文件 | `strategy.yaml` 内联 `framework.chapters` |
| 输出 Schema | `output_schema.py` 手写 dataclass | 算子 frontmatter `outputs` 自动生成 |
| 算子总数 | 14 个 | 37 个（含 11 个行业专项） |
| 章节数 | 10 章 | 6 章（更紧凑） |
| 行业门控 | 无 | 4 个算子含前置门控 |
| 算子 frontmatter | id, name, tags, data_needed | 新增 category, outputs |
