---
id: news_signal_history
name: 新闻与公告信号分析
category: forward_risk
tags: [risk, disclosure, history_adapter]
execution_mode: history_adapter
data_needed: [balancesheet, income, cashflow, fina_audit, pledge_stat, stk_holdertrade, repurchase]
outputs:
  - field: news_sentiment
    type: enum [重大利好, 偏正面, 中性, 偏负面, 重大利空]
  - field: key_events
    type: list
    desc: "截止日快照中可证实的披露事件"
  - field: risk_flags
    type: list
    desc: "由历史披露和财务异常识别的风险信号"
  - field: earnings_impact_pct
    type: number
    desc: "可量化事件的下一年盈利影响估计"
  - field: data_quality
    type: enum [新闻充足, 新闻有限, 无新闻数据-已降级]
    desc: "历史验证固定标记为无新闻数据-已降级"
---

## 分析目标

历史验证没有完整时点化新闻库时，不伪造新闻回放；改用截止日已进入快照的审计、财务、质押、股东交易和回购等披露信号完成风险降级分析。

## 严格历史边界

- 禁止调用新闻和其他实时市场上下文，禁止引用截止日之后的事件。
- `data_quality` 固定输出“无新闻数据-已降级”。
- `key_events` 只能包含快照中具有日期和数据证据的事项；没有事件时输出空列表。
- 不得依靠模型记忆补充公司公告、处罚、诉讼或业绩事件。

## 分析步骤

1. 检查审计意见、利润与经营现金流背离、资产减值、应收与存货异常。
2. 检查股权质押、重要股东增减持、回购与限售解禁等截止日可见记录。
3. 为每项信号记录证据日期、原始指标和可能影响；无法量化时不得编造盈利影响比例。
4. 根据证据强弱形成中性到负面的风险判断；缺少新闻本身不能被解释为利好。
