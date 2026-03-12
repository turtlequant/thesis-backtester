# V5.5.6 价值投资龟级评定

基于 [investTemplate](https://github.com/sunheyi6/investTemplate) V5.5.6 框架的策略实例。

## 投资模版

本策略的分析框架源自 **个股分析标准模版 V5.5.6**，一套面向 A 股/港股的深度价值分析体系。

- 原始仓库：https://github.com/sunheyi6/investTemplate
- 许可证：Apache 2.0

模版已解析为 10 个章节文件（`chunks/`），由 `parse-template` 命令生成。

## 框架概要

**四流派投资体系**：纯硬收息 / 价值发现 / 烟蒂股 / 关联方资源

**10 章分析流程**：

| 章节 | 内容 | 核心关注 |
|------|------|---------|
| 1 | 数据核查与地缘政治排除 | 5 分钟快速初筛 |
| 2 | 央国企筛选与流派识别 | 四流派分类 |
| 3 | 深度负债与周期分析 | 有息 vs 经营性负债、管理人诚信 |
| 4 | 动态现金与周期拐点 | 5 年现金趋势、非现金项目还原 |
| 5 | 极端情景测试 | 连续三年营收 -10% 压力测试 |
| 6 | 估值与安全边际 | EV/FCF、剔除净现金 FCF 倍数 |
| 7 | 决策流程与持仓管理 | 苹果买卖模型、网格加仓 |
| 8 | 高级烟蒂股分析 | T 级资产分层、REITs 期限结构 |
| 9 | 估值修复框架 | 跨流派买卖逻辑、一句话买入逻辑 |
| 10 | 特殊轻资产模式 | 航空 IT 等特殊商业模式 |

## 龟级筛选

| 级别 | PE | PB | 股息率 |
|------|-----|------|--------|
| 金龟 | ≤ 8 | ≤ 0.8 | ≥ 7% |
| 银龟 | ≤ 10 | ≤ 1.0 | ≥ 5% |
| 铜龟 | ≤ 12 | ≤ 1.2 | ≥ 4% |

## 盲测验证

- **样本**：60 只股票，12 个半年截面（2019-06 ~ 2024-12）
- **报告**：120 份盲测分析（`backtest/reports/`）
- **核心结论**：AI 过滤增益 **+16.6 个百分点**

详见 [validation_report.md](backtest/validation_report.md)。

## 用法

```bash
# 筛选
python -m src.engine.launcher strategies/v556_value/strategy.yaml screen 2024-06-30

# 单股分析
python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30

# 盲测
python -m src.engine.launcher strategies/v556_value/strategy.yaml analyze 601288.SH 2024-06-30 --blind
```
