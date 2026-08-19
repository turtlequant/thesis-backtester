# 盲测 Agent 设计

## 定位

LLM 驱动的定性投资分析系统。Agent 基于结构化财务数据（快照），按照投资框架（章节 DAG + 算子组合）逐步分析，通过 tool_use 主动查询数据，输出结构化评估结论。

核心特点：**盲测模式** — 隐藏公司名称和代码，强制 Agent 仅基于财务数据做出判断，消除认知偏差。

## 系统架构

```
┌────────────────────────────────────────────────────┐
│                 runtime.py (调度器)                  │
│  DAG 构建 → 拓扑排序 → 批次执行 → 综合分析          │
│  Prompt 组装（内联，无独立 PromptBuilder）            │
├────────────────────────────────────────────────────┤
│                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │  client.py   │  │  tools.py    │  │schemas.py│ │
│  │  LLM 客户端   │  │  工具沙盒    │  │输出Schema│ │
│  │  (OpenAI API) │  │  (16种查询)  │  │(JSON)    │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┘ │
│         │                 │                        │
│         │    ┌────────────┘                        │
│         ▼    ▼                                     │
│    Agent Loop (max 15 rounds)                      │
│    LLM ←→ tool_call ←→ tool_result ←→ LLM         │
└────────────────────────────────────────────────────┘
         │                 │
         ▼                 ▼
   OperatorRegistry     Snapshot
   (算子→prompt+schema) (时点数据)
```

## 分析流程

### 1. DAG 构建与调度

章节定义在 `strategy.yaml` 的 `framework.chapters` 中，章节之间通过 `dependencies` 形成有向无环图。

```yaml
# strategy.yaml 中的章节定义
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
  # ...
```

通过 Kahn 拓扑排序生成执行批次，同一批次内可并行：

```
Batch 1: [ch01_screening]              ← 入度=0
Batch 2: [ch02_fundamental]            ← ch01 完成后
Batch 3: [ch03_cashflow]               ← ch01+ch02 完成后
Batch 4: [ch04_valuation]              ← ch02+ch03 完成后
Batch 5: [ch05_stress]                 ← ch03+ch04 完成后
Batch 6: [ch06_decision]               ← ch04+ch05 完成后
```

### 2. 章节执行（Prompt 组装）

每个章节独立执行一次 Agent Loop。Prompt 组装由 `runtime.py` 的 `build_system_prompt()` 内联完成（无独立 PromptBuilder 模块）：

```
System Prompt 组成:
  ├── 角色定义 (analyst_role from config)
  ├── 时间边界 ("严格时间边界: {cutoff_date}")
  ├── 盲测规则 ("禁止猜测公司身份")
  ├── 行业提示 (金融行业特殊指标提醒)
  ├── 当前任务 ("第N章 — {title}")
  ├── 分析框架 (算子 content 拼接: _build_framework_content())
  ├── 数据快照 (snapshot_to_markdown, 预加载核心数据)
  ├── 工作方式 (优先使用快照，按需调用工具)
  ├── 输出要求 (直接输出结论，不叙述取数过程)
  └── 输出 Schema (compose_schema_text() 自动生成)

User Message:
  └── 前置章节输出 (prior_context: 依赖章节的 JSON 结构化结果)
```

### 3. 算子驱动的 Prompt 构建

`_build_framework_content()` 从 `OperatorRegistry` 加载算子：

```python
registry = config.get_operator_registry()
ops = registry.resolve(chapter['operators'])  # 按 ID 解析算子列表
for op in ops:
    # op.content = 算子 markdown 正文（不含 frontmatter）
    parts.append(f"### 算子 {i}: {op.name}\n\n{op.content}")
```

输出 Schema 从算子 frontmatter 的 `outputs` 字段自动生成：

```python
schema_text = registry.compose_schema_text(chapter['operators'])
# 输出格式: "字段列表：\n- **field_name** (type) — description"
```

### 4. 行业感知

`build_system_prompt()` 会检测行业并注入特殊提示：

```python
if snapshot.industry in ('银行', '保险', '证券', '多元金融'):
    # 注入金融行业特殊提示:
    # - 负债率 80-95% 属于正常
    # - 经营现金流/净利润不适用
    # - 应使用 ROE/净息差/不良率/拨备覆盖率
```

算子层面也有行业门控（如 valuation_fcf.md 的"金融行业估值禁区"），确保 LLM 不对银行使用 FCF 估值。

### 5. Agent Loop

```python
async def run_agent_loop(client, system_prompt, sandbox, prior_context):
    messages = [system_msg, user_msg]

    for round in range(MAX_TOOL_ROUNDS):  # max 15
        response = await client.chat(messages, tools=tool_definitions)

        if response has tool_calls:
            for tool_call in response.tool_calls:
                result = sandbox.execute(tool_call.name, tool_call.arguments)
                messages.append(tool_result_msg)
        else:
            # LLM 给出最终回答
            text = response.content
            structured = _extract_json_from_text(text)  # 取最后一个 ```json 块
            return (text, structured)
```

### 6. 综合分析 (Synthesis)

所有章节完成后，执行一次综合分析。综合 prompt 由三部分配置驱动：

**设计哲学**：算子管"看什么"，synthesis 管"怎么想"，评分留给 LLM 判断力。不用显式评分公式（那会退化为量化模型），而是通过结构化思考步骤引导 LLM 的推理路径。详见 [评分哲学](scoring.md)。

#### 思考步骤（thinking_steps）

引导 LLM 按固定认知路径推理，而不是直接"给 0-100 分"：

```yaml
framework:
  synthesis:
    thinking_steps:
      - step: 一票否决
        instruction: 检查致命问题 → 触发则直接回避，评分 ≤ 25
      - step: 识别投资机会类型
        instruction: 基于流派判定确认评估侧重
      - step: 核心矛盾
        instruction: 最可能亏钱的原因 vs 赚的是什么钱
      - step: 评分与决策
        instruction: 参照评分锚点，综合权衡
