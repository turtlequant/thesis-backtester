# 因子与分析算子设计

## 两类研究资产

| | 数值因子（Factor） | 分析算子（Operator） |
|---|---|---|
| 作用 | 计算可比较的截面指标 | 描述一个边界明确的定性研究方法 |
| 主要载体 | `*.factor.yaml`；兼容旧 Python 因子 | Markdown + YAML frontmatter |
| 执行者 | Polars/因子物化引擎 | 固定章节内的 LLM Agent |
| 输出 | 带语义、单位和精度的数值列 | 分析文本 + 结构化字段 |
| 主要用途 | 筛选、排名、历史截面回测 | 个股分析、批量研判、框架验证 |

二者共享的原则是：定义和数据分离、输出可校验、时间边界明确。因子不是定性结论，算子也不负责决定股票池或调度整个研究流程。

## 数值因子

### 原生字段与派生因子

因子库同时呈现两类资产：

- **原生字段**由 `src/data/catalog/native_fields.yaml` 维护统一语义，并由各 Provider 声明具体字段、频率和精确度。
- **派生因子**位于 `workspace/factors/definitions/`，通过输入字段映射和受限表达式定义计算逻辑。

系统统一的是上层语义，不会用另一 Provider 的字段静默补齐当前 Provider。兼容性、历史覆盖和物化状态分别展示。

### 派生因子格式

```yaml
schema_version: 1
id: ep
name: 盈利收益率
description: 盈利相对市价的收益率，等于 100 / PE_TTM。
category: valuation
tags: [valuation]
type: cross_section
grain: security_date
engine: polars
inputs:
  pe: valuation.pe_ttm
expression: round(safe_div(100.0, col("pe")), 2)
output:
  dtype: float64
  unit: percent
  direction: higher_better
policies:
  null: propagate
  point_in_time: strict
  enabled: true
```

定义必须说明：

1. 唯一 ID、名称、分类和用途。
2. 输入的统一语义字段，而不是某个 Provider 的私有列名。
3. 受限 Polars DSL 表达式、输出类型、单位和排序方向。
4. 空值与时点策略。
5. 对财务滚动因子，额外声明 `execution.mode: point_in_time` 和财报频率。

### 执行模式

- `row`：同一证券日期行内可以直接计算，适合估值倒数、市值换算等指标。
- `point_in_time`：必须以分析日之前已披露的财务记录形成滚动窗口，适合多年 ROE、利润增长和分红连续性。

新增或修改派生因子后，系统计算定义哈希。只有当前 Provider 输入完整、物化成功且哈希一致时，该因子才被标记为可用；定义变化只重算受影响的因子列。

### 兼容旧 Python 因子

根目录下已有的 `factors/*.py` 仍可被目录读取，以便兼容历史策略和结果。新建可编辑因子应优先使用 `*.factor.yaml` 和受限 DSL，避免执行任意代码成为普通用户的前置要求。

## 分析算子

### 文件格式

```markdown
---
id: operator_id
name: 算子名称
category: valuation
tags: [valuation]
data_needed: [income, balancesheet]
outputs:
  - field: conclusion
    type: str
    desc: 结构化结论
---

## 分析目标

说明分析步骤、证据要求、判定标准和不适用边界。
```

主要元数据：

| 字段 | 作用 |
|---|---|
| `id`、`name`、`category`、`tags` | 标识、展示和检索 |
| `data_needed` | 声明允许使用的数据类型 |
| `outputs` | 定义字段、类型和说明，供章节合并 Schema |
| `gate` | 声明行业或业务模式适用边界 |
| `weight`、`score_range` | 声明综合评分语义 |
| `history_variant` | 指向严格历史验证的内部实现 |
| `execution_mode` | `standard` 或仅内部使用的 `history_adapter` |

### 输出契约

`OperatorRegistry` 解析章节中的算子 ID，合并正文、数据需求和输出字段。输出字段是算子与框架之间的正式契约：

- 同一章节不能产生含义冲突的同名字段。
- 修改字段名或类型可能破坏下游章节与历史适配，必须经过框架校验。
- LLM 的自然语言正文可以变化，但结构化结果必须符合合并后的 Schema。

