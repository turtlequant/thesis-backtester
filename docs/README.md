# Thesis Backtester 文档索引

本文档目录同时保存当前实现说明和早期研究记录。阅读时以代码、测试和下列“当前文档”为准；历史记录用于理解项目如何演化，不代表现行产品承诺或开发计划。

## 当前产品文档

| 文档 | 内容 | 适合读者 |
|---|---|---|
| [产品功能指引](PRODUCT_GUIDE.md) | 三个工作区、实际使用流程、助手边界 | 所有用户 |
| [整体架构](design/architecture.md) | 运行时分层、数据流、研究流和安全边界 | 开发者、贡献者 |
| [数据层](design/data_layer.md) | Provider 边界、SQLite、下载、增量和时间边界 | 数据开发者 |
| [因子库](design/factor_library.md) | 原生字段、派生因子 DSL、物化状态 | 因子研究者 |
| [算子与编排](design/operators.md) | 定量因子、定性算子、章节组合和扩展方式 | 框架设计者 |
| [筛选层](design/screener.md) | 数值过滤、排序、因子合并与输出 | 策略研究者 |
| [回测层](design/backtest.md) | 三步历史实验、前瞻收益和多基准评估 | 策略研究者 |
| [Agent 执行](design/agent.md) | 固定 DAG、Prompt 组装、工具沙盒和结构化输出 | LLM 开发者 |
| [评分设计](design/scoring.md) | 章节结论、综合研判和校准逻辑 | 框架设计者 |
| [结构化投研](design/live_analysis.md) | 个股分析、最新研判与严格历史验证的边界 | 产品与 LLM 开发者 |
| [Windows 打包与发布](PACKAGING.md) | Nuitka 构建、资源清单、自检和发布检查 | 维护者、发布者 |

算子目录自身的说明见 [`workspace/operators/v2/README.md`](../workspace/operators/v2/README.md)。

## 历史研究记录

以下文件记录了早期实验、产品假设或阶段性路线，不作为当前状态清单：

- [投资思路回测引擎：早期产品设计](investment_thesis_backtester.md)
- [投资框架自动进化机制](framework_evolution.md)
- [数据维度扩展路线图](data_dimensions_roadmap.md)
- [规模扩展与框架优化计划](scaling_plan.md)
- [从回测到生产：三层实时分析架构](design/production_roadmap.md)

这些记录中的文件路径、算子数量、数据格式和时间计划可能已经过时。实施前应回到当前架构文档和代码验证。

## 文档维护规则

1. 产品名称统一使用 **Thesis Backtester**，中文定位为“结构化投研引擎”。
2. 安装、启动和测试命令统一使用 `uv` 与项目独立 `.venv`。
3. 数据存储统一描述为按 Provider 物理隔离的 SQLite，不再沿用旧 Parquet 基线。
4. 截面筛选是独立的纯数值能力；结构化投研只能单向引用筛选策略或候选池。
5. LLM 是既定管线中的辅助能力，不能被描述为自由生成或动态改变正式研究流程。
6. 历史验证必须遵守时点边界；当前算子只有在存在输出契约一致的历史实现时才能替换运行。
7. 路线图、实验结论和当前能力必须明确区分，避免把研究设想写成已经完成的产品功能。
