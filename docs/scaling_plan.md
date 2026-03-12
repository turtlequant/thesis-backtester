# 盲测规模扩展与框架优化计划

## 一、当前局限

| 问题 | 当前 | 目标 |
|------|------|------|
| 样本量 | 60（每截面5只） | 300-600（每截面25-50只） |
| 截面频率 | 半年（12个截面） | 季度（24个截面），未来可月度 |
| 验证指标 | 仅6个月前向收益 | 1m/3m/6m/12m + 最大回撤 |
| 框架 | 仅V5.5.6 | 支持多框架对比 |
| 数据维度 | 基础财务+行情 | +行业对比+宏观+股东变化 |

## 二、扩展方案

### Phase 1：全量600样本（立刻可做）

已有12个半年截面 × 每截面50只 = 600样本的筛选和前向收益数据。

**工作量**：
1. 补齐财务数据：约86只新股票需要下载（~30分钟）
2. 生成540个新prompt（~20分钟）
3. 运行540个Sonnet Agent（60并行 × 9批 ≈ 45分钟）
4. 重新生成验证报告

**成本**：Sonnet调用约 $25-30
**时间**：约2-3小时（含等待）

**价值**：
- 样本从60→600，统计显著性大幅提升
- 不再是"精选样本"，而是"全量验证"
- 可以做更细粒度的归因分析（按行业/市值/龟级分组）

### Phase 2：季度截面（需要新跑筛选）

在半年截面之间插入季度截面（3月31日、9月30日）。

**需要做的**：
1. 对每个季度末运行龟级筛选（quick_filter）
2. 计算前向收益（1m/3m/6m/12m）
3. 生成prompt + 跑盲测

**新增截面**：2019-03/09, 2020-03/09, ..., 2024-03/09 = 12个新截面
**预计新增样本**：12 × 50 = 600样本
**累计总量**：~1200样本

### Phase 3：灵活截面频率

支持任意截面频率：
- 月度：每月末跑一次（72个截面 × 50 = 3600样本）
- 事件驱动：在重大事件节点增加截面（如2020-03疫情底部、2022-10政策底等）

注意：月度截面的6m前向收益会高度重叠（相邻月份重叠5/6），需要用独立样本统计方法。

## 三、框架灵活化

### 3.1 当前的硬编码问题

```python
# blind_batch.py 当前结构
# - 样本定义：硬编码在 blind_test_samples.json
# - prompt生成：调用 build_full_analysis_prompt(blind_mode=True)
# - 评分提取：正则匹配 "综合评分: XX/100"
# - 验证报告：硬编码格式
```

### 3.2 需要抽象的配置项

```yaml
# backtest_config.yaml（目标架构）

# 选股条件（可替换）
screening:
  name: "龟级筛选"
  module: "src.screener.quick_filter"
  params:
    pe_max: 12
    pb_max: 1.2
    dv_min: 4.0

# 分析框架（可替换）
framework:
  name: "V5.5.6价值投资"
  prompt_builder: "src.analyzer.prompt_builder"
  chapters: "config/framework_chunks/"
  # 或者用另一个框架:
  # name: "困境反转"
  # prompt_builder: "src.analyzer.turnaround_prompt"
  # chapters: "config/turnaround_chunks/"

# 回测参数（可调整）
backtest:
  cutoff_dates: "quarterly"    # monthly/quarterly/semi-annual/custom
  date_range: ["2019-01-01", "2024-12-31"]
  samples_per_section: 50      # 0=全量
  sampling_strategy: "all"     # all/extreme/random/stratified

# 验证维度（可扩展）
validation:
  forward_returns: [1, 3, 6, 12]   # 月
  include_max_drawdown: true
  score_thresholds:
    buy: 70
    avoid: 45
  groupby: ["industry", "turtle_rating", "market_cap_bucket"]
```

### 3.3 多验证指标

当前只看6个月前向收益，应扩展为：

| 指标 | 用途 |
|------|------|
| fwd_1m | 短期信号有效性 |
| fwd_3m | 中短期 |
| fwd_6m | 核心指标（当前） |
| fwd_12m | 长期价值验证 |
| max_dd_6m | 风险控制能力（AI回避的股票是否也回避了大回撤） |
| 夏普比 | 风险调整后收益 |
| 胜率 | 方向正确的概率 |
| 盈亏比 | 赚的时候赚多少/亏的时候亏多少 |

## 四、优先级排序

| 任务 | 优先级 | 工作量 | 预期效果 |
|------|--------|--------|---------|
| Phase 1: 全量600样本 | P0 | 3小时 | 统计说服力×10 |
| 多验证指标(1m/3m/6m/12m/回撤) | P0 | 1小时（数据已有） |  更全面的验证 |
| 框架配置化(YAML) | P1 | 1-2天 | 支持多框架对比 |
| Phase 2: 季度截面 | P1 | 1天 | 样本量→1200 |
| 数据维度扩展(P0项) | P1 | 1天 | 提升分析质量 |
| 多框架对比 | P2 | 取决于新框架 | 验证引擎通用性 |
| Phase 3: 灵活截面 | P2 | 2天 | 完整产品能力 |

## 五、全量600样本的执行计划

### Step 1: 补齐财务数据（30分钟）

```bash
# 找出600样本中缺少财务数据的股票
# 批量下载
```

### Step 2: 生成全量prompt（20分钟）

复用 blind_batch.py 的 generate_all_prompts()，但样本从60扩展到600。

需要修改 blind_test_samples.json 或创建新的样本文件。

### Step 3: 运行540个新Agent（45分钟）

60并行 × 9批，每批约5分钟。

### Step 4: 多维度验证报告

扩展 generate_report() 以支持：
- 按龟级分组统计
- 按行业分组统计
- 按市值分组统计
- 1m/3m/6m/12m 多周期收益
- 最大回撤对比

---

*文档版本: v1.0*
*创建日期: 2026-03-12*
