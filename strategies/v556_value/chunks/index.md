# Framework Chunks Index

- **ch01_data_verify** (Ch1): 数据核查与地缘政治排除 [186 lines, 4025 chars]
  - 依赖: 无
  - 焦点: 数据源分级、地缘政治排除、快速初筛（5分钟排除法）、负债扫描

- **ch02_soe_stream** (Ch2): 央国企筛选与流派识别 [131 lines, 1997 chars]
  - 依赖: ch01_data_verify
  - 焦点: 国企背景判定、四流派分类（纯硬收息/价值发现/烟蒂股/关联方资源）

- **ch03_debt_cycle** (Ch3): 深度负债与周期分析 [63 lines, 1388 chars]
  - 依赖: ch01_data_verify, ch02_soe_stream
  - 焦点: 有息vs经营性负债、无有息负债特殊识别、周期性行业负债特判、管理人诚信评估

- **ch04_cash_trend** (Ch4): 动态现金与周期拐点 [40 lines, 668 chars]
  - 依赖: ch01_data_verify, ch03_debt_cycle
  - 焦点: 5年现金余额趋势、行业周期拐点判断、非现金项目还原

- **ch05_stress_test** (Ch5): 极端情景测试 [22 lines, 366 chars]
  - 依赖: ch03_debt_cycle, ch04_cash_trend
  - 焦点: 连续三年营收下降10%压力测试、分红可持续性验证

- **ch06_valuation** (Ch6): 估值与安全边际 [600 lines, 12461 chars]
  - 依赖: ch03_debt_cycle, ch04_cash_trend, ch05_stress_test
  - 焦点: V2债券视角/V3业主视角/V3.5FCEV估值、剔除净现金FCF倍数、FCF计算规范化、动态安全边际

- **ch07_decision** (Ch7): 决策流程与持仓管理 [306 lines, 6551 chars]
  - 依赖: ch02_soe_stream, ch06_valuation
  - 焦点: 核心卫星仓位、动态退出纪律、试探建仓与网格加仓、持仓状态标签、组合韧性评估

- **ch08_cigar_butt** (Ch8): 高级烟蒂股分析框架 [39 lines, 634 chars]
  - 依赖: ch02_soe_stream, ch03_debt_cycle, ch06_valuation
  - 焦点: T级资产分层、REITs期限结构、债务偿还路径、静态价值型三要义

- **ch09_repair** (Ch9): 估值修复框架 [120 lines, 2011 chars]
  - 依赖: ch02_soe_stream, ch06_valuation
  - 焦点: 跨流派买卖逻辑统一、苹果买卖模型、一句话买入逻辑声明

- **ch10_light_asset** (Ch10): 特殊轻资产模式 [333 lines, 7813 chars]
  - 依赖: ch06_valuation
  - 焦点: 航空IT等特殊商业模式估值
