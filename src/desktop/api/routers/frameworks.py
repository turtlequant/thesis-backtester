"""
Framework orchestration endpoints — manage strategy frameworks (chapters + operators).
"""
import logging
import re
from pathlib import Path
from typing import Any, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.data.settings import STRATEGIES_ROOT, WORKSPACE_ROOT
from src.engine.config import StrategyConfig
from src.engine.framework_validation import (
    audit_framework_definition,
    audit_synthesis_definition,
    normalize_synthesis_fields,
)
from src.engine.operators import OperatorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/frameworks", tags=["frameworks"])

STRATEGIES_DIR = STRATEGIES_ROOT
def _model_dump(value: BaseModel) -> dict:
    return value.model_dump() if hasattr(value, "model_dump") else value.dict()


def _assert_operator_library(operators_dir: str) -> None:
    normalized = str(operators_dir or "").replace("\\", "/")
    if not re.fullmatch(r"operators/v\d+", normalized) or not (
        WORKSPACE_ROOT / normalized
    ).is_dir():
        raise HTTPException(status_code=422, detail=f"无效的算子库版本: {operators_dir}")


def _assert_synthesis_valid(
    synthesis: Optional[dict],
    synthesis_fields: List[Any],
    chapters: List[dict],
) -> None:
    issues = audit_synthesis_definition(synthesis or {}, synthesis_fields, chapters)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "综合研判配置校验失败",
                "issues": [item["reason"] for item in issues],
            },
        )


def _assert_framework_valid(
    chapters: List[Any], operators_dir: str, strategy_dir: Optional[Path] = None
) -> None:
    _assert_operator_library(operators_dir)
    normalized = [
        item
        if isinstance(item, dict)
        else (item.model_dump() if hasattr(item, "model_dump") else item.dict())
        for item in chapters
    ]
    registry = OperatorRegistry(strategy_dir=strategy_dir, operators_dir=operators_dir)
    issues = audit_framework_definition(normalized, registry)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={"message": "研究框架结构校验失败", "issues": issues},
        )


def _load_framework(name: str) -> dict:
    """Load full framework detail for a strategy."""
    strategy_dir = STRATEGIES_DIR / name
    yaml_path = strategy_dir / "strategy.yaml"

    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")

    try:
        config = StrategyConfig.from_yaml(yaml_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load strategy: {e}")

    chapter_defs = config.get_chapter_defs()
    operators_dir = config.get_operators_dir() or "operators/v2"

    # Load the exact operator library bound to this framework.
    registry = None
    try:
        registry = OperatorRegistry(operators_dir=operators_dir)
    except Exception as e:
        logger.warning(f"Failed to load operator library: {e}")

    chapters = []
    for ch in chapter_defs:
        ops = ch.get("operators", [])
        operator_refs = []
        effective_outputs = []
        seen_outputs = set()
        for op_id in ops:
            operator = registry.get(op_id) if registry is not None else None
            if operator is None:
                operator_refs.append({"id": op_id, "name": op_id, "missing": True})
                continue
            outputs = [
                {"field": item.field, "type": item.type, "desc": item.desc}
                for item in operator.outputs
            ]
            operator_refs.append(
                {
                    "id": operator.id,
                    "name": operator.name,
                    "data_needed": list(operator.data_needed),
                    "outputs": outputs,
                    "gate": operator.gate,
                    "history_variant": operator.history_variant,
                    "execution_mode": operator.execution_mode,
                    "missing": False,
                }
            )
            for item in outputs:
                if item["field"] in seen_outputs:
                    continue
                effective_outputs.append({**item, "source_operator": operator.id})
                seen_outputs.add(item["field"])
        chapters.append({
            "id": ch["id"],
            "chapter": ch.get("chapter", 0),
            "title": ch.get("title", ""),
            "operators": operator_refs,
            "dependencies": ch.get("dependencies", []),
            "effective_outputs": effective_outputs,
        })

    # Synthesis config
    synthesis = config.get_synthesis_config()
    decision_thresholds = synthesis.get("decision_thresholds", {})

    return {
        "name": name,
        "display_name": config.name,
        "version": config.version,
        "version_string": config.get_version_string(),
        "operators_dir": operators_dir,
        "analyst_role": config.get_analyst_role(),
        "chapters": chapters,
        "synthesis": {
            "thinking_steps": synthesis.get("thinking_steps", []),
            "scoring_rubric": synthesis.get("scoring_rubric", []),
            "decision_thresholds": decision_thresholds,
        },
        "synthesis_fields": normalize_synthesis_fields(config.get_synthesis_fields()),
    }


@router.get("")
async def list_frameworks():
    """List all frameworks (strategies) with chapter details."""
    if not STRATEGIES_DIR.exists():
        return []

    frameworks = []
    for strategy_dir in sorted(STRATEGIES_DIR.iterdir()):
        if not strategy_dir.is_dir():
            continue

        yaml_path = strategy_dir / "strategy.yaml"
        if not yaml_path.exists():
            continue

        try:
            config = StrategyConfig.from_yaml(yaml_path)
            chapter_defs = config.get_chapter_defs()

            # Count total operators
            total_ops = sum(len(ch.get("operators", [])) for ch in chapter_defs)

            synthesis = config.get_synthesis_config()
            thresholds = synthesis.get("decision_thresholds", {})

            frameworks.append({
                "name": strategy_dir.name,
                "display_name": config.name,
                "version": config.version,
                "chapter_count": len(chapter_defs),
                "operator_count": total_ops,
                "operators_dir": config.get_operators_dir() or "operators/v2",
                "buy_threshold": thresholds.get("buy", 70),
                "avoid_threshold": thresholds.get("avoid", 29),
            })
        except Exception as e:
            logger.warning(f"Failed to load framework {strategy_dir.name}: {e}")

    return frameworks


@router.get("/{name}")
async def get_framework(name: str):
    """Get full framework detail (chapters + operators + synthesis config)."""
    return _load_framework(name)


class ChapterDef(BaseModel):
    id: str
    chapter: int
    title: str
    operators: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)


