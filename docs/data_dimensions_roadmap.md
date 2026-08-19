# 数据维度扩展路线图

> **文档性质：历史研究记录。** 本文保存早期数据扩展设想，其中的状态和优先级不代表当前实现。当前数据契约见 [文档索引](README.md) 和 [数据层设计](design/data_layer.md)。

## 一、当前数据快照包含的维度

### v6 StockSnapshot 数据结构

| 类别 | 数据 | 字段 | 状态 |
|------|------|------|------|
| 元数据 | 行业分类 | `industry` | **已实现** |
| 元数据 | 地区 | `area` | **已实现** |
| 元数据 | 上市日期 | `list_date` | **已实现** |
| 行情 | 日线K线（3年） | `price_history` | 已实现 |
| 行情 | 每日指标（PE/PB/市值/股息率） | `daily_indicators` | 已实现 |
| 财报 | 资产负债表 | `balancesheet` | 已实现 |
| 财报 | 利润表 | `income` | 已实现 |
| 财报 | 现金流量表 | `cashflow` | 已实现 |
| 财报 | 财务指标（ROE/毛利率/负债率等） | `fina_indicator` | 已实现 |
| 分红 | 历史分红 | `dividend` | 已实现 |
| 股东 | 前十大股东 | `top10_holders` | 已实现 |
| 股东 | 前十大流通股东 | `top10_floatholders` | **已实现** |
| 治理 | 审计意见 | `fina_audit` | **已实现** |
| 治理 | 主营业务构成 | `fina_mainbz` | **已实现** |
| 治理 | 股权质押统计 | `pledge_stat` | **已实现** |
| 治理 | 股东户数变化 | `stk_holdernumber` | **已实现** |
| 治理 | 高管增减持 | `stk_holdertrade` | **已实现** |
| 治理 | 限售解禁 | `share_float` | **已实现** |
| 治理 | 回购 | `repurchase` | **已实现** |

### 快照 Markdown 输出结构

```
# 标的公司数据快照
├── 公司概况（行业、地区、上市日期）
├── 行情概览（收盘价、52周高低点、价格位置）
├── 估值指标（PE/PB/PS/股息率/市值）
├── 资产负债表（关键科目）
├── 利润表（关键科目）
├── 现金流量表（关键科目）
├── 核心财务指标（ROE/毛利率/净利率/负债率/流动比率）
├── 分红历史
├── 前十大股东（盲测模式下匿名化）
├── 前十大流通股东
├── 审计意见
├── 主营业务构成
├── 股权质押统计
├── 股东户数变化
├── 高管增减持
├── 限售解禁
└── 回购
```

## 二、AI分析中暴露的数据缺口

从60个盲测报告中，AI频繁提到"数据不足"的场景。以下标注各缺口的当前状态：

### 2.1 行业与公司身份信息

| 缺口 | v6 状态 | 说明 |
|------|---------|------|
| **行业分类** | **已解决** | StockSnapshot.industry，snapshot 输出中包含 |
| **上市时间** | **已解决** | StockSnapshot.list_date |
| **主营构成** | **已解决** | StockSnapshot.fina_mainbz，盲测模式下匿名化 |
| 所属概念/板块 | 未实现 | 优先级低，行业分类已覆盖主要需求 |

### 2.2 行业对比数据

| 缺口 | v6 状态 | 说明 |
|------|---------|------|
| **行业平均PE/PB** | 未实现 | 可从 daily_indicator 聚合计算 |
| **行业平均毛利率** | 未实现 | 需从 fina_indicator 按行业聚合 |
| **行业景气指标** | 未实现 | 需外部数据（P2） |

### 2.3 股东与治理

| 缺口 | v6 状态 | 说明 |
|------|---------|------|
| **实际控制人** | 部分解决 | `soe_identification` 算子从十大股东推断 |
| **股东户数变化** | **已解决** | StockSnapshot.stk_holdernumber |
| **高管持股/增减持** | **已解决** | StockSnapshot.stk_holdertrade |
| **股权质押** | **已解决** | StockSnapshot.pledge_stat |

### 2.4 宏观与市场环境

| 缺口 | v6 状态 | 说明 |
|------|---------|------|
| **宏观经济指标** | 未实现 | M2/社融/PMI/CPI（P2） |
| **货币政策信号** | 未实现 | P2 |
| **市场整体估值** | 未实现 | 可从现有数据计算全A平均PE/PB |
| **行业资金流向** | 未实现 | P3 |

### 2.5 更精细的财务数据

