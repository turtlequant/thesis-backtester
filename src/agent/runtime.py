"""
Agent 运行时 — 核心编排器

职责：
  1. 构建 system prompt（投资理念 + 时间边界 + 盲测规则）
  2. 按章节 DAG 拓扑顺序驱动 LLM 分析
  3. 管理 tool_use 循环（LLM 调用 tool → sandbox 执行 → 结果回传）
  4. 收集每章结构化输出 → 汇总综合研判

用法:
    python -m src.agent.runtime strategies/v6_value/strategy.yaml 601288.SH 2024-06-30
"""
import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.data.snapshot import create_snapshot, StockSnapshot, snapshot_to_markdown
from src.engine.config import StrategyConfig

from .client import LLMClient, LLMConfig
from .tools import ToolSandbox, TOOL_DEFINITIONS
from .schemas import schema_to_prompt_description, dataclass_to_json_schema

logger = logging.getLogger(__name__)

# 最大 tool_use 循环次数（防止无限循环）
MAX_TOOL_ROUNDS = 15


# ==================== DAG 调度 ====================

def build_dag(chapter_defs: List[dict]) -> Dict[str, List[str]]:
    """构建章节依赖图"""
    return {ch["id"]: ch.get("dependencies", []) for ch in chapter_defs}


def topological_batches(dag: Dict[str, List[str]]) -> List[List[str]]:
    """
    拓扑排序，返回可并行执行的批次列表

    Returns:
        [[ch01, ch02], [ch03, ch04], [ch05], ...] — 同批内可并行
    """
    in_degree = {node: 0 for node in dag}
    for node, deps in dag.items():
        for dep in deps:
            if dep in in_degree:
                pass  # dep is counted as source
        in_degree[node] = len([d for d in deps if d in dag])

    # Kahn's algorithm with batching
    batches = []
    remaining = dict(in_degree)

    while remaining:
        # 找出所有入度为 0 的节点
        ready = [n for n, d in remaining.items() if d == 0]
        if not ready:
            # 有环，强制取剩余
            logger.warning(f"DAG cycle detected, forcing: {list(remaining.keys())}")
            ready = list(remaining.keys())

        batches.append(sorted(ready))  # 排序保证确定性

        # 移除已处理的节点，更新入度
        for node in ready:
            del remaining[node]
        for node in remaining:
            remaining[node] = len([d for d in dag[node] if d in remaining])

    return batches


# ==================== System Prompt 构建 ====================

def build_system_prompt(
    chapter: dict,
    snapshot: StockSnapshot,
    config: StrategyConfig,
    blind_mode: bool = True,
    snapshot_md: str = "",
    output_schema_text: str = "",
) -> str:
    """构建单章分析的 system prompt（算子驱动）"""
    version_string = config.get_version_string()
    analyst_role = config.get_analyst_role()

    blind_rules = ""
    if blind_mode:
        blind_rules = """
## 盲测规则
- 公司名称和股票代码已被隐藏，你不知道分析的是哪家公司
- 禁止猜测公司身份
- 仅基于提供的数据和工具返回的数据进行分析
- 不得使用训练数据中对任何特定公司的既有认知
"""

    # 行业提示（帮助 LLM 正确理解行业特征）
    industry_hint = ""
    if snapshot.industry:
        industry_hint = f"\n## 行业信息: {snapshot.industry}\n"
        # 金融行业特殊提示
        if snapshot.industry in ('银行', '保险', '证券', '多元金融'):
            industry_hint += (
                "**重要**: 该公司属于金融行业，财务报表结构与一般企业不同：\n"
                "- 负债率 80-95% 属于行业正常水平（存款/保费=负债），不是风险信号\n"
                "- 经营现金流/净利润 比率不适用于金融企业\n"
                "- 应使用 ROE、净息差、不良率、拨备覆盖率等行业指标\n"
                "- 资本充足率是核心安全指标，而非传统的流动比率/速动比率\n"
            )

    # 输出 schema 提示
    schema_section = ""
    if output_schema_text:
        schema_section = f"""
## 结构化输出 Schema
请严格按照以下字段输出 JSON 结论：
{output_schema_text}
"""

    # 分析框架内容（算子驱动）
    framework_content = _build_framework_content(chapter, config)

    return f"""你是一位{analyst_role}，正在使用「{version_string}」框架进行深度分析。

## 严格时间边界: {snapshot.cutoff_date}
- 你正在分析 {snapshot.cutoff_date} 时间点下的投资价值
- 禁止使用任何该日期之后的信息
- 通过工具获取的数据是完整的——未出现的信息代表在该时间点不可获取
{blind_rules}{industry_hint}
## 当前任务: 第{chapter['chapter']}章 — {chapter['title']}

## 分析框架

请严格按照以下分析算子进行分析：

{framework_content}

## 已有数据快照（核心数据已预加载，无需重复通过工具获取）

{snapshot_md}

## 工作方式
1. 上方已包含核心数据快照，请优先使用
2. 仅在需要更多期数或快照中未包含的数据时，才调用 query_financial_data 工具
3. 按上方分析算子逐项完成分析，引用具体数据支撑每个判断
4. 在分析结束时，输出结构化 JSON 结论（用 ```json 包裹）

## 输出要求
- **直接输出分析结论和推理过程，不要描述数据获取过程**（禁止出现"我先调用XX工具获取数据""让我查看XX数据"等叙述性描述）
- 引用具体数据支撑每个判断，但只呈现分析结论，不叙述查找过程
- 金额单位统一为"亿元"
- 百分比用数值表示（如 7.06 表示 7.06%）
- 保持简洁：每个算子的分析控制在 3-5 个要点，避免冗余复述
- 最后用 ```json ``` 包裹输出结构化结论
{schema_section}"""


