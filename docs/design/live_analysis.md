# 个股实时分析模块设计

## 定位

单股实时深度分析——用户输入股票代码，系统自动获取免费公开数据，通过算子 DAG 逐步分析，输出结构化报告。

与回测模块完全隔离，共享引擎层但数据获取和结果存储独立。

## 与回测模块的关系

| | 回测 (backtest) | 实时分析 (live) |
|--|----------------|----------------|
| 数据源 | Tushare（付费） | CrawlerProvider（AKShare，免费） |
| 时间 | 历史截面 | 当前最新 |
| 盲测 | 默认隐藏公司名 | 默认暴露公司名（非盲测） |
| 输出位置 | `strategies/xxx/backtest/` | `strategies/xxx/live/` |
| 算子库 | v1（冻结） | v2（26 个，含前瞻风险） |
| 增强数据 | 无 | 新闻 + 资金流 + 大盘 + 行业（通过 Tool） |

## 使用方式

```bash
# CLI
python -m src.engine.launcher strategies/v6_enhanced/strategy.yaml live-analyze 601288.SH

# Web 工作台
streamlit run src/web/app.py
```

## 数据层：CrawlerProvider

基于 AKShare 实现 DataProvider 协议。日线行情支持三源回退（东方财富 → 新浪 → 网易163）。

### 基础数据（注入 Snapshot Markdown）

| 数据类型 | 状态 |
|---------|------|
| 日线行情 | ✅ 三源回退 |
| 资产负债表 | ✅ 221 列，含公告日期 |
| 利润表 | ✅ 170 列，含公告日期 |
| 现金流量表 | ✅ 316 列，含公告日期 |
| 财务指标 | ✅ 86 列 |
| 分红历史 | ✅ |
| 十大股东 | ✅ 含公告日期 |
| 审计/主营/回购 | ❌ 降级处理（返回空） |

### 增强数据（通过 query_market_context Tool 按需获取）

| 数据类型 | Tool 参数 | 来源 |
|---------|----------|------|
| 个股新闻 | `info_type="news"` | 东方财富 |
| 主力资金流 | `info_type="fund_flow"` | 东方财富 |
| 大盘走势 | `info_type="market_index"` | 新浪（沪深300） |
| 行业板块 | `info_type="industry_overview"` | 同花顺 |

增强数据不注入 system prompt（避免 token 膨胀），Agent 在需要市场环境信息时主动调用 Tool 获取。回测模式下 Tool 返回空数据，算子自动降级。

### 数据完整性检查

三张核心财报（资产负债表 + 利润表 + 现金流量表）任一缺失 → 中止分析，避免浪费 LLM token。

## 输出结构

每次分析生成独立的自包含文件夹：

```
strategies/v6_enhanced/live/
└── 601288.SH_2026-03-18/
    ├── raw_data/           # 爬取的原始数据（含增强数据）
    │   ├── balancesheet.csv
    │   ├── income.csv
    │   ├── cashflow.csv
    │   ├── price_history.csv
    │   ├── dividend.csv
    │   ├── top10_holders.csv
    │   ├── news.csv
    │   ├── fund_flow.csv
    │   └── index_daily.csv
    ├── snapshot.json        # Snapshot 元数据
    ├── *_report.md          # 完整分析报告
    ├── *_structured.json    # 结构化结论
    └── run.log              # 运行日志
```

## Web 分析工作台

Streamlit 实现，替换原有策略配置编辑器。

### 界面布局

```
左侧:
  - 股票代码输入
  - 分析框架下拉选择（4 个预设）
  - 选中后显示策略描述 + 各章算子
  - 盲测模式开关
  - 开始分析按钮

右侧:
  - 数据获取状态
  - 各章节实时进度（⏳ / 🔄 / ✅）
  - 分析结论（评分 + 建议 + 风险）
  - 可展开：结构化 JSON / 各章详情 / 完整报告

历史记录 Tab:
  - 浏览过去的分析结果
  - 查看详情 + 原始数据
```

### 预设框架

| 框架 | 章节 | 算子 | 定位 |
|------|------|------|------|
| V6 价值投资 | 6 | 21 (v1) | 回测验证版 |
| V6 增强分析 | 8 | 26 (v2) | 深度 + 前瞻风险 + 一致性裁决 |
| 快速评估 | 3 | 11 (v2) | 10-15 分钟快速判断 |
| 收息型分析 | 5 | 15 (v2) | 高股息可持续性专用 |

### 实时进度

通过 `on_progress` 回调实现。`run_blind_analysis()` 在每个章节开始/完成和综合研判前后发送事件，Streamlit 通过 `st.empty()` 占位符实时更新状态。

进度事件：`snapshot_done` · `chapter_start` · `chapter_done` · `synthesis_start` · `synthesis_done`

## 算子版本管理

```
operators/
├── v1/    # 冻结（21 个，绑定 +7.1pp 回测结果）
└── v2/    # 活跃开发（26 个，含前瞻风险算子）
```

策略通过 `operators_dir` 指定版本，默认 v2。v1 永不修改。

## 实现文件

| 文件 | 职责 |
|------|------|
| `src/data/crawler/provider.py` | CrawlerProvider：AKShare + 三源回退 + 字段映射 + 增强数据 |
| `src/data/live_snapshot.py` | 从 CrawlerProvider 构建实时 Snapshot |
| `src/agent/tools.py` | 新增 `query_market_context` Tool（新闻/资金/大盘/行业） |
| `src/agent/runtime.py` | `on_progress` 回调 + 外部 `snapshot` 参数 |
| `src/engine/launcher.py` | `live-analyze` 命令 |
| `src/web/app.py` | Streamlit 分析工作台 |

所有改动对回测模块非侵入——新增参数均为 Optional，不传时行为不变。

## 下一步计划

### 近期（2026 Q2）

**模拟盘第一期**
- 截面日期：2026-06-30（半年报披露后）
- 范围：沪深300 成分股全量 Agent 评估（约 ¥120，5 小时）
- 产出：Top 10-15 持仓组合 + 每只完整分析报告
- 公开发布：雪球模拟组合 + 公众号报告全文
- 12 月底对账

**财报季自动触发**
- A 股财报披露节奏：4 月底（年报+一季报）、8 月底（半年报）、10 月底（三季报）
- 每个财报季结束后自动触发：`backtest-screen` → `backtest-agent` → 更新持仓
- 目标：每年 3 次有效评估（5 月初、9 月初、11 月初）

### 中期（2026 H2）

**三层生产架构**（详见 [production_roadmap.md](production_roadmap.md)）
- 第一层：财报驱动评估（季度，Agent 全量分析）
- 第二层：价格信号监控（每日，当前价 vs Agent 买卖价）
- 第三层：定向资讯校验（触发时，买入前查最近公告）

**v2 算子回测验证**
- 用 v2 算子（26 个）重跑 12 截面回测
- 对比 v1（+7.1pp）看增量 alpha
- 重点验证：前瞻风险算子是否改善地产误判、一致性裁决是否减少矛盾评分

### 长期

**扩大覆盖**
- 每截面分析数量：10 → 30（agent_batch ratio 提升）
- 截面频率：半年 → 季度
- 样本量：120 → 500+

**多策略对比**
- 在同一截面上跑不同策略（v6_enhanced / income_focus / quick_scan）
- 对比不同策略的选股重叠度和 alpha 差异

---

*文档版本: v2.1*
*更新日期: 2026-03-19*
