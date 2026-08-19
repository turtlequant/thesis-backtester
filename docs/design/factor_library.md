# 因子库设计

## 目标

因子库把“数据源实际提供什么”和“研究者如何派生因子”分成两层：

1. 原生字段目录登记 Provider 的真实字段、语义、单位、频率和精确度。
2. 派生因子只引用稳定的语义字段，并用受限 Polars DSL 表达计算关系。
3. 筛选与历史验证只消费统一目录中兼容且满足时点要求的因子。

任何一次研究只使用一个 Provider。字段不可用时返回明确的 `unavailable`，不允许跨源静默补齐。

## 目录结构

```text
src/data/catalog/native_fields.yaml   # Provider 原生字段语义与绑定
src/data/field_catalog.py             # 原生字段解析和兼容性判断
workspace/factors/definitions/**/*.factor.yaml  # 新的派生因子定义
src/engine/factor_dsl.py              # 受限表达式编译与批量执行
src/engine/factor_catalog.py          # 原生字段、DSL、遗留 Python 的统一目录
```

现有 Python 因子只作为兼容实现保留；同 ID 的 DSL 定义会覆盖 Python 实现。原有 16 个多年财务因子已经迁移为公告时点 DSL，研究链路不再读取 `daily/ts_factors/latest` 的静态结果。

## Provider 能力边界

- **Tushare**：完整历史财务与治理因子的参考 Provider，具体可用性仍受 Token 权限和本地物化状态约束。
- **BaoStock**：行情、复权和基础估值 Provider。有限季度比率不等同于完整三大报表，缺少依赖时因子降级为不可用。
- **AKShare**：即时分析适配器，不作为严格历史因子基线。

兼容性只按精确语义绑定判定。目录支持 `exact`、`approximate`、`unavailable` 三种语义质量，但当前派生计算只接受 `exact`，避免近似字段悄然改变因子含义。

## DSL

因子定义示例：

```yaml
id: ep
name: 盈利收益率
engine: polars
kind: cross_section
category: valuation
expression: safe_div(lit(1.0), col("pe_ttm"))
inputs:
  pe_ttm: valuation.pe_ttm
optional_inputs: []
output:
  dtype: Float64
point_in_time: strict
```

表达式通过 Python AST 白名单编译，不使用 `eval`，不能访问文件、网络、Python 模块或任意属性。行级因子支持列、字面量、四则运算、比较、布尔组合，以及 `safe_div`、`round`、`abs`、`sqrt`、`exp`、`log`、`log1p`、`clip`、`fill_null`、`coalesce` 和 `when`。`optional_inputs` 中声明的输入在历史分区缺列时会被显式注入 null，适合 `coalesce` 回退；它不会改变 Provider 语义兼容性判断。

财报输入会自动切换为 `execution.mode: point_in_time`。该模式只读取年报行，按 `f_ann_date → ann_date → 保守披露截止日` 确定可见时间，支持 `lag`、`rolling_mean`、`rolling_sum`、`rolling_std`、`cagr` 和 `positive_streak`。计算结果先形成公告事件流，再通过 backward as-of join 对齐到每日交易截面；报告期本身不能让数据提前生效。

同一批公告时点 DSL 会共享一次财报字段加载，分别生成事件流后合并成宽表；每个月度日线分区只做一次 backward as-of join，避免逐因子重复扫描数据库和重复对齐交易日。

## 状态模型

因子库为每个资产展示三类独立状态：

- **Provider 兼容性**：依赖语义字段在当前数据源上是否精确可用。
- **物化状态**：当前 Provider 的 SQLite 中是否已存在对应列；兼容但未计算不会被误报为已经可用。
- **时点安全性**：是否声明并满足严格历史截面要求。遗留最新值因子不会进入严格历史研究。

派生因子的物化记录同时保存 `definition_hash`。定义保存后，所有旧 Provider 结果会立即标记为 `stale`；当前 Provider 如果具备精确输入和历史指标数据，会自动创建单因子后台任务，在完整历史区间定向覆盖该列。任务依次经历 `pending → computing → ready/failed`，不会删除或重算其他因子列。应用正常退出会先取消并等待计算线程收尾，中断任务回到 `stale`；异常进程退出产生的临时失败会在下次启动自动重试，公式或数据错误则保留为 `failed` 等待处理。

旧版本遗留、没有定义哈希记录的列显示为 `ready_unverified`；一旦编辑或手动重算，就进入严格的哈希校验生命周期。

目录同时给出两个消费能力：`current_screen` 和 `historical_screen`。定义始终可见，缺少本地输入或物化覆盖时通过 `materialization_blockers` 解释原因，不再通过“从下拉列表消失”表达不可用。当前筛选允许行级 DSL 在线补算；财报时点因子和历史回测必须使用覆盖目标日期的每日物化结果。

## 自动闭环

```text
原生数据下载
  → 语义字段与 Provider 精确度校验
  → DSL 定义/定义哈希
  → 行级或公告时点 Polars 计算
  → daily/factors(ts_code, trade_date)
  → 截面筛选 / 历史验证
```

应用启动时会核对所有内置和用户 DSL：输入已经下载且状态为未计算、过期或日期覆盖落后的定义会自动进入单线程数据任务队列。市场数据向前延伸时只补齐缺失日期；显式重下财务历史会使公告时点因子失效并触发重算。没有下载分红等输入时，因子详情列出阻塞原因并提供“补齐依赖并计算”；依赖任务完成后由统一协调器自动续接物化，不会生成伪数据。

Tushare 的核心财报继续按报告期批量下载；分红首次随“下载财务”建立可续传的逐股票历史基线，此后日常任务仅按公告日增量追加，避免反复扫描全部股票。

## API

- `GET /api/factors`：读取 Provider 感知的统一目录。
- `GET /api/factors/{id}`：读取单个资产及定义。
- `POST /api/factors/validate`：校验 DSL 定义但不落盘。
- `POST /api/factors`：创建 DSL 因子。
- `PUT /api/factors/{id}`：更新 DSL 因子，路径 ID 必须与定义一致。
- `POST /api/factors/{id}/prepare`：补齐缺失的原生数据，并在完成后自动续接物化。
- `POST /api/factors/{id}/materialize`：重新排队该因子的全历史定向计算。

删除暂不开放，以避免已有策略和历史实验失去依赖。创建或更新定义会自动排队物化；当前 Provider 缺少精确输入或历史指标时只保存定义，并明确保持不可用/未物化状态。
