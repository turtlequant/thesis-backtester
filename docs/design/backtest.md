# 回测层设计

## 定位

验证 Agent 分析质量的闭环系统。通过多截面回测 → 前瞻收益采集 → 多基准绩效评估，量化评估投资框架和 Agent 的分析能力。

核心问题：**Agent 的分析结论在事后看来有多准确？筛选策略相比大盘有多少 alpha？**

## 三步独立 Pipeline

```
backtest-screen                 backtest-agent                 backtest-eval
┌─────────────────┐            ┌─────────────────┐            ┌─────────────────┐
│ ① 截面筛选       │            │ ② Agent 分析     │            │ ③ 绩效评估       │
│                  │            │                  │            │                  │
│ strategy.yaml    │    CSV     │ 读取筛选 CSV      │  reports   │ 读取报告+CSV     │
│ → 生成截面日期    │───────────→│ → 并发 Agent      │──────────→│ → 采集前向收益    │
│ → 逐截面筛选     │            │ → 进度/重试/增量   │            │ → 五基准评估      │
│ → 保存 CSV       │            │ → 保存 JSON+MD    │            │ → 输出报告        │
└─────────────────┘            └─────────────────┘            └─────────────────┘
      秒级                           小时级                         分钟级
      可反复跑                        可中断/续跑                     可反复跑
```

每步独立，可以随时中断、重跑，互不影响。

### 调用方式

```bash
# Step 1: 生成截面日期 + 逐截面筛选 + 保存 CSV
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-screen

# Step 2: 并发 Agent 分析 (增量/重试/进度)
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-agent
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-agent --dry-run   # 仅查看任务量和成本估算
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-agent --retry 2   # 失败自动重试2轮

# Step 3: 采集前向收益 + 多基准绩效评估
uv run python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml backtest-eval
```

### 配置 (strategy.yaml)

```yaml
backtest:
  start_date: '2020-06-30'           # 起始截面 (决定日期对齐: 06-30→06-30/12-31)
  end_date: '2025-12-31'             # 结束截面
  cross_section_interval: 6m         # 间隔 (6m/3m/1y/2w)
  top_n: 50                          # 每截面筛选候选数
  agent_concurrency: 10              # Agent 并发数
  forward_periods:                   # 前向收益评估窗口
  - {months: 1, label: 1个月}
  - {months: 3, label: 3个月}
  - {months: 6, label: 6个月}
  - {months: 12, label: 12个月}
```

## 五基准绩效体系

| 基准 | 来源 | 含义 |
|------|------|------|
| **沪深300** | tushare 指数日线 | 全市场基准，衡量被动投资收益 |
| **筛选池等权** | backtest-screen CSV | 全部通过量化筛选的候选等权，衡量筛选策略 alpha |
| **筛选池 Top** | CSV 中最高评级 | 最高评级等权，衡量分级的区分度 |
| **Agent 买入** | Agent 报告中建议买入 (≥70分) | 衡量 Agent 判断力 |
| **Agent Top5** | Agent 报告中评分最高 5 只 | 衡量 Agent 精选能力 |

Alpha 分析输出三层对比：
- 筛选池 vs 沪深300（量化筛选的 alpha）
- Agent 买入 vs 筛选池（Agent 的增量 alpha）
- Agent 买入 vs 沪深300（端到端 alpha）

## 模块详解

### pipeline.py — 三步 Pipeline 编排

核心模块，包含三个独立入口函数：

| 函数 | 职责 |
|------|------|
| `step_screen(config)` | 日期生成（月末对齐）→ 逐截面筛选 → 保存 CSV |
| `step_agent(config)` | 读 CSV → 并发 Agent → 进度/重试/增量 → 保存报告 |
| `step_eval(config)` | 读 CSV + 报告 → 采集前向收益（带缓存）→ 五基准评估 |

#### Agent 批量分析特性

- **增量**：自动跳过已有报告的股票，再次运行只补缺失的
- **进度**：`✓ [3/119 3%] 601288.SH | 68分 | 观望 | 312s | ETA 45min`
- **重试**：`--retry N` 失败后自动重试 N 轮
- **dry-run**：`--dry-run` 仅统计任务量、预估耗时和成本

