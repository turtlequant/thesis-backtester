"""
Framework orchestration endpoints — manage strategy frameworks (chapters + operators).
"""
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.settings import PROJECT_ROOT
from src.engine.config import StrategyConfig
from src.engine.operators import OperatorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/frameworks", tags=["frameworks"])

STRATEGIES_DIR = PROJECT_ROOT / "strategies"


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

    # Load operator names
    op_names = {}
    try:
        registry = OperatorRegistry(operators_dir=operators_dir)
        for op in registry.list_all():
            op_names[op.id] = op.name
    except Exception as e:
        logger.warning(f"Failed to load operator names: {e}")

    chapters = []
    for ch in chapter_defs:
        ops = ch.get("operators", [])
        chapters.append({
            "id": ch["id"],
            "chapter": ch.get("chapter", 0),
            "title": ch.get("title", ""),
            "operators": [
                {"id": op_id, "name": op_names.get(op_id, op_id)}
                for op_id in ops
            ],
            "dependencies": ch.get("dependencies", []),
        })

    # Synthesis config
    synthesis = config.get_synthesis_config()
    decision_thresholds = synthesis.get("decision_thresholds", {})

    return {
        "name": name,
        "display_name": config.name,
        "version": config.version,
        "operators_dir": operators_dir,
        "analyst_role": config.get_analyst_role(),
        "chapters": chapters,
        "synthesis": {
            "thinking_steps": synthesis.get("thinking_steps", []),
            "scoring_rubric": synthesis.get("scoring_rubric", []),
            "decision_thresholds": decision_thresholds,
        },
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
    operators: List[str] = []
    dependencies: List[str] = []


class SynthesisConfig(BaseModel):
    thinking_steps: List[dict] = []
    scoring_rubric: List[dict] = []
    decision_thresholds: dict = {}


class FrameworkCreate(BaseModel):
    name: str
    display_name: str
    version: str = "1.0"
    operators_dir: str = "operators/v2"
    analyst_role: str = "投资分析师"
    chapters: List[ChapterDef] = []
    synthesis: Optional[SynthesisConfig] = None


class FrameworkUpdate(BaseModel):
    display_name: Optional[str] = None
    version: Optional[str] = None
    operators_dir: Optional[str] = None
    analyst_role: Optional[str] = None
    chapters: Optional[List[ChapterDef]] = None
    synthesis: Optional[SynthesisConfig] = None


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

    strategy_dir.mkdir(parents=True, exist_ok=True)

    # Build and write strategy.yaml
    raw = _build_strategy_yaml(data.dict())
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

        # Also remove chapters.yaml if it exists, since we're now inline
        chapters_yaml = strategy_dir / "chapters.yaml"
        if chapters_yaml.exists():
            chapters_yaml.unlink()

    if update.synthesis is not None:
        raw["framework"]["synthesis"] = update.synthesis.dict()

    # Write back
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return _load_framework(name)
