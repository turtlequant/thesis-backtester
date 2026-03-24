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
| 算子库 | v1（冻结） | v2（37 个，含前瞻风险 + 行业专项） |
| 增强数据 | 无 | 新闻 + 资金流 + 大盘 + 行业（通过 Tool） |

## 使用方式

```bash
# CLI
python -m src.engine.launcher strategies/v6_enhanced/strategy.yaml live-analyze 601288.SH

# 桌面端投研工具
python src/desktop/main.py
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

## 桌面端投研工具

FastAPI + Vue 3 实现，替换原有 Streamlit 工作台。提供 6 个页面 + 浮动聊天助手。

### 页面布局

| 页面 | 功能 |
|------|------|
| Analysis | 股票分析（代码输入 + 框架选择 + 实时进度 + 结论展示） |
| Reports | 历史分析报告浏览与详情查看 |
| Operators | 算子库浏览（37 个，按分类筛选） |
| Frameworks | 预设框架查看与自定义 |
| Data | 数据状态管理 |
| Settings | LLM 配置 + 系统参数 |

浮动聊天助手：全局可用，支持投研问答。

### 预设框架

| 框架 | 章节 | 算子 | 定位 |
|------|------|------|------|
| V6 价值投资 | 6 | 21 (v1) | 回测验证版 |
| V6 增强分析 | 8 | 26 (v2) | 深度 + 前瞻风险 + 一致性裁决 |
| 快速评估 | 3 | 11 (v2) | 10-15 分钟快速判断 |
| 收息型分析 | 5 | 15 (v2) | 高股息可持续性专用 |
| 银行专项分析 | 6 | 行业专项 (v2) | 银行业专用算子 + 行业特异性指标 |

### 实时进度

通过 `on_progress` 回调实现。`run_blind_analysis()` 在每个章节开始/完成和综合研判前后发送事件，前端通过 WebSocket 实时更新状态。

进度事件：`snapshot_done` · `chapter_start` · `chapter_done` · `synthesis_start` · `synthesis_done`

## 算子版本管理

```
operators/
├── v1/    # 冻结（21 个，绑定 +7.1pp 回测结果）
└── v2/    # 活跃开发（37 个，含前瞻风险 + 行业专项算子）
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
| `src/desktop/main.py` | FastAPI + Vue 3 桌面端投研工具（6 页面 + 聊天助手） |
| `src/desktop/batch_live.py` | 模拟盘批量分析（多股票 + 组合级汇总） |

所有改动对回测模块非侵入——新增参数均为 Optional，不传时行为不变。

---

*文档版本: v2.0*
*更新日期: 2026-03-19*