#### 前向收益缓存

每次运行仍在 `outcomes_cache/outcomes_{date}.json` 保存独立结果快照；同时把可复用结果写入
`workspace/data/outcomes_cache/forward_outcomes.db`。共享缓存按数据源和截面隔离，换策略或新建任务时可直接复用，跨过新的 1/3/6/12 个月期限后会自动补算。多个截面的待计算窗口先合并，再在 SQLite 内一次关联原始收盘价与复权因子，避免逐截面重复扫描行情库。收益、回撤和波动率统一由后复权价格序列计算，不使用“原始价格收益 + 现金分红”的人工拼接方式。

### outcome_collector.py — 前瞻收益采集

采集分析截止日期之后的实际市场表现，作为质量评估的 ground truth。

```python
@dataclass
class ForwardOutcome:
    cutoff_price: float          # 基准价格
    return_1m/3m/6m/12m: float   # 各窗口后复权收益率
    max_drawdown_6m: float       # 6个月最大回撤
    max_gain_6m: float           # 6个月最大涨幅
    volatility_6m: float         # 日收益波动率
    actual_dividends: float      # 12个月内每股分红
    data_available_months: int   # 可用数据月数
```

回看窗口 15 天，覆盖春节/国庆等长假。

前向期限只有在观察日已经越过目标日期、且目标日前 10 个自然日内存在交易价格时才算成熟。未走完的 1/3/6/12 个月收益和 6 个月期间统计保持为空，不使用“截至当前”的部分收益替代。Outcome 缓存带语义版本；重新运行时旧口径缓存会失效，观察日跨过新的期限后也会自动重新采集。已经生成的旧报告仍按原始产物展示，但界面统一标记为“旧收益口径”，不会与新口径混淆。现金分红仍可作为投研事实单独记录，但不得再次加入绩效收益。

这里输出的是多截面的前向收益验证，不等同于包含持仓账本、交易成本和可成交性约束的组合回测。

### quality_scorer.py — 5 维质量评分

| 维度 | 权重 | 评估内容 |
|------|------|---------|
| 方向判断 | 40% | AI 看多/空 vs 实际涨跌 |
| 推荐质量 | 25% | 买入→赚钱? 回避→跌了? |
| 风险识别 | 15% | 有回撤时是否提前预警? |
| 安全边际 | 10% | 声称的安全边际是否兜住? |
| 分红准确度 | 10% | 分红预测 vs 实际分红 |

可评分条件：`data_available_months >= 3`

### batch_backtest.py — 量化筛选回测（独立）

在多截面运行量化筛选，评估筛选策略本身的历史表现。不涉及 Agent，可独立使用。

### batch_live.py — 批量当前分析

`src/batch_live.py` 对多只股票运行当前分析并生成汇总。桌面端的“最新研判”提供更完整的策略引用、任务预览、暂停续跑和报告索引；该脚本主要保留作 CLI 批处理入口。

### crosssection.py — 跨截面对比

三种模式：plan（规划）、prepare（准备快照）、compare（纵向对比分析结论变化）。

## 数据存储

```
{strategy_dir}/backtest/
├── screen_results/                        # Step 1 输出
│   ├── screen_2020-06-30.csv
│   ├── screen_2020-12-31.csv
│   └── ...
├── agent_reports/                         # Step 2 输出
│   ├── 601288.SH_2024-06-30_report.md
│   ├── 601288.SH_2024-06-30_structured.json
│   └── ...
├── outcomes_cache/                        # Step 3 缓存
│   ├── outcomes_2020-06-30.json
│   └── ...
├── backtest_report_20260316_1143.md       # Step 3 输出 (Markdown)
└── backtest_summary_20260316_1143.json    # Step 3 输出 (JSON)
```

## 设计约束

1. **无前视偏差**：分析基于 cutoff_date 之前的数据，收益采集基于之后的数据
2. **可复现**：相同样本 + 策略 + LLM → 可重现（temperature=0.1）
3. **渐进式**：可先 dry-run 看任务量，再小批量跑，最后全量
4. **增量安全**：每步可中断重跑，Agent 自动跳过已完成的
5. **配置驱动**：所有参数从 strategy.yaml 读取
