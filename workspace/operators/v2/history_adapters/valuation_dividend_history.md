---
id: valuation_dividend_history
name: 债券视角股息估值法
category: valuation
tags: [valuation, dividend, yield, history_adapter]
execution_mode: history_adapter
data_needed: [daily_indicators, dividend, income, cashflow]
outputs:
  - field: dividend_yield_pct
    type: float
    desc: 截止日可见口径下的股息率(%)
  - field: dividend_sustainable
    type: bool
    desc: 股息是否可持续
---

## 分析目标

在截止日期当时可见的数据范围内，从“现金票息 + 可持续增长”的债券替代视角评估股息价值。

## 严格历史边界

- 只使用快照中的截止日行情、当时已公告分红、利润表与现金流量表。
- 禁止调用市场上下文，禁止使用当前国债收益率、当前利率环境或截止日之后的分红信息。
- 快照未提供截止日对应无风险利率时，不得虚构利率；改用固定、可复现的股息率分层，并明确写出“无历史无风险利率数据”。

## 分析步骤

1. 计算或读取截止日股息率；区分已实施、已公告未实施和不可确认分红。
2. 计算近年派息稳定性、股利支付率、自由现金流覆盖和经营现金流覆盖。
3. 使用固定分层评估票息吸引力：低于 2%、2%–3%、3%–5%、高于 5%；该分层只用于跨截面一致比较，不代表当时利率利差。
4. 检查利润、现金流、负债压力是否支持继续派息，识别一次性高股息和透支式分红。
5. 输出股息率、可持续性判断、证据日期与数据缺口；不得把缺失信息解释为正面证据。