def _build_framework_content(
    chapter: dict,
    config: StrategyConfig,
) -> str:
    """从章节定义中的算子组合构建分析框架内容"""
    operators = chapter.get('operators', [])
    if not operators:
        return "（无分析框架内容）"

    registry = config.get_operator_registry()
    ops = registry.resolve(operators)
    if not ops:
        return "（无分析框架内容）"

    parts = []
    for i, op in enumerate(ops, 1):
        parts.append(f"### 算子 {i}: {op.name}\n\n{op.content}")
    return "\n\n---\n\n".join(parts)


def build_synthesis_prompt(
    config: StrategyConfig,
    snapshot: StockSnapshot,
    chapter_outputs: Dict[str, Any],
    blind_mode: bool = True,
    chapter_texts: Optional[Dict[str, str]] = None,
) -> str:
    """构建综合研判的 system prompt（含结构化思考步骤和评分锚点）"""
    analyst_role = config.get_analyst_role()
    version_string = config.get_version_string()
    synthesis_fields = config.get_synthesis_fields()
    thinking_steps = config.get_thinking_steps()
    scoring_rubric = config.get_scoring_rubric()
    decision_thresholds = config.get_decision_thresholds()

    # 格式化前置章节输出（完整分析文本 + 结构化结论）
    prior_text = ""
    chapter_defs = config.get_chapter_defs()
    for ch_def in chapter_defs:
        ch_id = ch_def["id"]
        prior_text += f"\n### 第{ch_def['chapter']}章: {ch_def['title']}\n"

        # 优先使用完整分析文本（含推理过程和数据引用）
        if chapter_texts and ch_id in chapter_texts:
            prior_text += f"\n{chapter_texts[ch_id]}\n"
        elif ch_id in chapter_outputs:
            # 回退：仅有结构化输出
            output = chapter_outputs[ch_id]
            if isinstance(output, dict):
                for k, v in output.items():
                    if v and str(v) not in ("", "0", "0.0", "False", "[]"):
                        prior_text += f"- **{k}**: {v}\n"
            else:
                prior_text += str(output) + "\n"

    fields_text = "\n".join(f"{i+1}. **{f}**" for i, f in enumerate(synthesis_fields))

    blind_rules = ""
    if blind_mode:
        blind_rules = "\n注意：这是盲测分析，你不知道公司身份。\n"

    # 构建思考步骤
    thinking_text = ""
    if thinking_steps:
        thinking_text = "\n## 思考步骤\n\n请严格按以下步骤进行综合研判：\n"
        for i, step in enumerate(thinking_steps, 1):
            thinking_text += f"\n### 步骤 {i}: {step['step']}\n\n{step['instruction']}\n"

    # 构建评分锚点
    rubric_text = ""
    if scoring_rubric:
        rubric_text = "\n## 评分锚点（校准参考，不是公式）\n\n"
        for item in scoring_rubric:
            rubric_text += f"- **{item['range']}分**: {item['description']}\n"

    # 构建决策边界
    threshold_text = ""
    if decision_thresholds:
        buy = decision_thresholds.get('buy', 70)
        avoid = decision_thresholds.get('avoid', 29)
        threshold_text = f"""
## 决策边界

- ≥{buy}分 → 买入
- {avoid + 1}-{buy - 1}分 → 观望
- ≤{avoid}分 → 回避

评分与最终建议必须一致，不能出现"评分 75 但建议观望"的矛盾。
"""

    return f"""你是一位{analyst_role}，已完成「{version_string}」框架的全部章节分析。
现在请基于所有章节的结论，进行综合研判。

## 严格时间边界: {snapshot.cutoff_date}
{blind_rules}
## 各章分析结论
{prior_text}
{thinking_text}{rubric_text}{threshold_text}
## 输出要求

完成上述思考步骤后，输出包含以下字段的综合研判（用 ```json 包裹）：

{fields_text}

注意：
- 一句话买入逻辑必须是可证伪的投资命题
- 最终建议只能是：买入 / 观望 / 回避
- 先完成思考步骤的分析，再给出最终 JSON"""