```

#### 评分锚点（scoring_rubric）

校准参考——告诉 LLM "90 分长什么样"，让不同标的的分数可比较：

```yaml
    scoring_rubric:
      - range: "85-100"
        description: "极度低估 + 现金流强劲 + 无重大风险 + 明确催化剂"
      - range: "70-84"
        description: "明确低估 + 基本面健康 → 买入区间"
      - range: "50-69"
        description: "有吸引力但存在疑虑 → 观望"
      - range: "30-49"
        description: "风险收益不对称 → 偏向回避"
      - range: "0-29"
        description: "重大风险 / 价值陷阱 → 明确回避"
```

#### 决策边界 + 输出字段

```yaml
    decision_thresholds: { buy: 70, watch: [30, 69], avoid: 29 }
  synthesis_fields:
    - '流派判定 / 龟级评定 / 核心估值 / 苹果买卖模型'
    - '一句话买入逻辑（可证伪）/ 关键风险 / 管理人诚信'
    - '最终建议: 买入/观望/回避 / 综合评分: 0-100 / 信心水平'
```

#### Synthesis Prompt 结构

```
build_synthesis_prompt() 组装:
  ├── 角色定义 + 时间边界 + 盲测规则
  ├── 各章完整分析文本（含推理过程和数据引用，回退到 JSON 字段）
  ├── 思考步骤（4步结构化推理）
  ├── 评分锚点（5级校准参考）
  ├── 决策边界（评分与建议一致性约束）
  └── 输出字段要求（synthesis_fields）
```

**完整文本 vs JSON 字段**：synthesis 默认接收每章的完整分析文本（包括 LLM 的推理过程、数据引用、具体论据），而不仅是提取出的 JSON 结论字段。这确保最终综合研判基于完整论据而非标签摘要。若 `chapter_texts` 不可用，则回退到 `chapter_outputs` 的 JSON 字段。

## 工具沙盒 (ToolSandbox)

Agent 通过 tool use 主动查询数据。`tools.py` 对外只提供受控的快照查询与分析上下文工具，并在工具参数内区分财务和市场数据类型；它不提供文件、网络或代码执行权限。

### 可用工具

#### query_financial_data

```json
{
  "name": "query_financial_data",
  "parameters": {
    "data_type": "price_summary|valuation|balance_sheet|income|cashflow|
                  financial_indicators|dividends|holders|float_holders|
                  audit_opinion|business_composition|pledge|holder_count|
                  disclosure_dates|adj_factor|industry_comparison",
    "periods": 4
  }
}
```

#### get_analysis_context

```json
{
  "name": "get_analysis_context"
}
```

返回：cutoff_date、行业、上市日期、最新报告期、数据来源列表、数据警告。

### 盲测匿名化

`holders` 数据在盲测模式下自动匿名化：

```python
def _classify_holder(name: str) -> str:
    # "中国证券金融股份有限公司" → "国有/政府关联股东"
    # "招商基金管理有限公司"     → "机构投资者"
    # "张三"                   → "自然人股东"
```

## LLM 客户端

### 配置

配置优先级：环境变量 > strategy.yaml

```yaml
# strategy.yaml
llm:
  base_url_env: LLM_BASE_URL    # 环境变量名
  api_key_env: LLM_API_KEY      # 环境变量名
  base_url: https://api.openai.com/v1  # 默认值
  model: gpt-4o
  max_tokens: 8192
  temperature: 0.1
```

### 异步执行

使用 `AsyncOpenAI` 客户端，支持同一批次内多章节并行分析。

## 输出处理

### JSON 提取

从 LLM 回复中提取最后一个 `\`\`\`json\`\`\`` 代码块：

```python
def _extract_json_from_text(text):
    pattern = r'```json\s*\n?(.*?)\n?\s*```'
    matches = re.findall(pattern, text, re.DOTALL)
    return json.loads(matches[-1]) if matches else None
```

### 结果保存

```
{backtest_dir}/agent_reports/
├── {ts_code}_{cutoff_date}_report.md       # 完整分析报告
└── {ts_code}_{cutoff_date}_structured.json # 结构化输出
```

## 调用方式

```bash
# Agent 盲测分析
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml agent-analyze 601288.SH 2024-06-30

# 非盲测模式
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml agent-analyze 601288.SH 2024-06-30 --no-blind

# 直接调用
uv run python -m src.agent.runtime workspace/strategies/v6_value/strategy.yaml 601288.SH 2024-06-30
```

## 安全约束

| 约束 | 实现方式 |
|------|---------|
| 时间边界 | Snapshot 在生成时已过滤，Agent 无法访问未来数据 |
| 数据隔离 | ToolSandbox 只暴露 Snapshot 中的数据，不能访问磁盘 |
| 工具限制 | 只有 2 个工具（query_financial_data + get_analysis_context），无文件/网络/代码执行 |
| 轮次限制 | MAX_TOOL_ROUNDS=15，防止无限循环 |
| 身份隐藏 | 盲测模式下 Prompt 中不包含公司名称/代码 |
| 行业门控 | 算子前置门控防止对金融行业使用不适用的估值方法 |
| 输出简洁 | Prompt 指令禁止叙述取数过程，直接输出分析结论 |
