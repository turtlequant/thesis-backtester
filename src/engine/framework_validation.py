"""Structural validation shared by framework editing and execution preflight."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List


SUPPORTED_OUTPUT_TYPES = {"str", "float", "int", "bool", "list"}


def normalize_synthesis_field(value: Any) -> Dict[str, str]:
    """Normalize legacy string fields and structured fields to one contract."""
    if isinstance(value, dict):
        field_name = str(value.get("field") or "").strip()
        field_type = str(value.get("type") or "str").strip()
        description = str(value.get("desc") or value.get("description") or "").strip()
    else:
        raw = str(value or "").strip()
        field_name, separator, description = raw.partition(":")
        if not separator:
            field_name, separator, description = raw.partition("：")
        field_name = field_name.strip()
        description = description.strip() if separator else ""
        field_type = "str"
        if field_name in {"综合评分", "总体评分"}:
            field_type = "int"
        elif field_name in {"关键风险", "主要风险", "风险提示"}:
            field_type = "list"
    return {"field": field_name, "type": field_type, "desc": description}


def normalize_synthesis_fields(values: Iterable[Any]) -> List[Dict[str, str]]:
    fields = []
    seen = set()
    for value in values or []:
        item = normalize_synthesis_field(value)
        if not item["field"] or item["field"] in seen:
            continue
        fields.append(item)
        seen.add(item["field"])
    return fields


def audit_synthesis_definition(
    synthesis: Dict[str, Any],
    synthesis_fields: Iterable[Any],
    chapters: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return blocking issues for the final synthesis prompt/output contract."""
    issues: List[Dict[str, Any]] = []
    config = synthesis or {}
    chapter_ids = {str(item.get("id") or "") for item in chapters or []}

    def add(reason: str, item_id: str = "synthesis") -> None:
        issues.append(
            {
                "id": item_id,
                "name": "综合研判配置",
                "kind": "invalid_synthesis",
                "reason": reason,
                "remediation": "在研究框架页面修正后重新保存",
            }
        )

    thresholds = config.get("decision_thresholds") or {}
    if thresholds:
        buy = thresholds.get("buy")
        avoid = thresholds.get("avoid")
        if not all(isinstance(value, (int, float)) for value in (buy, avoid)) or not (
            0 <= avoid < buy <= 100
        ):
            add("决策边界必须满足 0 ≤ 回避阈值 < 买入阈值 ≤ 100", "decision_thresholds")

    for index, step in enumerate(config.get("thinking_steps") or [], 1):
        if not isinstance(step, dict) or not str(step.get("step") or "").strip() or not str(
            step.get("instruction") or ""
        ).strip():
            add(f"思考步骤 {index} 缺少步骤名称或指令", f"thinking_step_{index}")

    for index, rubric in enumerate(config.get("scoring_rubric") or [], 1):
        if not isinstance(rubric, dict) or not str(rubric.get("description") or "").strip():
            add(f"评分规则 {index} 缺少说明", f"scoring_rubric_{index}")
            continue
        has_range = bool(str(rubric.get("range") or "").strip())
        has_dimension = bool(str(rubric.get("dimension") or "").strip())
        if not has_range and not has_dimension:
            add(f"评分规则 {index} 必须定义分数区间或评分维度", f"scoring_rubric_{index}")
        source_chapter = str(rubric.get("source_chapter") or "").strip()
        if source_chapter and source_chapter not in chapter_ids:
            add(f"评分规则 {index} 引用了不存在的章节 {source_chapter}", f"scoring_rubric_{index}")
        weight = rubric.get("weight")
        if weight is not None and (not isinstance(weight, (int, float)) or weight <= 0):
            add(f"评分规则 {index} 的权重必须大于 0", f"scoring_rubric_{index}")

    raw_fields = list(synthesis_fields or [])
    normalized_fields = normalize_synthesis_fields(raw_fields)
    if len(normalized_fields) != len(raw_fields):
        add("综合输出字段不能为空或重名", "synthesis_fields")
    for field in normalized_fields:
        if field["type"] not in SUPPORTED_OUTPUT_TYPES:
            add(
                f"综合输出字段 {field['field']} 使用了不支持的类型 {field['type']}",
                field["field"],
            )
    return issues