# ==================== Agent Loop ====================

async def run_agent_loop(
    client: LLMClient,
    system_prompt: str,
    sandbox: ToolSandbox,
    prior_context: Optional[str] = None,
) -> Tuple[str, Optional[Dict]]:
    """
    执行单次 agent loop（一个章节的分析）

    Args:
        client: LLM 客户端
        system_prompt: system prompt
        sandbox: tool 沙箱
        prior_context: 前置章节输出（注入 user message）

    Returns:
        (full_text, structured_output) — 完整分析文本和解析出的 JSON
    """
    messages = [{"role": "system", "content": system_prompt}]

    user_msg = "请开始分析。先调用工具获取需要的数据，然后进行详细分析。"
    if prior_context:
        user_msg = f"以下是前置章节的分析结论：\n\n{prior_context}\n\n请基于这些结论和工具数据，开始本章分析。"
    messages.append({"role": "user", "content": user_msg})

    full_text_parts = []
    tools = TOOL_DEFINITIONS

    for round_num in range(MAX_TOOL_ROUNDS):
        response = await client.chat(messages, tools=tools)
        choice = response.choices[0]
        message = choice.message

        # 收集文本内容
        if message.content:
            full_text_parts.append(message.content)

        # 检查是否结束 (不同 API 返回的 finish_reason 不同)
        terminal_reasons = {"stop", "end_turn", "end", None}
        if choice.finish_reason in terminal_reasons or not message.tool_calls:
            if choice.finish_reason == "length":
                logger.warning("LLM 输出达到 max_tokens 限制，回复可能被截断")
            break

        # 处理 tool calls
        # 先把 assistant message（含 tool_calls）追加到 messages
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            fn = tool_call.function
            try:
                args = json.loads(fn.arguments) if fn.arguments else {}
            except json.JSONDecodeError:
                args = {}

            logger.debug(f"Tool call: {fn.name}({args})")
            result = sandbox.execute(fn.name, args)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    full_text = "\n".join(full_text_parts)

    # 从文本中提取 JSON 结构化输出
    structured = _extract_json_from_text(full_text)

    return full_text, structured


def _extract_json_from_text(text: str) -> Optional[Dict]:
    """从 LLM 输出文本中提取 ```json ``` 包裹的 JSON"""
    # 找最后一个 json 代码块（通常是最终结论）
    pattern = r"```json\s*\n?(.*?)\n?\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if not matches:
        return None

    # 取最后一个 JSON 块
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON output: {e}")
        return None


# ==================== Output Schema 加载 ====================

def _load_output_schemas(config: StrategyConfig) -> Dict[str, str]:
    """
    加载每章的 output schema 描述

    优先级:
      1. output_schema.py 中的 dataclass 定义（精确控制）
      2. 算子 frontmatter 中的 outputs 字段（自动聚合）

    Returns:
        {ch_id: schema_description_text}
    """
    result = {}

    # 尝试从 output_schema.py 加载
    try:
        schema_map = config.get_schema_map()
        for ch_id, cls in schema_map.items():
            result[ch_id] = schema_to_prompt_description(cls)
    except Exception as e:
        logger.debug(f"No output_schema.py or load failed: {e}")

    # 对于没有 schema 的章节，从算子 outputs 自动生成
    chapter_defs = config.get_chapter_defs()
    registry = None
    for ch_def in chapter_defs:
        ch_id = ch_def["id"]
        if ch_id in result:
            continue  # output_schema.py 已有定义，跳过
        operators = ch_def.get("operators", [])
        if not operators:
            continue
        if registry is None:
            registry = config.get_operator_registry()
        auto_schema = registry.compose_schema_text(operators)
        if auto_schema:
            result[ch_id] = auto_schema

    return result


