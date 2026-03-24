"""
Strategy management endpoints.
"""
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from src.data.settings import PROJECT_ROOT
from src.engine.config import StrategyConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# Strategy directory descriptions (fallback if not in YAML)
_STRATEGY_DESCRIPTIONS = {
    "v6_value": "经典价值投资，6章深度分析，已回测验证(+7.1pp alpha)",
    "v6_enhanced": "增强版，8章+前瞻风险+一致性裁决，适合实盘深度分析",
    "quick_scan": "3章快速评估，10-15分钟出结论，适合批量初筛",
    "income_focus": "收息专用策略，聚焦股息可持续性分析",
}


@router.get("")
async def list_strategies():
    """List all available strategies with descriptions."""
    strategies_dir = PROJECT_ROOT / "strategies"
    if not strategies_dir.exists():
        return []

    strategies = []
    for strategy_dir in sorted(strategies_dir.iterdir()):
        if not strategy_dir.is_dir():
            continue

        yaml_path = strategy_dir / "strategy.yaml"
        if not yaml_path.exists():
            continue

        try:
            config = StrategyConfig.from_yaml(yaml_path)
            strategies.append({
                "name": strategy_dir.name,
                "display_name": config.name,
                "version": config.version,
                "description": _STRATEGY_DESCRIPTIONS.get(
                    strategy_dir.name,
                    f"{config.name} v{config.version}"
                ),
                "yaml_path": str(yaml_path),
                "chapter_count": len(config.get_chapter_defs()),
                "operators_dir": config.get_operators_dir() or "operators/v1",
            })
        except Exception as e:
            logger.warning(f"Failed to load strategy {strategy_dir.name}: {e}")

    return strategies


@router.get("/{name}/chapters")
async def get_chapters(name: str):
    """Get chapter details for a strategy."""
    yaml_path = PROJECT_ROOT / "strategies" / name / "strategy.yaml"
    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")

    try:
        config = StrategyConfig.from_yaml(yaml_path)
        chapter_defs = config.get_chapter_defs()

        # Load operator names from registry
        from src.engine.operators import OperatorRegistry
        operators_dir = config.get_operators_dir() or "operators/v1"
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

        # Get synthesis config
        synthesis = config.get_synthesis_config()

        return {
            "strategy_name": config.name,
            "version": config.version,
            "chapters": chapters,
            "synthesis": {
                "thinking_steps": len(synthesis.get("thinking_steps", [])),
                "has_scoring_rubric": bool(synthesis.get("scoring_rubric")),
                "decision_thresholds": synthesis.get("decision_thresholds", {}),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
