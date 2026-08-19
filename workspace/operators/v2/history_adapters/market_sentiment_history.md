---
id: market_sentiment_history
name: 市场情绪与资金面分析
category: forward_risk
tags: [risk, market, history_adapter]
execution_mode: history_adapter
data_needed: [price_history, daily_indicators, fina_indicator]
outputs:
  - field: sentiment_level
    type: enum [极度乐观, 偏乐观, 中性, 偏悲观, 极度悲观]
  - field: fund_flow_trend
    type: enum [持续流入, 流入转流出, 中性, 流出转流入, 持续流出, 数据不可用]
    desc: "资金流数据不可用时必须明确降级"
  - field: market_position
    type: text
    desc: "基于截止日个股行情的位置判断"
  - field: margin_signal
    type: enum [看多, 中性, 看空, 数据不可用]
    desc: "融资融券信号"
  - field: contrarian_flag
    type: boolean
    desc: "是否触发逆向投资机会信号"
  - field: sector_divergence
    type: text
    desc: "无历史行业序列时标记数据不可用"
---

## 分析目标

以截止日之前的个股价格、成交和估值序列构建可复现的价格情绪代理，不使用当前资金流或大盘信息。

## 严格历史边界

- 禁止调用资金流、大盘和行业实时上下文。
- 只使用 `trade_date <= cutoff_date` 的行情和估值数据。
- 快照没有资金流、融资融券或行业历史序列时，对应字段必须输出“数据不可用”，不得用价格走势冒充资金流事实。

## 分析步骤

1. 计算或读取 20、60、120、250 交易日收益，评估短中长期动量。
2. 评估 52 周价格位置、历史回撤、波动率和成交量异常。
3. 结合 PE、PB 或股息率的自身历史位置识别估值与价格情绪是否共振。
4. 使用固定规则给出情绪等级：极端价格位置、显著回撤与动量反转需分别列证据。
5. 逆向信号必须同时满足低位置/高回撤、基本面未同步恶化等条件；数据不足时不触发。
