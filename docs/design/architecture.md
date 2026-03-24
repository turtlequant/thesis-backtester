# 整体架构设计

## 定位

AI Agent 驱动的定性投资分析工具。通过可配置的策略实例，对 A 股股票进行结构化深度分析，并通过盲测回测验证分析质量。

核心理念：**Engine（论文无关）+ Instance（特定投资哲学）**，由 YAML 配置 + 算子组合驱动。

## 系统分层

```
┌─────────────────────────────────────────────────────────────────┐
│                        Strategy Instance                        │
│  strategy.yaml (筛选 + 章节 + 算子组合 + LLM 配置，一站式定义)    │
│  (每个投资哲学一个目录，所有参数在此定义)                           │
└─────────────────────────┬───────────────────────────────────────┘
                          │ 读取配置
┌─────────────────────────▼───────────────────────────────────────┐
│                      Engine Layer (src/engine/)                  │
│  StrategyConfig · Launcher · FactorRegistry · OperatorRegistry  │
│  Tracker (SQLite)                                               │
│  (策略无关的通用引擎，不含任何投资哲学假设)                         │
└──────┬──────────┬──────────┬──────────┬─────────────────────────┘
       │          │          │          │
┌──────▼───┐ ┌───▼────┐ ┌──▼────┐ ┌───▼──────┐
│ Screener │ │ Agent  │ │ Back- │ │ Desktop  │
│ 量化筛选  │ │ 盲测分析│ │ test  │ │ 投研工具  │
│          │ │        │ │ 回测  │ │ FastAPI  │
└──────┬───┘ └───┬────┘ └──┬────┘ └───┬──────┘
       │         │         │          │
┌──────▼─────────▼─────────▼──────────▼───────────────────────────┐
│                      Data Layer (src/data/)                      │
│  Provider(抽象) · Storage(Parquet) · Updater · FactorStore · API │
│  Snapshot(时点快照)                                               │
└──────┬──────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│                    External Data Sources                         │
│  Tushare API · AKShare（免费爬虫） · (CSV · Wind ... 未来扩展)     │
└─────────────────────────────────────────────────────────────────┘
```

## 核心模块职责

| 模块 | 路径 | 职责 | 依赖 |
|------|------|------|------|
| **StrategyConfig** | `src/engine/config.py` | 加载 YAML，提供所有策略参数的统一访问接口 | 无 |
| **Launcher** | `src/engine/launcher.py` | CLI 入口，命令分发（策略命令 + 数据命令） | StrategyConfig |
| **FactorRegistry** | `src/engine/factors.py` | 发现、加载、执行量化因子（截面 + 时序） | factors/ 目录 |
| **OperatorRegistry** | `src/engine/operators.py` | 发现、加载、组合定性分析算子（含自动 schema 生成） | operators/ 目录 |
| **Tracker** | `src/engine/tracker.py` | 分析运行生命周期管理（SQLite） | StrategyConfig |
| **QuickFilter** | `src/screener/quick_filter.py` | 声明式量化筛选（过滤 → 评分 → 分级） | Data API, FactorStore |
| **Agent Runtime** | `src/agent/runtime.py` | LLM Agent 盲测分析（DAG 调度 + tool_use + prompt 组装） | Snapshot, OperatorRegistry |
| **Backtest** | `src/backtest/` | 批量回测 + 前瞻收益采集 + 质量评分 | Agent, Data API |
| **Desktop App** | `src/desktop/main.py` | FastAPI + Vue 3 投研分析工具（6 页面 + 浮动聊天助手） | StrategyConfig, Screener |
| **DataProvider** | `src/data/provider.py` | 数据源抽象协议 + 注册表 | 无 |
| **Storage** | `src/data/storage.py` | Parquet 持久化（月分区/股票分区） | 无 |
| **DataUpdater** | `src/data/updater.py` | 数据获取编排（批量 + 增量） | Provider, Storage |
| **FactorStore** | `src/data/factor_store.py` | 因子预计算与存储 | Storage, FactorRegistry |
| **API** | `src/data/api.py` | 公共只读查询接口 | Storage |
| **Snapshot** | `src/data/snapshot.py` | 时点快照生成（严格时间边界） | API |

## 目录结构