class SynthesisFieldDef(BaseModel):
    field: str
    type: str = "str"
    desc: str = ""


class ThinkingStepDef(BaseModel):
    step: str
    instruction: str


class ScoringRubricDef(BaseModel):
    range: Optional[str] = None
    description: str
    dimension: Optional[str] = None
    source_chapter: Optional[str] = None
    weight: Optional[float] = None


class DecisionThresholdDef(BaseModel):
    buy: float = 70
    avoid: float = 29
    watch: Optional[List[float]] = None


class SynthesisConfig(BaseModel):
    thinking_steps: List[ThinkingStepDef] = Field(default_factory=list)
    scoring_rubric: List[ScoringRubricDef] = Field(default_factory=list)
    decision_thresholds: DecisionThresholdDef = Field(default_factory=DecisionThresholdDef)


class FrameworkCreate(BaseModel):
    name: str
    display_name: str
    version: str = "1.0"
    operators_dir: str = "operators/v2"
    analyst_role: str = "投资分析师"
    version_string: Optional[str] = None
    chapters: List[ChapterDef] = Field(default_factory=list)
    synthesis: Optional[SynthesisConfig] = None
    synthesis_fields: List[SynthesisFieldDef] = Field(default_factory=list)


class FrameworkUpdate(BaseModel):
    display_name: Optional[str] = None
    version: Optional[str] = None
    operators_dir: Optional[str] = None
    analyst_role: Optional[str] = None
    version_string: Optional[str] = None
    chapters: Optional[List[ChapterDef]] = None
    synthesis: Optional[SynthesisConfig] = None
    synthesis_fields: Optional[List[SynthesisFieldDef]] = None


def _build_strategy_yaml(data: dict) -> dict:
    """Build strategy.yaml raw dict from framework data."""
    raw = {
        "meta": {
            "name": data["display_name"],
            "version": data["version"],
        },
        "framework": {
            "operators_dir": data.get("operators_dir", "operators/v2"),
            "analyst_role": data.get("analyst_role", "投资分析师"),
        },
    }
    if data.get("version_string"):
        raw["framework"]["version_string"] = data["version_string"]

    # Add chapters inline
    chapters = []
    for ch in data.get("chapters", []):
        ch_def = {
            "id": ch["id"] if isinstance(ch, dict) else ch.id,
            "chapter": ch["chapter"] if isinstance(ch, dict) else ch.chapter,
            "title": ch["title"] if isinstance(ch, dict) else ch.title,
            "operators": ch["operators"] if isinstance(ch, dict) else ch.operators,
            "dependencies": ch["dependencies"] if isinstance(ch, dict) else ch.dependencies,
        }
        chapters.append(ch_def)

    raw["framework"]["chapters"] = chapters

    # Add synthesis
    synthesis = data.get("synthesis")
    if synthesis:
        s = synthesis if isinstance(synthesis, dict) else synthesis.dict()
        raw["framework"]["synthesis"] = s
    raw["framework"]["synthesis_fields"] = normalize_synthesis_fields(
        data.get("synthesis_fields", [])
    )

    return raw