### 行业门控

不适用于某类公司的方法必须显式门控。例如一般企业 FCF 估值不能机械套用到银行，烟蒂股方法也不能对所有持续盈利的大市值公司强制给出清算价值。门控负责返回“为什么不适用”和约定的结构化状态，不能假装执行成功。

## 分层框架编排

框架在 `workspace/strategies/<name>/strategy.yaml` 中按章节组织算子：

```yaml
framework:
  chapters:
    - id: ch01_screening
      title: 数据核查与快速筛选
      operators:
        - data_source_grading
        - geopolitical_exclusion
        - quick_screen_5min
      dependencies: []
    - id: ch02_fundamental
      title: 基本面分析
      operators:
        - debt_structure
        - cycle_analysis
        - management_integrity
      dependencies: [ch01_screening]
```

这里的基本单元是“分析方向/章节”，每个章节可以并列组合多个算子；章节之间的依赖才构成 DAG。执行流程为：

1. 校验章节 ID、依赖和算子引用。
2. 拓扑排序，冻结当前框架内容。
3. 合并本章算子正文、数据需求和输出契约。
4. Agent 在本章边界内使用时点快照和数据工具完成分析。
5. 结构化输出进入后续依赖章节，最终由综合章节汇总。

这不是任意拖线式工作流。用户主要选择和维护完整研究框架，不需要逐次手工连接所有算子。

## 当前算子库

v2 当前包含 **37 个用户可见算子**：26 个通用算子，以及 11 个银行、制造、消费和科技行业专项算子。完整、可执行的 ID 清单以 [v2 算子目录](../../workspace/operators/v2/README.md) 为准。

`OperatorRegistry.list_all()` 默认只返回用户可见算子。`workspace/operators/v2/history_adapters/` 中另有 5 个内部历史实现，不计入产品算子数量。

## 严格历史适配

部分当前分析算子会使用新闻、情绪或当前行业上下文，不能原样回放到过去。此时原算子通过 `history_variant` 指向一个内部实现。替换必须同时满足：

1. 历史实现的 `execution_mode` 为 `history_adapter`。
2. 输出字段集合、字段类型与原算子完全一致。
3. 正文只允许使用分析日已经披露并进入快照的数据。
4. 历史实现不作为用户可选的新研究算子展示。

当前映射包括 `valuation_dividend`、`policy_risk`、`industry_position`、`market_sentiment` 和 `news_signal`。若映射缺失或输出契约不一致，框架验证会在启动前失败，不会跳过该算子。

## 定量与定性协作边界

```text
数值策略 → 当前/历史候选池 ───────────────┐
                                          ▼
                                  结构化研究框架
                                  章节 DAG + 算子
                                          │
                                          ▼
                                报告 / 框架增量效果
```

- 截面筛选只按数值条件和排序工作，不读取定性分析结果。
- 结构化投研可以单向引用已保存的筛选策略或候选池。
- 框架验证比较筛选池与框架判断的差异，回答定性框架是否带来增量效果。
- Agent 可以辅助生成结构化修改，但应用修改和正式执行仍走与人工界面相同的 API。

## 扩展检查清单

### 新增因子

- 统一语义字段是否存在，当前 Provider 的精度是否足够？
- 表达式是否可由受限 DSL 表达？
- 财务窗口是否按公告日而非报告期直接回填？
- 定义版本变化后是否触发正确的增量物化？
- 筛选、截面选股和历史验证是否得到一致值？

### 新增算子

- 是否是一项可复用研究能力，而不是完整流程或临时提示？
- 输入、步骤、证据优先级和不适用边界是否明确？
- 输出字段是否足够稳定，能被下游章节检查？
- 是否依赖仅当前可得的信息？若需要严格历史验证，是否有安全等价实现？
- 在算子库、框架编辑和实际执行中的行为是否一致？

### 修改框架

- 章节内部是否围绕同一分析方向组合算子？
- 依赖是否形成无环图，前置输出是否真的被后续使用？
- 当前研判与严格历史验证能否完成同一输出契约？
- 修改后是否产生新的框架指纹，旧结果是否退出当前上下文？