```
invest_analysis/
├── src/
│   ├── engine/              # 策略无关引擎
│   │   ├── config.py        #   StrategyConfig
│   │   ├── launcher.py      #   CLI 入口
│   │   ├── factors.py       #   FactorRegistry（截面+时序）
│   │   ├── operators.py     #   OperatorRegistry（自动 schema）
│   │   └── tracker.py       #   运行追踪 (SQLite)
│   ├── data/                # 数据层
│   │   ├── provider.py      #   DataProvider 协议 + 注册表
│   │   ├── storage.py       #   Parquet 读写（含 predicate pushdown）
│   │   ├── updater.py       #   DataUpdater 编排
│   │   ├── factor_store.py  #   因子预计算
│   │   ├── api.py           #   只读查询接口（含 lru_cache）
│   │   ├── snapshot.py      #   时点快照（并行 I/O）
│   │   ├── settings.py      #   配置常量
│   │   └── tushare/         #   Tushare 实现
│   │       ├── __init__.py
│   │       └── provider.py
│   ├── agent/               # LLM Agent
│   │   ├── runtime.py       #   主调度器（DAG + prompt 组装 + agent loop）
│   │   ├── client.py        #   OpenAI 兼容异步客户端
│   │   ├── tools.py         #   工具沙盒（16 种数据查询）
│   │   └── schemas.py       #   输出 Schema 工具
│   ├── screener/            # 量化筛选
│   │   └── quick_filter.py
│   ├── backtest/            # 回测验证
│   │   ├── batch_backtest.py    # 批量截面回测
│   │   ├── crosssection.py     # 跨截面对比
│   │   ├── outcome_collector.py # 前瞻收益采集
│   │   └── quality_scorer.py   # 5维质量评分
│   └── desktop/             # FastAPI + Vue 3 Desktop App
│       ├── main.py          #   Entry point
│       └── batch_live.py    #   Mock portfolio batch analysis
├── factors/                 # 量化因子定义（.py）
├── operators/               # 定性分析算子（.md，含 YAML frontmatter）
│   ├── screening/           #   数据质量、地缘政治、快速筛选、央国企
│   ├── fundamental/         #   负债、周期、现金流、管理层、流派分类
│   ├── valuation/           #   FCF、股息、PE陷阱、安全边际、所有者收益、估值修复
│   ├── decision/            #   苹果模型、仓位管理、压力测试
│   ├── special/             #   烟蒂股、轻资产模式
│   ├── bank/                #   银行专项（4 个：NIM、资产质量、资本充足、PPOP）
│   ├── manufacturing/       #   制造业专项（3 个：产能周期、成本结构、订单簿）
│   ├── consumer/            #   消费专项（2 个：品牌护城河、渠道分析）
│   └── tech/                #   科技专项（2 个：研发效率、平台锁定）
├── strategies/              # 策略实例
│   └── v6_value/            #   V6 价值投资（算子驱动）
│       └── strategy.yaml    #   一站式配置：筛选 + 章节 + 算子 + LLM
├── data/                    # 本地数据存储
│   ├── tushare/             #   市场数据 (Parquet)
│   └── financial/           #   财报数据 (Parquet)
└── docs/                    # 设计文档
```

## 数据流

### 完整分析 Pipeline

```
strategy.yaml ──→ StrategyConfig
                      │
          ┌───────────┼───────────────────┐
          ▼           ▼                   ▼
    FactorRegistry  OperatorRegistry   章节定义
          │           │ (自动 schema)      │
          ▼           │                   │
    FactorStore       │                   │
    (预计算因子)       │                   │
          │           └───────┐           │
          ▼                   ▼           ▼
    QuickFilter         runtime.py ←── Snapshot
    (量化筛选)        (prompt 组装 + DAG) (时点快照)
          │               │
          ▼               ▼
    候选股票列表      Agent Loop (tool_use)
                          │
                          ▼
                    分析报告 + 结构化输出
                          │
                    ┌─────┼──────┐
                    ▼     ▼      ▼
              Tracker  Outcome  Quality
              (存储)   (收益)   (评分)
```

### 筛选 Pipeline（QuickFilter）

```
全市场 ~5500 只
    │
    ▼ 排除规则 (ST/退市/...)
  ~4000 只
    │
    ▼ 预计算截面因子 + 时序因子合并
    │
    ▼ 声明式过滤 (PE/PB/DV/市值...)
  ~300 只
    │
    ▼ 加权评分 (0-100)
    │
    ▼ 龟级分级 (金龟/银龟/铜龟/不达标)
    │
    ▼ Top N
  50 只候选
```