def audit_framework_definition(
    chapters: Iterable[Dict[str, Any]], registry: Any
) -> List[Dict[str, Any]]:
    """Return blocking structural issues without mutating the framework."""
    chapters = list(chapters or [])
    issues: List[Dict[str, Any]] = []
    if not chapters:
        return [
            {
                "id": "framework",
                "name": "研究框架",
                "kind": "empty_framework",
                "reason": "框架没有任何章节",
                "remediation": "至少创建一个包含算子的章节",
            }
        ]

    chapter_ids = [str(item.get("id") or "").strip() for item in chapters]
    for chapter_id, count in Counter(chapter_ids).items():
        if not chapter_id:
            issues.append(
                {
                    "id": "chapter",
                    "name": "未命名章节",
                    "kind": "invalid_chapter",
                    "reason": "章节 ID 不能为空",
                    "remediation": "为每个章节设置唯一且稳定的 ID",
                }
            )
        elif count > 1:
            issues.append(
                {
                    "id": chapter_id,
                    "name": chapter_id,
                    "kind": "duplicate_chapter",
                    "reason": f"章节 ID 重复出现 {count} 次",
                    "remediation": "为重复章节设置不同的 ID",
                }
            )

    known_chapters = {item for item in chapter_ids if item}
    graph: Dict[str, List[str]] = {}
    seen_missing_operators = set()
    for chapter in chapters:
        chapter_id = str(chapter.get("id") or "").strip()
        dependencies = [str(item).strip() for item in chapter.get("dependencies", [])]
        graph.setdefault(chapter_id, dependencies)
        for dependency in dependencies:
            if dependency not in known_chapters:
                issues.append(
                    {
                        "id": dependency,
                        "name": dependency,
                        "kind": "missing_dependency",
                        "reason": f"章节 {chapter_id} 依赖不存在的章节 {dependency}",
                        "remediation": "修正依赖 ID，或补齐对应章节",
                    }
                )
            elif dependency == chapter_id:
                issues.append(
                    {
                        "id": chapter_id,
                        "name": chapter_id,
                        "kind": "self_dependency",
                        "reason": "章节不能依赖自身",
                        "remediation": "删除该自依赖关系",
                    }
                )

        operator_ids = [str(item).strip() for item in chapter.get("operators", [])]
        if not operator_ids:
            issues.append(
                {
                    "id": chapter_id,
                    "name": chapter.get("title") or chapter_id,
                    "kind": "empty_chapter",
                    "reason": "章节没有配置任何算子",
                    "remediation": "为章节添加至少一个算子，或删除空章节",
                }
            )
        for operator_id in operator_ids:
            if operator_id in seen_missing_operators or registry.get(operator_id) is not None:
                continue
            seen_missing_operators.add(operator_id)
            issues.append(
                {
                    "id": operator_id,
                    "name": operator_id,
                    "kind": "missing_operator",
                    "reason": f"章节 {chapter_id} 引用了不存在的算子",
                    "remediation": "从当前算子库选择有效 ID，或补齐对应算子定义",
                }
            )

    visiting = set()
    visited = set()
    cycle_nodes = set()

    def visit(chapter_id: str) -> None:
        if chapter_id in visited:
            return
        if chapter_id in visiting:
            cycle_nodes.add(chapter_id)
            return
        visiting.add(chapter_id)
        for dependency in graph.get(chapter_id, []):
            if dependency in known_chapters:
                visit(dependency)
                if dependency in cycle_nodes:
                    cycle_nodes.add(chapter_id)
        visiting.remove(chapter_id)
        visited.add(chapter_id)

    for chapter_id in known_chapters:
        visit(chapter_id)
    if cycle_nodes:
        nodes = "、".join(sorted(cycle_nodes))
        issues.append(
            {
                "id": "chapter_dag",
                "name": "章节 DAG",
                "kind": "dependency_cycle",
                "reason": f"章节依赖形成环路：{nodes}",
                "remediation": "调整依赖关系，确保章节 DAG 无环",
            }
        )

    return issues