@router.post("")
async def create_framework(data: FrameworkCreate):
    """Create a new framework (strategy directory + strategy.yaml)."""
    strategy_dir = STRATEGIES_DIR / data.name
    if strategy_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Strategy directory already exists: {data.name}",
        )

    _assert_operator_library(data.operators_dir)
    chapter_payload = [_model_dump(item) for item in data.chapters]
    if chapter_payload:
        _assert_framework_valid(chapter_payload, data.operators_dir)
    synthesis_payload = _model_dump(data.synthesis) if data.synthesis is not None else {}
    field_payload = [_model_dump(item) for item in data.synthesis_fields]
    _assert_synthesis_valid(synthesis_payload, field_payload, chapter_payload)

    strategy_dir.mkdir(parents=True, exist_ok=True)

    # Build and write strategy.yaml
    raw = _build_strategy_yaml(_model_dump(data))
    yaml_path = strategy_dir / "strategy.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return _load_framework(data.name)


@router.put("/{name}")
async def update_framework(name: str, update: FrameworkUpdate):
    """Update an existing framework."""
    strategy_dir = STRATEGIES_DIR / name
    yaml_path = strategy_dir / "strategy.yaml"

    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")

    # Load existing
    try:
        config = StrategyConfig.from_yaml(yaml_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load strategy: {e}")

    raw = config.raw

    # Ensure meta section exists
    if "meta" not in raw:
        raw["meta"] = {}
    if "framework" not in raw:
        raw["framework"] = {}

    # Apply updates
    if update.display_name is not None:
        raw["meta"]["name"] = update.display_name
    if update.version is not None:
        raw["meta"]["version"] = update.version
    if update.operators_dir is not None:
        raw["framework"]["operators_dir"] = update.operators_dir
    if update.analyst_role is not None:
        raw["framework"]["analyst_role"] = update.analyst_role
    if update.version_string is not None:
        if update.version_string.strip():
            raw["framework"]["version_string"] = update.version_string.strip()
        else:
            raw["framework"].pop("version_string", None)

    if update.chapters is not None:
        chapters = []
        for ch in update.chapters:
            chapters.append({
                "id": ch.id,
                "chapter": ch.chapter,
                "title": ch.title,
                "operators": ch.operators,
                "dependencies": ch.dependencies,
            })
        raw["framework"]["chapters"] = chapters

    if update.synthesis is not None:
        raw["framework"]["synthesis"] = _model_dump(update.synthesis)
    if update.synthesis_fields is not None:
        raw["framework"]["synthesis_fields"] = normalize_synthesis_fields(
            [_model_dump(item) for item in update.synthesis_fields]
        )

    prospective_chapters = (
        [item.model_dump() if hasattr(item, "model_dump") else item.dict() for item in update.chapters]
        if update.chapters is not None
        else config.get_chapter_defs()
    )
    prospective_operators_dir = raw["framework"].get("operators_dir") or "operators/v2"
    _assert_operator_library(prospective_operators_dir)
    if prospective_chapters:
        _assert_framework_valid(prospective_chapters, prospective_operators_dir, strategy_dir)
    prospective_synthesis = raw["framework"].get("synthesis") or {}
    prospective_fields = raw["framework"].get("synthesis_fields") or []
    _assert_synthesis_valid(prospective_synthesis, prospective_fields, prospective_chapters)

    # Validation succeeded; the inline definition can now replace a legacy chapters.yaml.
    if update.chapters is not None:
        chapters_yaml = strategy_dir / "chapters.yaml"
        if chapters_yaml.exists():
            chapters_yaml.unlink()

    # Write back
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return _load_framework(name)