### Agent 分析 Pipeline

```
章节 DAG（strategy.yaml 中定义）
    │
    ▼ 拓扑排序 → 批次

Batch 1: [ch01_screening]              ← 无依赖
Batch 2: [ch02_fundamental]            ← 依赖 ch01
Batch 3: [ch03_cashflow]               ← 依赖 ch01, ch02
Batch 4: [ch04_valuation]              ← 依赖 ch02, ch03
Batch 5: [ch05_stress]                 ← 依赖 ch03, ch04
Batch 6: [ch06_decision]               ← 依赖 ch04, ch05

每个章节:
  算子加载 → compose_content() + compose_schema_text()
  ↓
  System Prompt = 角色 + 时间边界 + 行业提示 + 算子指令 + 快照 + schema
  ↓
  LLM Agent Loop (max 15 rounds)
    ├→ tool_call: query_financial_data(data_type, periods)
    ├→ tool_call: get_analysis_context()
    └→ 返回: 分析文本 + 结构化 JSON
  ↓
  输出作为后续章节的 prior_context
```

## 关键设计变更（v5.5.6 → v6）

| 维度 | v5.5.6 | v6 |
|------|--------|-----|
| 分析框架定义 | template.md 手写 Prompt 模板 | operators/*.md 算子组合 |
| 章节定义 | chapters.yaml 独立文件 | strategy.yaml 内联 framework.chapters |
| 输出 Schema | output_schema.py 手写 dataclass | 算子 frontmatter outputs 自动生成 |
| Prompt 组装 | FrameworkParser + PromptBuilder 独立模块 | runtime.py 内联 build_system_prompt() |
| 行业处理 | 无 | 算子前置门控 + system prompt 行业提示 |
| 数据查询 | 顺序 I/O | 并行 ThreadPoolExecutor + predicate pushdown |

## 设计原则

### 1. 算子驱动（Operator-Driven）

分析逻辑以算子（.md 文件）为最小单元。策略通过在 strategy.yaml 中组合算子构建分析框架，无需编写模板或手动拼接 prompt。输出 schema 从算子 frontmatter 的 outputs 字段自动生成。

### 2. 配置驱动（Config-Driven）

所有策略特定的值都在 `strategy.yaml` 中定义。引擎代码不包含任何投资哲学假设，不存在硬编码的默认值。

### 3. 时间边界（Time Boundary）

所有分析严格遵守截止日期。数据层按公告日期（ann_date）硬过滤，防止前视偏差（look-ahead bias）。

### 4. Provider 抽象

数据获取与存储解耦。通过 `DataProvider` Protocol 定义接口，更换数据源（Tushare → AKShare/CSV）只需实现协议。

### 5. 因子预计算

两类因子均预先全量计算，筛选时直接读取：
- **截面因子**：按交易日计算，月分区存储
- **时序因子**：每股票计算一次，单文件存储

### 6. 盲测验证

通过隐藏公司名称和代码，强制 Agent 仅基于财务数据做出判断，消除认知偏差。后续通过前瞻收益回测验证分析质量。

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| 语言 | Python 3.9+ |
| 数据存储 | Parquet (zstd 压缩) |
| 数据库 | SQLite (分析追踪) |
| LLM 接口 | OpenAI 兼容 API (async) |
| CLI | 内置 sys.argv 解析 |
| 桌面端 | FastAPI + Vue 3 |
| 数据源 | Tushare Pro API + AKShare（免费爬虫） |

## 扩展点

| 扩展方向 | 实现方式 |
|---------|---------|
| 新数据源 | 实现 `DataProvider` Protocol，注册到 provider registry |
| 新截面因子 | 在 `factors/` 添加 `.py` 文件，定义 `META` + `compute(df)` |
| 新时序因子 | 在 `factors/` 添加 `.py` 文件，`META.type='timeseries'`，`compute(ts_code, api)` |
| 新分析算子 | 在 `operators/` 添加 `.md` 文件，YAML frontmatter + Markdown 指令 |
| 新策略实例 | 创建 `strategies/<name>/strategy.yaml`，组合算子 |
| 新评分维度 | 在 `quality_scorer.py` 添加评分函数，更新权重 |
