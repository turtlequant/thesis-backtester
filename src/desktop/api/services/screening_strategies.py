"""Persistent, numerical screening strategies for cross-sectional research.

Screening strategies deliberately contain no LLM or research-framework fields.
They are reusable numerical inputs that downstream research may reference, but
this module never imports or calls the qualitative-analysis subsystem.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.desktop.runtime import DESKTOP_RUNTIME_DIR
from src.engine.config import StrategyConfig


SCREENING_DB_PATH = DESKTOP_RUNTIME_DIR / "research.db"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = path or SCREENING_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS screening_strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            definition_json TEXT NOT NULL,
            is_builtin INTEGER NOT NULL DEFAULT 0,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def normalize_definition(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the stable, provider-neutral numerical strategy schema."""
    raw = raw or {}
    filters = []
    seen_filters = set()
    for item in raw.get("filters", []):
        field = str(item.get("field", "")).strip()
        if not field or field in seen_filters:
            continue
        seen_filters.add(field)
        normalized = {
            "field": field,
            "enabled": bool(item.get("enabled", True)),
            "mode": "percentile" if item.get("mode") == "percentile" else "value",
        }
        for key in ("min", "max", "percentile_min", "percentile_max"):
            value = item.get(key)
            if value is not None and value != "":
                normalized[key] = float(value)
        filters.append(normalized)

    ranking = []
    seen_ranking = set()
    for item in raw.get("ranking", []):
        field = str(item.get("field", "")).strip()
        if not field or field in seen_ranking:
            continue
        seen_ranking.add(field)
        ranking.append(
            {
                "field": field,
                "weight": float(item.get("weight", 1.0)),
                "direction": "asc" if item.get("direction") == "asc" else "desc",
                "na_handling": "worst"
                if item.get("na_handling") == "worst"
                else "neutral",
            }
        )

    return {
        "exclude_st": bool(raw.get("exclude_st", True)),
        "industry_cap": max(0, int(raw.get("industry_cap", 0) or 0)),
        "filters": filters,
        "ranking": ranking,
    }


def validate_definition(definition: Dict[str, Any], available_fields: Iterable[str]) -> None:
    fields = set(available_fields)
    for rule in definition["filters"]:
        if rule["field"] not in fields:
            raise ValueError(f"未知筛选字段: {rule['field']}")
        if rule["mode"] == "percentile":
            lower = rule.get("percentile_min")
            upper = rule.get("percentile_max")
            if lower is not None and not 0 <= lower <= 100:
                raise ValueError("分位下限必须在 0 到 100 之间")
            if upper is not None and not 0 <= upper <= 100:
                raise ValueError("分位上限必须在 0 到 100 之间")
        else:
            lower = rule.get("min")
            upper = rule.get("max")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"{rule['field']} 的下限不能大于上限")

    for node in definition["ranking"]:
        if node["field"] not in fields:
            raise ValueError(f"未知排名因子: {node['field']}")
        if node["weight"] <= 0:
            raise ValueError("排名因子权重必须大于 0")


def to_engine_screening(definition: Dict[str, Any]) -> Dict[str, Any]:
    """Translate the persisted schema to StrategyConfig's screening schema."""
    definition = normalize_definition(definition)
    filters = []
    for rule in definition["filters"]:
        item = {"field": rule["field"], "enabled": rule["enabled"]}
        if rule["mode"] == "percentile":
            for key in ("percentile_min", "percentile_max"):
                if key in rule:
                    item[key] = rule[key]
        else:
            for key in ("min", "max"):
                if key in rule:
                    item[key] = rule[key]
        filters.append(item)

    return {
        "exclude": (
            [{"field": "name", "contains": ["ST", "退"]}]
            if definition["exclude_st"]
            else []
        ),
        "industry_cap": definition["industry_cap"],
        "filters": filters,
        "scoring": {
            "factors": [
                {
                    "field": node["field"],
                    "weight": node["weight"],
                    "direction": node["direction"],
                    "na_handling": node["na_handling"],
                    "method": "percentile",
                }
                for node in definition["ranking"]
            ],
            "tiers": [],
            "default_tier": "入选",
        },
    }


