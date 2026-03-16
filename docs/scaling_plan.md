# 规模扩展与框架优化计划

## 一、当前状态（v6）

| 维度 | 当前 | 目标 |
|------|------|------|
| 样本量 | 120（12截面 × 10只/截面） | 600+（提高 agent_batch 或 top_n） |
| 截面频率 | 半年（12个截面，2020-2025） | 季度/月度可配置 |
| 验证指标 | 1m/3m/6m/12m + 回撤 + 分红 | 已完备 |
| 基准对比 | 沪深300 + 筛选池 + Agent 精选 | 五基准体系已实现 |
| 框架 | V6（21算子，6章节） | 支持多策略实例 |
| Agent 工具 | 16种数据查询 | 已实现 |

### 已实现的 Pipeline

三步独立执行，每步可中断/续跑：

```bash
backtest-screen              # ① 生成截面 + 筛选 + 保存 CSV（秒级）
backtest-agent [--dry-run]   # ② 并发 Agent 分析 + 进度/重试/增量（小时级）
backtest-eval                # ③ 前向收益 + 五基准评估（分钟级，带缓存）
```

## 二、扩展方案

### Phase 1：全量回测（当前进行中）

12个半年截面 × 每截面 10 只 = 120 只 Agent 分析。

**运行方式**：
```bash
# 查看任务量和成本预估
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent --dry-run

# 执行（增量，已有报告自动跳过）
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-agent

# 评估绩效
python -m src.engine.launcher strategies/v6_value/strategy.yaml backtest-eval
```

**预估成本**：~¥48（119只 × ¥0.4/只，DeepSeek 定价）
**预估耗时**：~1小时（并发10）

**价值**：
- 五基准绩效对比，验证筛选策略和 Agent 的 alpha
- 按龟级/行业/截面的归因分析
- 建立 Agent 分析质量的基线数据

### Phase 2：提升覆盖度

两个方向可同时推进：

**2a. 增加每截面分析数量**
```yaml
screening:
  agent_batch:
    ratio: 0.4    # 20% → 40%
    max: 30       # 20 → 30
```
效果：120 → 240-360 只，成本线性增长。

**2b. 增加截面密度**
```yaml
backtest:
  cross_section_interval: 3m    # 6m → 3m (季度)
```
效果：12截面 → 24截面，样本量翻倍。

### Phase 3：多策略对比

创建新策略实例验证引擎通用性：

```bash
strategies/
├── v6_value/       # 当前：深度价值 + 高股息
├── growth/         # 新建：成长股策略
└── cyclical/       # 新建：周期股策略
```

每个策略独立的 `strategy.yaml` + `chapters.yaml`，复用相同算子库和引擎。对比不同投资理念在同一时间段的表现。

## 三、框架配置化

### 已实现

v6 通过 `strategy.yaml` 一站式配置：

```yaml
screening:           # 量化筛选（声明式过滤 + 评分分级）
framework:           # 分析框架（算子驱动 + DAG 依赖）
  synthesis:         # 综合研判（思考步骤 + 评分锚点 + 决策边界）
backtest:            # 回测参数（日期 + 间隔 + 并发 + 前向周期）
llm:                 # LLM 配置（模型 + 温度 + token 限制）
```

### 创建新策略

1. 创建 `strategies/<name>/strategy.yaml`（参考 v6_value 的注释版配置）
2. 选择和组合已有算子（或创建新算子）
3. 运行 `backtest-screen` → `backtest-agent` → `backtest-eval`

无需修改任何引擎代码。

## 四、优先级排序

| 任务 | 优先级 | 状态 | 预期效果 |
|------|--------|------|---------|
| 三步 Pipeline | P0 | ✅ 已完成 | 端到端自动化 |
| 五基准绩效评估 | P0 | ✅ 已完成 | 沪深300 + 筛选 + Agent 多层 alpha |
| Phase 1: 全量120样本 | P0 | 🔄 进行中 | 建立基线数据 |
| Agent 稳定性（重试/超时） | P0 | ✅ 已完成 | 批量运行不崩溃 |
| Phase 2: 覆盖度提升 | P1 | 待 Phase 1 完成 | 样本量 → 300+ |
| 宏观环境算子 | P1 | 待开发 | 解决周期反转盲区 |
| Phase 3: 多策略对比 | P2 | 待开发 | 验证引擎通用性 |
| 月度截面 | P2 | 待 Phase 2 完成 | 完整产品能力 |

---

*文档版本: v3.0 (三步 Pipeline 架构)*
*更新日期: 2026-03-16*
