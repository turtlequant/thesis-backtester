---
id: industry_position_history
name: 行业地位与竞争格局分析
category: forward_risk
tags: [fundamental, forward_looking, history_adapter]
execution_mode: history_adapter
data_needed: [income, fina_indicator, fina_mainbz, balancesheet]
outputs:
  - field: market_position
    type: enum [龙头, 第二梯队, 一般, 边缘化]
  - field: competitive_moat
    type: enum [强, 中, 弱, 无]
  - field: moat_type
    type: text
    desc: "护城河类型"
  - field: moat_durability
    type: enum [加固中, 稳定, 侵蚀中, 不适用]
    desc: "护城河趋势方向"
  - field: share_trend
    type: enum [抢占份额, 稳定, 流失份额]
    desc: "由历史经营代理指标支持的份额趋势"
  - field: industry_trend
    type: enum [增长, 成熟, 衰退, 周期性]
  - field: pricing_power
    type: enum [强, 中, 弱]
    desc: "定价能力"
  - field: five_forces_summary
    type: text
    desc: "基于截止日证据的竞争格局结论"
---

## 分析目标

使用截止日已披露的经营结果和业务构成，对竞争地位、定价能力与护城河趋势形成保守、可复核的历史判断。

## 严格历史边界

- 禁止查询当前行业概况、当前新闻、当前市场份额或截止日之后的竞争事件。
- 只使用快照内的分业务收入、毛利率、收入增长、ROE、资产周转、现金转换和资本开支趋势。
- 没有横截面同行数据时，不得仅凭公司规模断言“行业龙头”；必须降低结论强度并披露证据不足。

## 分析步骤

1. 识别主要业务及收入、利润集中度，判断业务结构是否稳定。
2. 用毛利率、费用率、周转率和现金回收趋势评估定价权与议价能力。
3. 用连续多期增长质量、资本回报和投入强度判断护城河是在加固还是侵蚀。
4. 仅在快照提供可比较证据时判断份额趋势；否则输出保守等级并说明不可观测。
5. 按波特五力给出结构性结论，每项必须对应截止日可见数据或明确的数据缺口。