| 缺口 | v6 状态 | 说明 |
|------|---------|------|
| **分季度数据** | 未实现 | 可从累计值计算差值 |
| **关联交易** | 未实现 | P3 |
| **审计意见** | **已解决** | StockSnapshot.fina_audit |
| **银行专项指标** | 未实现 | 不良率/拨备/净息差（P2） |

## 三、扩展优先级排序

### P0 已完成项 ✓

以下数据已在 v6 的 `StockSnapshot` 和 `TushareProvider` 中实现：

- ✓ 行业分类（`industry`）
- ✓ 上市日期（`list_date`）
- ✓ 主营业务构成（`fina_mainbz`）
- ✓ 审计意见（`fina_audit`）
- ✓ 股东户数变化（`stk_holdernumber`）
- ✓ 高管增减持（`stk_holdertrade`）
- ✓ 股权质押统计（`pledge_stat`）
- ✓ 前十大流通股东（`top10_floatholders`）
- ✓ 限售解禁（`share_float`）
- ✓ 回购（`repurchase`）

### P1：下一步（已有数据可聚合计算）

| 数据 | 实现方式 | 预期改善 |
|------|---------|---------|
| **行业平均估值** | 从 daily_indicator 按行业聚合 | 解决"便宜是行业性还是个股性" |
| **市场整体估值** | daily_indicator 全市场聚合 | 提供市场环境背景 |
| **单季度财务** | 从累计值计算差值 | 看到季度拐点 |
| **大盘指数走势** | `index_daily` 上证/沪深300 | 市场环境参考 |

### P2：需要新数据源

| 数据 | 来源 | 预期改善 |
|------|------|---------|
| **宏观经济指标** | 央行/统计局（M2/社融/PMI/CPI） | **解决最大盲区：周期反转** |
| **行业景气指标** | 行业协会数据、商品价格指数 | 周期股择时能力 |
| **银行专项指标** | 专用接口/年报提取 | 银行股分析质量 |
| **公告文本** | 巨潮资讯 | 重大事件识别 |

### P3：长期方向

| 数据 | 来源 | 预期改善 |
|------|------|---------|
| ESG评分 | 第三方数据 | 治理风险维度 |
| 供应链关系 | 企业关联图谱 | 产业链传导分析 |
| 舆情数据 | 社交媒体/新闻 | 市场情绪维度 |
| 港股/美股对标 | 多市场数据源 | 跨市场估值锚定 |

## 四、实现方案

### 4.1 P1 实现方案

#### 行业平均估值

```python
# 在 snapshot.py 或 api.py 中实现
def get_industry_valuation(industry: str, trade_date: str) -> dict:
    """计算指定行业的估值中位数和分位数"""
    indicator = api.get_daily_indicator(trade_date, trade_date)
    stock_list = api.get_stock_list()
    merged = indicator.merge(stock_list[['ts_code', 'industry']], on='ts_code')
    industry_data = merged[merged['industry'] == industry]
    return {
        'pe_median': industry_data['pe_ttm'].median(),
        'pb_median': industry_data['pb'].median(),
        'dv_median': industry_data['dv_ttm'].median(),
    }
```

#### 单季度财务

```python
# 从累计值计算差值
def compute_quarterly(cumulative_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """从累计财报值计算单季度值"""
    df = cumulative_df.sort_values('end_date')
    # Q1 = 本期值（已是单季度）
    # Q2/Q3/Q4 = 本期累计 - 上期累计
    ...
```

### 4.2 P2 宏观数据方案

历史回测只需有限个截面的宏观快照，可以手工整理一次性录入（工作量约2小时）。

创建 `macro_environment.md` 算子，在 system prompt 中注入截面时点的宏观环境摘要（M2增速、PMI、全A估值水平等）。

## 五、预期效果评估

| 数据维度 | v6 状态 | 预期解决的问题 |
|---------|---------|---------------|
| 行业分类+上市日期 | ✓ 已实现 | AI 不再猜测行业 |
| 审计意见 | ✓ 已实现 | 排除财务造假嫌疑 |
| 主营构成 | ✓ 已实现 | 多元化/专注判断 |
| 股东户数/高管增减持 | ✓ 已实现 | 筹码集中度 + 内部人信号 |
| 股权质押 | ✓ 已实现 | 控股股东资金链风险 |
| 行业平均估值 | P1 待实现 | 行业性 vs 个股性低估 |
| 宏观环境 | P2 待实现 | **周期反转判断（最大盲区）** |

---

*文档版本: v2.0 (v6 架构)*
*更新日期: 2026-03-16*
*关联文档: docs/investment_thesis_backtester.md*