def build_config(
    strategy: Dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    interval: str,
    top_n: int,
    run_dir: Path,
) -> StrategyConfig:
    raw = {
        "meta": {
            "name": strategy["name"],
            "version": strategy.get("updated_at") or "1",
        },
        "screening": to_engine_screening(strategy["definition"]),
        "backtest": {
            "start_date": start_date,
            "end_date": end_date,
            "cross_section_interval": interval,
            "top_n": int(top_n),
            "forward_periods": [
                {"months": 1, "label": "1个月"},
                {"months": 3, "label": "3个月"},
                {"months": 6, "label": "6个月"},
                {"months": 12, "label": "12个月"},
            ],
        },
        "paths": {"backtest_dir": str(run_dir.resolve())},
    }
    pseudo_path = DESKTOP_RUNTIME_DIR / "screening_strategies" / f"{strategy['id']}.yaml"
    return StrategyConfig(
        name=strategy["name"],
        version=str(strategy.get("updated_at") or "1"),
        yaml_path=pseudo_path,
        raw=raw,
    )


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    definition = json.loads(row["definition_json"])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "definition": definition,
        "is_builtin": bool(row["is_builtin"]),
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _purge_retired_builtin_strategies() -> None:
    """Remove the retired built-in presets while preserving every user strategy."""
    with closing(_connect()) as connection, connection:
        connection.execute("DELETE FROM screening_strategies WHERE is_builtin = 1")


def list_strategies() -> List[Dict[str, Any]]:
    _purge_retired_builtin_strategies()
    with closing(_connect()) as connection, connection:
        rows = connection.execute(
            """
            SELECT * FROM screening_strategies WHERE is_builtin = 0
            ORDER BY name COLLATE NOCASE, created_at
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_strategy(strategy_id: str) -> Dict[str, Any]:
    with closing(_connect()) as connection, connection:
        row = connection.execute(
            "SELECT * FROM screening_strategies WHERE id = ?", (strategy_id,)
        ).fetchone()
    if row is None:
        raise KeyError(strategy_id)
    return _row_to_dict(row)


def create_strategy(name: str, description: str, definition: Dict[str, Any]) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("筛选策略名称不能为空")
    strategy_id = uuid.uuid4().hex[:16]
    timestamp = _now()
    normalized = normalize_definition(definition)
    try:
        with closing(_connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO screening_strategies
                    (id, name, description, definition_json, is_builtin, source,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (
                    strategy_id,
                    name,
                    description.strip(),
                    json.dumps(normalized, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("筛选策略名称已存在") from exc
    return get_strategy(strategy_id)


def update_strategy(
    strategy_id: str,
    name: str,
    description: str,
    definition: Dict[str, Any],
) -> Dict[str, Any]:
    existing = get_strategy(strategy_id)
    if existing["is_builtin"]:
        raise ValueError("内置策略只读，请另存为新策略")
    name = name.strip()
    if not name:
        raise ValueError("筛选策略名称不能为空")
    try:
        with closing(_connect()) as connection, connection:
            connection.execute(
                """
                UPDATE screening_strategies
                SET name = ?, description = ?, definition_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    description.strip(),
                    json.dumps(normalize_definition(definition), ensure_ascii=False),
                    _now(),
                    strategy_id,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("筛选策略名称已存在") from exc
    return get_strategy(strategy_id)


def delete_strategy(strategy_id: str) -> None:
    existing = get_strategy(strategy_id)
    if existing["is_builtin"]:
        raise ValueError("内置策略不能删除")
    with closing(_connect()) as connection, connection:
        connection.execute("DELETE FROM screening_strategies WHERE id = ?", (strategy_id,))