# ==================== 主入口 ====================

async def run_blind_analysis(
    ts_code: str,
    cutoff_date: str,
    config: StrategyConfig,
    blind_mode: bool = True,
    output_dir: Optional[Path] = None,
    on_progress: Optional[callable] = None,
    snapshot: Optional["StockSnapshot"] = None,
) -> Dict[str, Any]:
    """
    执行完整的 Agent 盲测分析

    Args:
        ts_code: 股票代码
        cutoff_date: 截止日期
        config: 策略配置
        blind_mode: 盲测模式
        output_dir: 输出目录（可选）
        on_progress: 进度回调（可选），签名: (event, ch_id, data) -> None
            event: "snapshot_done" | "chapter_start" | "chapter_done" | "synthesis_start" | "synthesis_done"
        snapshot: 外部创建的 Snapshot（可选，live-analyze 传入，跳过内部创建）

    Returns:
        {
            "chapter_outputs": {ch_id: {structured_output}},
            "chapter_texts": {ch_id: "full analysis text"},
            "synthesis": {综合研判},
            "metadata": {运行元数据},
        }
    """
    start_time = time.time()

    def _progress(event, ch_id=None, data=None):
        if on_progress:
            try:
                on_progress(event, ch_id, data)
            except Exception:
                pass  # 回调异常不影响主流程

    # 1. 创建数据快照（或使用外部传入的）
    if snapshot is None:
        logger.info(f"Creating snapshot: {ts_code} @ {cutoff_date}")
        snapshot = create_snapshot(ts_code, cutoff_date)
    else:
        logger.info(f"Using provided snapshot: {ts_code} @ {cutoff_date}")
    _progress("snapshot_done", data={"data_sources": snapshot.data_sources})

    # 2. 创建沙箱和客户端
    sandbox = ToolSandbox(snapshot, blind_mode=blind_mode)
    client = LLMClient.from_strategy(config)

    # 3. 加载章节定义
    chapter_defs = config.get_chapter_defs()
    chapter_def_map = {ch["id"]: ch for ch in chapter_defs}

    if not chapter_defs:
        raise RuntimeError("策略缺少章节定义 (chapters.yaml)")

    # 4. 预生成 snapshot markdown（注入 prompt，减少 tool 调用）
    snap_md = snapshot_to_markdown(snapshot, blind_mode=blind_mode)
    logger.info(f"Snapshot markdown: {len(snap_md)} chars")

    # 5. 加载 output schema（如有）
    output_schema_map = _load_output_schemas(config)

    # 6. DAG 调度
    dag = build_dag(chapter_defs)
    batches = topological_batches(dag)

    chapter_outputs: Dict[str, Any] = {}
    chapter_texts: Dict[str, str] = {}

    logger.info(f"DAG batches: {[[ch for ch in b] for b in batches]}")

    for batch_idx, batch in enumerate(batches):
        logger.info(f"Batch {batch_idx + 1}/{len(batches)}: {batch}")

        # 同一批内并行执行
        tasks = []
        for ch_id in batch:
            if ch_id not in chapter_def_map:
                logger.warning(f"Skipping unknown chapter: {ch_id}")
                continue

            ch_def = chapter_def_map[ch_id]

            if not ch_def.get('operators'):
                logger.warning(f"Skipping {ch_id}: no operators defined")
                continue

            # 获取本章 output schema 描述
            schema_text = output_schema_map.get(ch_id, "")

            # 构建 system prompt（含 snapshot + schema）
            system_prompt = build_system_prompt(
                ch_def, snapshot, config, blind_mode,
                snapshot_md=snap_md,
                output_schema_text=schema_text,
            )

            # 构建前置上下文（P1: 传递完整 JSON）
            prior_context = None
            deps = ch_def.get("dependencies", [])
            if deps:
                prior_parts = []
                for dep_id in deps:
                    if dep_id in chapter_outputs and chapter_outputs[dep_id]:
                        dep_def = chapter_def_map.get(dep_id, {})
                        dep_title = dep_def.get("title", dep_id)
                        prior_parts.append(f"### 第{dep_def.get('chapter', '?')}章: {dep_title}")
                        output = chapter_outputs[dep_id]
                        prior_parts.append(f"```json\n{json.dumps(output, ensure_ascii=False, indent=2)}\n```")
                        prior_parts.append("")
                prior_context = "\n".join(prior_parts)

            tasks.append((ch_id, system_prompt, prior_context))

        # 并行执行同一批的章节
        async def _run_chapter(ch_id, sys_prompt, prior_ctx):
            ch_def = chapter_def_map.get(ch_id, {})
            _progress("chapter_start", ch_id, {"title": ch_def.get("title", ch_id)})
            logger.info(f"  Running chapter: {ch_id}")
            text, structured = await run_agent_loop(
                client, sys_prompt, sandbox, prior_ctx
            )
            return ch_id, text, structured

        results = await asyncio.gather(
            *[_run_chapter(cid, sp, pc) for cid, sp, pc in tasks]
        )

        for ch_id, text, structured in results:
            chapter_texts[ch_id] = text
            chapter_outputs[ch_id] = structured or {}
            _progress("chapter_done", ch_id, structured or {})
            logger.info(f"  Completed: {ch_id} ({'structured' if structured else 'text only'})")

    # 5. 综合研判（传入完整分析文本，让 synthesis 看到推理过程和数据引用）
    _progress("synthesis_start")
    logger.info("Running synthesis...")
    synthesis_prompt = build_synthesis_prompt(
        config, snapshot, chapter_outputs, blind_mode,
        chapter_texts=chapter_texts,
    )
    synthesis_text, synthesis_output = await run_agent_loop(
        client, synthesis_prompt, sandbox
    )
    chapter_texts["synthesis"] = synthesis_text
    _progress("synthesis_done", data=synthesis_output or {})

    # 6. 保存结果
    elapsed = time.time() - start_time
    result = {
        "chapter_outputs": chapter_outputs,
        "chapter_texts": chapter_texts,
        "synthesis": synthesis_output or {},
        "metadata": {
            "ts_code": ts_code,
            "cutoff_date": cutoff_date,
            "blind_mode": blind_mode,
            "model": client.config.model,
            "elapsed_seconds": round(elapsed, 1),
            "chapters_completed": len(chapter_outputs),
        },
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        _save_results(result, output_dir, ts_code, cutoff_date)

    await client.close()

    logger.info(
        f"Analysis complete: {len(chapter_outputs)} chapters, "
        f"synthesis={'yes' if synthesis_output else 'no'}, "
        f"{elapsed:.1f}s"
    )

    return result


def _save_results(
    result: Dict[str, Any],
    output_dir: Path,
    ts_code: str,
    cutoff_date: str,
):
    """保存分析结果到文件"""
    prefix = f"{ts_code}_{cutoff_date}"

    # 保存完整分析文本
    full_text = []
    for ch_id, text in result["chapter_texts"].items():
        full_text.append(f"\n{'='*60}")
        full_text.append(f"# {ch_id}")
        full_text.append(f"{'='*60}\n")
        full_text.append(text)

    report_path = output_dir / f"{prefix}_report.md"
    report_path.write_text("\n".join(full_text), encoding="utf-8")

    # 保存结构化输出
    structured_path = output_dir / f"{prefix}_structured.json"
    structured = {
        "chapter_outputs": result["chapter_outputs"],
        "synthesis": result["synthesis"],
        "metadata": result["metadata"],
    }
    structured_path.write_text(
        json.dumps(structured, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(f"Saved: {report_path}, {structured_path}")


# ==================== CLI ====================

def main():
    """命令行入口"""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if len(sys.argv) < 4:
        print("用法: python -m src.agent.runtime <strategy.yaml> <ts_code> <cutoff_date> [--no-blind]")
        print("示例: python -m src.agent.runtime strategies/v6_value/strategy.yaml 601288.SH 2024-06-30")
        sys.exit(1)

    yaml_path = sys.argv[1]
    ts_code = sys.argv[2]
    cutoff_date = sys.argv[3]
    blind_mode = "--no-blind" not in sys.argv

    config = StrategyConfig.from_yaml(yaml_path)
    print(f"策略: {config.name} (v{config.version})")
    print(f"标的: {ts_code} @ {cutoff_date}")
    print(f"盲测: {'是' if blind_mode else '否'}")
    print()

    output_dir = config.get_backtest_dir() / "agent_reports"

    result = asyncio.run(
        run_blind_analysis(ts_code, cutoff_date, config, blind_mode, output_dir)
    )

    # 打印摘要
    meta = result["metadata"]
    print(f"\n{'='*60}")
    print(f"分析完成: {meta['chapters_completed']} 章, {meta['elapsed_seconds']}秒")
    print(f"模型: {meta['model']}")

    synthesis = result.get("synthesis", {})
    if synthesis:
        print(f"\n综合研判:")
        for k, v in synthesis.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
