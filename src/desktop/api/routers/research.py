"""Desktop research-workspace endpoints."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.data import storage
from src.data.config import get_active_provider_name
from src.data.settings import DATA_ROOT
from src.desktop.api.services.research_jobs import research_job_manager
from src.desktop.api.services import screening_strategies
from src.desktop.api.services.screening_preview_cache import get_screening_preview
from src.engine.factor_catalog import FactorCatalog
from src.screener.quick_filter import screen_at_date


router = APIRouter(prefix="/api/research", tags=["research"])


class CrossSectionRunRequest(BaseModel):
    screening_strategy_id: str
    start_date: str
    end_date: str
    interval: str = "6m"
    top_n: int = Field(default=50, ge=1, le=1000)


class ScreeningStrategyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    definition: Dict[str, Any] = Field(default_factory=dict)


class ScreeningPreviewRequest(BaseModel):
    definition: Dict[str, Any] = Field(default_factory=dict)
    as_of_date: str
    top_n: int = Field(default=30, ge=1, le=200)
    historical: bool = False
    force: bool = False


def _validate_dates(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期必须为 YYYY-MM-DD") from exc
    if start > end:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")


def _screening_fields() -> List[Dict[str, Any]]:
    fields = {}
    for asset in FactorCatalog().list_assets():
        if not asset.get("screening_catalogued", asset["screening_eligible"]):
            continue
        fields[asset["id"]] = {
            "id": asset["id"],
            "name": asset["name"],
            "description": asset["description"],
            "group": (
                f"原生 · {asset['category']}"
                if asset["asset_kind"] == "native"
                else f"派生 · {asset['category']}"
            ),
            "preferred_direction": asset["preferred_direction"],
            "source": asset["asset_kind"],
            "editable": asset.get("editable", False),
            "data_needed": asset["data_needed"],
            "provider_compatibility": asset["provider"]["compatibility"],
            "provider_note": asset["provider"].get("note", ""),
            "point_in_time_safe": asset["point_in_time_safe"],
            "execution_mode": asset.get("execution_mode", "native"),
            "capabilities": asset.get("capabilities", {}),
            "materialization": asset["materialization"],
            "materialization_blockers": asset.get("materialization_blockers", []),
        }
    return sorted(fields.values(), key=lambda item: (item["group"], item["name"]))


def _validate_screening_definition(raw: Dict[str, Any]) -> Dict[str, Any]:
    definition = screening_strategies.normalize_definition(raw)
    screening_strategies.validate_definition(
        definition,
        (field["id"] for field in _screening_fields()),
    )
    return definition


def _screening_factor_ids(definition: Dict[str, Any]) -> set[str]:
    return {
        str(node.get("field"))
        for section in ("filters", "ranking")
        for node in definition.get(section, [])
        if node.get("field")
    }


def _require_screening_coverage(
    definition: Dict[str, Any],
    start_date: str,
    end_date: str,
    *,
    historical: bool,
) -> None:
    catalog = FactorCatalog(provider=get_active_provider_name())
    capability = "historical_screen" if historical else "current_screen"
    failures = []
    for factor_id in sorted(_screening_factor_ids(definition)):
        asset = catalog.get_asset(factor_id)
        if asset is None or not asset.get("capabilities", {}).get(capability, False):
            reason = "、".join((asset or {}).get("materialization_blockers", []))
            failures.append(f"{factor_id}（{reason or '当前场景不可执行'}）")
            continue
        materialization = asset["materialization"]
        if asset.get("execution_mode") != "point_in_time":
            continue
        materialized_start = materialization.get("start_date")
        materialized_end = materialization.get("latest_date")
        if (materialized_start and materialized_start > start_date) or (
            materialized_end and materialized_end < end_date
        ):
            failures.append(
                f"{factor_id}（覆盖 {materialized_start or '?'} 至 {materialized_end or '?'}）"
            )
    if failures:
        raise HTTPException(
            status_code=409,
            detail="以下因子尚未完成所需日期的时点物化：" + "、".join(failures),
        )


def _read_dataset_catalog(provider: str) -> dict:
    """Read coverage metadata without taking a writer lock on the market DB."""
    path = storage.get_database_path(provider)
    if not path.exists():
        return {}
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            rows = connection.execute(
                "SELECT category, sub, partition_count, latest_date FROM _datasets"
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        (str(category), str(sub)): {
            "partitions": int(partition_count or 0),
            "latest_date": latest_date,
        }
        for category, sub, partition_count, latest_date in rows
    }


def _screening_data_revision(provider: str) -> str:
    """Use catalog write timestamps, unaffected by SQLite read-side WAL files."""
    path = storage.get_database_path(provider)
    if not path.exists():
        return "missing"
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            dataset_row = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM _datasets"
            ).fetchone()
            has_materializations = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='_factor_materializations'"
            ).fetchone()
            materialization_rows = (
                connection.execute(
                    "SELECT factor_id, definition_hash, status, updated_at "
                    "FROM _factor_materializations ORDER BY factor_id"
                ).fetchall()
                if has_materializations
                else []
            )
    except sqlite3.Error:
        return "unavailable"
    revision = json.dumps(
        [int(dataset_row[0] or 0), dataset_row[1], materialization_rows],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(revision.encode("utf-8")).hexdigest()


def _screening_preview_key(
    definition: Dict[str, Any],
    request: ScreeningPreviewRequest,
) -> str:
    provider = get_active_provider_name()
    payload = {
        "provider": provider,
        "data_revision": _screening_data_revision(provider),
        "definition": definition,
        "as_of_date": request.as_of_date,
        "top_n": request.top_n,
        "historical": request.historical,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compute_screening_preview(
    definition: Dict[str, Any],
    request: ScreeningPreviewRequest,
) -> Dict[str, Any]:
    definition = _validate_screening_definition(definition)
    _require_screening_coverage(
        definition,
        request.as_of_date,
        request.as_of_date,
        historical=request.historical,
    )
    preview_strategy = {
        "id": "preview",
        "name": "未保存策略预览",
        "updated_at": "preview",
        "definition": definition,
    }
    config = screening_strategies.build_config(
        preview_strategy,
        start_date=request.as_of_date,
        end_date=request.as_of_date,
        interval="1m",
        top_n=request.top_n,
        run_dir=DATA_ROOT / "research_previews",
    )
    result = screen_at_date(request.as_of_date, config, request.top_n)
    candidates = result.candidates.astype(object).where(
        pd.notna(result.candidates), None
    )
    return {
        "requested_date": request.as_of_date,
        "effective_date": result.effective_date,
        "funnel": {
            "universe": result.total_stocks,
            "after_filters": result.after_basic_filter,
            "selected": len(result.candidates),
        },
        "stocks": candidates.to_dict(orient="records"),
    }


@router.get("/screening-fields")
async def list_screening_fields():
    """Numerical fields that may be used by filters and ranking."""
    return _screening_fields()


@router.get("/screening-status")
async def screening_status():
    """Return the latest locally executable screening snapshot."""
    provider = get_active_provider_name()
    catalog = _read_dataset_catalog(provider)
    indicator = catalog.get(("daily", "indicator"), {})
    return {
        "provider": provider,
        "latest_date": indicator.get("latest_date"),
        "available": bool(indicator.get("partitions")),
    }


@router.get("/screening-strategies")
async def list_screening_strategies():
    return screening_strategies.list_strategies()


@router.post("/screening-strategies")
async def create_screening_strategy(request: ScreeningStrategyRequest):
    definition = _validate_screening_definition(request.definition)
    try:
        return screening_strategies.create_strategy(
            request.name,
            request.description,
            definition,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/screening-strategies/{strategy_id}")
async def update_screening_strategy(strategy_id: str, request: ScreeningStrategyRequest):
    definition = _validate_screening_definition(request.definition)
    try:
        return screening_strategies.update_strategy(
            strategy_id,
            request.name,
            request.description,
            definition,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="筛选策略不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/screening-strategies/{strategy_id}")
async def delete_screening_strategy(strategy_id: str):
    try:
        screening_strategies.delete_strategy(strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="筛选策略不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/screening-preview")
async def preview_screening(request: ScreeningPreviewRequest):
    _validate_dates(request.as_of_date, request.as_of_date)
    definition = screening_strategies.normalize_definition(request.definition)
    try:
        return await get_screening_preview(
            _screening_preview_key(definition, request),
            lambda: _compute_screening_preview(definition, request),
            force=request.force,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cross-section/presets")
async def cross_section_presets():
    """Compatibility view backed only by independent numerical strategies."""
    return [
        {
            "id": strategy["id"],
            "name": strategy["name"],
            "version": strategy["updated_at"],
            "filter_count": len(strategy["definition"]["filters"]),
            "factor_count": len(strategy["definition"]["ranking"]),
            "tier_count": 0,
            "start_date": "2020-01-01",
            "end_date": date.today().isoformat(),
            "interval": "6m",
            "top_n": 50,
        }
        for strategy in screening_strategies.list_strategies()
    ]


@router.post("/cross-section/start")
async def start_cross_section(request: CrossSectionRunRequest):
    _validate_dates(request.start_date, request.end_date)
    if not re.fullmatch(r"(?:[1-9]\d*)[mwy]", request.interval.lower()):
        raise HTTPException(status_code=400, detail="截面频率格式应为 1m、6m、1y 或 2w")
    try:
        strategy = screening_strategies.get_strategy(request.screening_strategy_id)
        _require_screening_coverage(
            strategy["definition"],
            request.start_date,
            request.end_date,
            historical=True,
        )
        params = request.dict()
        params["screening_strategy_name"] = strategy["name"]
        params["screening_strategy_snapshot"] = strategy
        return research_job_manager.start_cross_section(params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="筛选策略不存在") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs")
async def list_research_jobs(kind: str = "cross_section", limit: int = 20):
    return research_job_manager.list_jobs(kind=kind, limit=limit)


@router.get("/jobs/{job_id}")
async def get_research_job(job_id: str):
    try:
        return research_job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="研究任务不存在") from exc
