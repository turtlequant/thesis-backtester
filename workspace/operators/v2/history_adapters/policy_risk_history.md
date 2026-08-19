---
id: policy_risk_history
name: 政策转向风险评估
category: forward_risk
tags: [risk, forward_looking, history_adapter]
execution_mode: history_adapter
data_needed: [income, fina_mainbz, balancesheet, fina_indicator, top10_holders]
outputs:
  - field: policy_exposure
    type: enum [高, 中, 低]
    desc: "业务对政策的依赖程度"
  - field: policy_direction
    type: enum [利好, 中性, 利空, 不确定]
    desc: "截止日证据可支持的政策方向"
  - field: strategic_alignment
    type: enum [核心战略, 支撑配套, 中性, 潜在打击对象]
    desc: "与可见业务结构对应的政策敏感性"
  - field: subsidy_dependency_pct
    type: float
    desc: "政府补助占净利润比例(%)"
  - field: gov_revenue_pct
    type: float
    desc: "政府相关收入占总收入比例(%)"
  - field: worst_case_earnings_impact_pct
    type: float
    desc: "结构性政策冲击下预估盈利影响(%)"
  - field: policy_resilience
    type: enum [强, 中, 弱]
    desc: "政策冲击抵御能力"
  - field: key_policies
    type: list
    desc: "仅由截止日可见证据支持的政策暴露类别"
---

## 分析目标

不预测具体政策新闻，而是用截止日已披露的业务与财务结构衡量公司对政策变化的暴露和承受能力。

## 严格历史边界

- 禁止调用新闻或市场上下文，禁止引用截止日之后发生或发布的政策。
- 只使用业务构成、客户集中度、政府补助、资产负债结构、盈利波动与股东性质等快照证据。
- 没有时点化政策材料时，`policy_direction` 必须输出“不确定”；不得依靠模型记忆补写当年政策事件。

## 分析步骤

1. 识别特许经营、价格管制、财政补贴、政府采购、环保约束、地产链和金融监管等结构性暴露。
2. 量化可得的补助依赖、政府相关收入、业务集中度；缺少字段时明确标记不可计算。
3. 设计政策冲击情景，估算收入、利润或资产减值的敏感度，说明假设而非伪装成事实。
4. 根据现金流、负债、业务分散度和股东支持能力评估韧性。
5. 输出暴露程度、韧性和关键证据；“政策方向”在无历史材料时保持不确定。
