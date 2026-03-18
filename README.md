# Thesis Backtester — AI 驱动的投资分析框架

> 用 Markdown 写分析方法论，引擎按 DAG 严格执行，LLM 逐步推理。

把投资分析方法论编码为可执行算子，按依赖关系编排成 DAG，LLM 逐章执行——后一步建立在前一步的结论之上。不是让 AI 自由发挥，是让 AI **按你的方法严格分析**。

## 回测结果：+7.1pp Alpha

120 只股票 × 12 个半年截面 × 5 年（2020-2025），五基准对比：

| 基准 | 样本 | 6m 收益 | 胜率 | vs 沪深300 |
|------|------|--------|------|-----------|
| 沪深300 | 12 | +0.9% | 42% | — |
| 筛选池等权 | 600 | +4.0% | 53% | +3.0pp |
| **Agent 买入** | **43** | **+8.1%** | **65%** | **+7.1pp** |

![累计收益曲线](strategies/v6_value/backtest/backtest_chart_20260316_1448.png)

```
沪深300        +0.9%
                 │ +3.0pp  量化筛选 alpha
筛选池等权      +4.0%
                 │ +4.1pp  Agent 增量 alpha
Agent 买入      +8.1%    端到端 alpha: +7.1pp
```

**回避信号更强**：Agent 回避的股票 73% 后续下跌，排雷 alpha（-14.8pp）是选股 alpha（+6.4pp）的 2.3 倍。

> [完整报告](strategies/v6_value/backtest/backtest_report_20260316_1448.md) · [结构化数据](strategies/v6_value/backtest/backtest_summary_20260316_1448.json) · [120 份分析报告](strategies/v6_value/backtest/agent_reports/)

## 实时分析工作台

```bash
# 单股实时分析（免费数据，无需 Tushare）
python -m src.engine.launcher strategies/v6_enhanced/strategy.yaml live-analyze 601288.SH

# Web 工作台
streamlit run src/web/app.py
```

![投研分析工作台](docs/app_image/01_home.png)

<details>
<summary>查看分析过程截图</summary>

![数据获取](docs/app_image/02_data_fetching.png)
![分析进度](docs/app_image/03_chapter_progress.png)
![分析运行](docs/app_image/04_analysis_running.png)
![分析结果](docs/app_image/05_result.png)

</details>

4 个预设框架：

| 框架 | 章节 | 定位 |
|------|------|------|
| V6 价值投资 | 6 章 | 回测验证版（+7.1pp alpha） |
| **V6 增强分析** | **8 章** | **深度分析 + 前瞻风险 + 一致性裁决** |
| 快速评估 | 3 章 | 10-15 分钟快速判断 |
| 收息型分析 | 5 章 | 高股息可持续性专用 |

## 核心设计

**算子 DAG 编排 > 单次 Prompt**：每步结论传递给下一步，链式推理产出更好的结果。

```
strategy.yaml                    一站式配置：筛选 + 分析框架 + 评分体系 + LLM
       │
       ▼
┌─── Engine ──────────────────────────────────────────────────────┐
│  StrategyConfig · Launcher · OperatorRegistry · FactorRegistry  │
└──────┬──────────────┬───────────────────┬───────────────────────┘
       │              │                   │
  ┌────▼────┐   ┌─────▼──────┐   ┌───────▼────────┐
  │Screener │   │   Agent    │   │   Backtest      │
  │量化筛选  │   │ 26算子DAG  │   │  Pipeline       │
  │ 因子评分 │   │ 三层评分   │   │ screen → agent  │
  └────┬────┘   └─────┬──────┘   │   → eval        │
       │              │          └───────┬────────┘
┌──────▼──────────────▼─────────────────▼───────────────────────┐
│  Data Layer: Provider抽象 · Parquet存储 · 时点快照 · 查询API   │
└───────────────────────────────────────────────────────────────┘
```

| 设计 | 做法 |
|------|------|
| **算子驱动** | 26 个 `.md` 算子，策略通过 YAML 组合，无需写代码 |
| **盲测** | 隐藏公司名称，消除 AI 品牌偏见和记忆污染 |
| **时间边界** | 数据层按公告日过滤 + Prompt 注入 + 工具沙盒，三层防护 |
| **三层评分** | 思考步骤引导推理 → 评分锚点校准 → 决策边界强制一致 |
| **五基准对比** | 沪深300 / 筛选池 / Top 评级 / Agent 买入 / Agent Top5 |

