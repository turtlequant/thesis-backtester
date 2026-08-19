# 数据层设计

## 设计原则

1. **单应用、多适配器**：BaoStock、Tushare、AKShare 都属于同一个产品，不对应不同版本。
2. **单次分析只用一个数据口径**：禁止用另一个数据源静默补字段，确保结果可解释、可复现。
3. **历史与当前推演一致**：BaoStock/Tushare 先下载到本地，再由分析、筛选和回测共用同一查询层。
4. **即时数据明确隔离**：AKShare 用于一次性即时分析，不进入严格历史数据库。
5. **时间边界优先**：财务数据按公告日、行情按交易日截断，避免前视偏差。

## 分层架构

```
┌──────────────────────────────────────────────────────┐
│ Consumer: api.py · snapshot.py · screener · backtest │
├──────────────────────────────────────────────────────┤
│ Computation: factor_store.py                          │
├──────────────────────────────────────────────────────┤
│ Orchestration: updater.py · jobs.py · auto scheduler  │
├──────────────────────────────────────────────────────┤
│ Persistence: provider-isolated SQLite                 │
├──────────────────────────────────────────────────────┤
│ Abstraction: DataProvider Protocol + capabilities     │
├──────────────────────────────────────────────────────┤
│ BaoStock adapter │ Tushare adapter │ AKShare adapter  │
└──────────────────────────────────────────────────────┘
```

上层模块只通过 `src/data/api.py` 读取数据。切换 provider 不改变分析、算子或回测接口。

## 数据源边界

| Provider | 定位 | 历史下载 | 主要能力 | 明确限制 |
|---|---|---:|---|---|
| BaoStock | 免费行情与基础估值基线 | 是 | 股票、日历、行情、复权、基础估值、有限季度指标 | 缺少完整三大报表、日频股息与治理等字段，不作为完整财务因子研究口径 |
| Tushare Pro | 订阅历史基线 | 是 | 行情、估值、完整财报、股东治理、分红等 | 权限由 Token、积分和套餐决定 |
| AKShare | 免费即时分析 | 否 | 即时公开行情、财务页面、新闻、资金流、行业和指数 | 网页字段可能变化；不作为严格历史回测基线 |

BaoStock 的 `balancesheet`、`income`、`cashflow` 适配表只承载其实际提供的比率或指标，不会伪造 Tushare 才有的完整科目。因子与算子读取不到的字段应明确表现为不可用，不会从 Tushare 或其他 Provider 静默补齐，并由因子库或报告的数据核查环节说明。

## 配置

数据配置保存在不入库的 `workspace/data/data_config.json`：

```json
{
  "provider": "baostock",
  "tushare_token": "",
  "data_start_date": "2015-01-01",
  "auto_update_enabled": false,
  "auto_update_time": "18:30",
  "auto_update_financials": true
}
```

环境变量 `DATA_PROVIDER`、`TUSHARE_TOKEN`、`DATA_START_DATE` 优先于文件配置，便于服务器部署。桌面端“设置”页面与命令行读取同一配置。

## SQLite 存储

```
data/
├── data_config.json
├── control.db                         # 下载任务与自动更新状态
├── providers/
│   ├── baostock/market.db
│   ├── tushare/market.db
│   └── akshare/market.db              # 即时模式通常不会创建
└── snapshots/
```

每个 provider 使用独立数据库，物理上阻止跨源混合。逻辑分区保存在各数据表的 `_partition` 列中：

| 数据类型 | 逻辑分区 | 合并键 |
|---|---|---|
| 股票列表、交易日历 | 固定分区 | 全量覆盖 |
| 日线、复权、每日指标、截面因子 | `YYYY-MM` | `ts_code + trade_date` |
| 时序因子 | `latest` | `ts_code` |
| 财务与治理数据 | `ts_code` | 核心财报保留 `ts_code + end_date + 公告/修订版本字段` |

`storage.py` 会按 DataFrame 字段演进 SQLite 表结构，并在 `_partition/ts_code/merge key` 上创建索引。已有上层代码继续使用 `save`、`load`、`load_financial` 等稳定接口。

## 下载与增量更新

- Tushare 按交易日获取全市场行情、复权因子和每日指标的完整快照，按报告期获取财报截面。
- Tushare 全市场接口统一使用 `limit + offset` 分页；核心财报按报告期流式下载、原子写入并记录完成标记，不在内存中累计全部年份。
- BaoStock 首次历史基线按股票和日期区间获取；基线完成后，尾部行情按交易日获取全市场不复权快照、复权因子和估值指标，避免每日逐股请求。
- 历史股票池包含当前上市和已经退市的股票，避免 BaoStock 逐股历史基线产生幸存者偏差。
- BaoStock 历史任务中断后，以 SQLite 中已有股票覆盖为准续传缺失股票；日增量按 `ts_code + trade_date` 合并，可安全重跑。
- BaoStock 财务数据按股票原子提交并记录安全报告期检查点；失败股票不会被标记完成，下次只补缺失检查点。
- BaoStock 与 Tushare 的行情、复权因子和估值指标均共用一个 SQLite 事务；三者全部写入后才提交交易日完成标记，任一失败会整体回滚。
- 日线表由 SQLite 唯一索引约束 `_partition + ts_code + trade_date`，应用层合并与数据库层约束共同防止重复记录。
- `DataUpdater` 自动检测本地最早分区和最新日期，支持向前回填与向后增量。
- 自动调度只在增量任务完整成功后记录当天已更新；失败或进程中断不会占用当天的成功标记。
- `DataJobManager` 单线程串行执行下载任务，持久记录 queued/running/completed/failed/cancelled 状态与进度。
- “立即增量”只维护已经初始化的财务基线，不会在空库中隐式启动耗时的全历史财务下载。
- 自动更新调度器在应用运行期间每 30 秒检查一次配置；成功后当日不再重复，失败重试至少间隔 15 分钟。

桌面“数据”页支持：

- 初始化股票列表和交易日历；
- 按日期、可选股票代码下载行情；
- 下载财务数据；
- 完整初始化与立即增量更新；
- 查看 SQLite 数据集、行数、分区、最新日期和任务进度；
- 取消正在执行的任务。

命令行仍可使用：

```bash
uv run python -m src.engine.launcher data init-basic
uv run python -m src.engine.launcher data init-market 2020-01-01
uv run python -m src.engine.launcher data update-financials 601288.SH
uv run python -m src.engine.launcher data daily-update
uv run python -m src.engine.launcher data status
```

## 时间边界

`snapshot.create_snapshot(ts_code, cutoff_date)` 使用以下规则：

- 行情：`trade_date <= cutoff_date`；
- 财务：优先使用 `f_ann_date`，其次 `ann_date`；
- 分红、股东与治理事件：使用各自公告/生效日期；
- 无公告日期时采用保守回退，不把报告期本身当作当时已知日期。

严格历史分析不允许引入新闻、资金流等只在当前时点可获取、但历史截面无法复原的数据。