<details>
<summary>Agent 分析流程（DAG 依赖图）</summary>

```mermaid
graph LR
    CH1[Ch1 数据核查<br/>数据可信吗？]
    CH2[Ch2 基本面<br/>什么类型的公司？]
    CH3[Ch3 现金流<br/>利润是真金白银吗？]
    CH4[Ch4 估值<br/>当前价格低估吗？]
    CH5[Ch5 压力测试<br/>最坏情况如何？]
    CH6[Ch6 投资决策<br/>怎么买卖？]
    SYN[综合研判<br/>思考步骤 → 评分 → 建议]

    CH1 --> CH2 & CH3
    CH2 --> CH3 & CH4
    CH3 --> CH4 & CH5
    CH4 --> CH5 & CH6
    CH5 --> CH6
    CH6 --> SYN

    style SYN fill:#ff6b35,color:#fff
    style CH1 fill:#4a90d9,color:#fff
    style CH2 fill:#4a90d9,color:#fff
    style CH3 fill:#4a90d9,color:#fff
    style CH4 fill:#4a90d9,color:#fff
    style CH5 fill:#4a90d9,color:#fff
    style CH6 fill:#4a90d9,color:#fff
```

</details>

<details>
<summary>回测 Pipeline（三步独立）</summary>

```bash
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-screen   # ① 筛选（秒级）
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent    # ② Agent（小时级）
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-eval     # ③ 评估（分钟级）
```

每步独立，可中断/续跑。Agent 自动跳过已完成的分析。

</details>

## 快速开始

```bash
pip install -e .
export LLM_API_KEY="your_key"
export LLM_BASE_URL="https://api.deepseek.com"

# 实时分析（免费数据，无需 Tushare）
python -m src.engine.launcher strategies/v6_enhanced/strategy.yaml live-analyze 601288.SH

# 或启动 Web 工作台
streamlit run src/web/app.py
```

<details>
<summary>回测模式（需要 Tushare）</summary>

```bash
export TUSHARE_TOKEN="your_token"

# 数据初始化
python -m src.engine.launcher data init-basic
python -m src.engine.launcher data init-market 2020-01-01

# 量化筛选
python -m src.engine.launcher strategies/v6_value/strategy.yaml screen 2024-06-30

# 回测 Pipeline
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-screen
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-eval
```

</details>

<details>
<summary>创建自己的策略</summary>

1. 创建 `strategies/<name>/strategy.yaml`（参考 [v6_value](strategies/v6_value/strategy.yaml) 的完整注释版）
2. 定义量化筛选条件（`screening`）
3. 组合算子为章节（`framework.chapters`）
4. 运行 `backtest-screen` → `backtest-agent` → `backtest-eval`

无需编写代码，输出 Schema 从算子 `outputs` 字段自动生成。

</details>

<details>
<summary>目录结构</summary>

```
src/
├── engine/        # 引擎层：配置 + 启动器 + 注册表
├── data/          # 数据层：Provider + Parquet + 快照 + 免费爬虫
├── agent/         # Agent层：LLM 分析（DAG调度 + tool_use）
├── screener/      # 筛选层：声明式量化筛选
├── backtest/      # 回测层：三步 Pipeline + 五基准评估
└── web/           # Web层：Streamlit 分析工作台

operators/v1/      # 算子库 v1（21 个，冻结，绑定回测结果）
operators/v2/      # 算子库 v2（26 个，含前瞻风险算子）
strategies/        # 策略实例（4 个预设框架）
```

</details>

## 文档

- [架构](docs/design/architecture.md) · [Agent](docs/design/agent.md) · [数据层](docs/design/data_layer.md) · [算子](docs/design/operators.md) · [筛选](docs/design/screener.md) · [回测](docs/design/backtest.md) · [评分](docs/design/scoring.md) · [实时分析](docs/design/live_analysis.md)

## 许可证

Apache License 2.0

## 免责声明

本工具仅用于**投资方法论研究与验证**，不构成投资建议。历史回测结果不代表未来表现。

---

[English](README_en.md)
