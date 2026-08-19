"""Structured-research batch and framework-validation endpoints."""
from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.backtest.pipeline import generate_crosssection_dates
from src.data.config import get_active_provider_name
from src.desktop.runtime import DESKTOP_CONFIG_PATH

from ..services import screening_strategies
from ..services.qualitative_jobs import (
    FRAMEWORKS_ROOT,
    framework_snapshot,
    qualitative_job_manager,
    screening_identity,
)
from ..services.validation_archive import list_validation_archive
from . import research


router = APIRouter(prefix="/api/qualitative", tags=["qualitative"])


class LatestRunRequest(BaseModel):
    screening_strategy_id: str
    framework_id: str
    top_n: int = Field(default=10, ge=1, le=100)
    concurrency: int = Field(default=2, ge=1, le=10)


class ValidationRunRequest(BaseModel):
    screening_strategy_id: str
    framework_id: str
    start_date: str
    end_date: str
    interval: str = "6m"
    top_n: int = Field(default=10, ge=1, le=100)
    concurrency: int = Field(default=2, ge=1, le=10)


def _llm_status() -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    if DESKTOP_CONFIG_PATH.exists():
        try:
            settings = json.loads(DESKTOP_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
    configured = bool(settings.get("llm_api_key") or os.environ.get("LLM_API_KEY"))
    raw_temperature = settings.get("temperature")
    if raw_temperature in (None, ""):
        raw_temperature = os.environ.get("LLM_TEMPERATURE", 0.1)
    raw_max_tokens = settings.get("max_tokens")
    if raw_max_tokens in (None, ""):
        raw_max_tokens = os.environ.get("LLM_MAX_TOKENS", 8192)
    return {
        "configured": configured,
        "model": settings.get("llm_model") or os.environ.get("LLM_MODEL") or "按框架配置",
        "temperature": float(raw_temperature),
        "max_tokens": int(raw_max_tokens),
    }


def _resolve_inputs(screening_strategy_id: str, framework_id: str):
    try:
        strategy = screening_strategies.get_strategy(screening_strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="筛选策略不存在") from exc
    try:
        framework = framework_snapshot(framework_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="研究框架不存在") from exc
    return strategy, framework


def _screening_scope(strategy: Dict[str, Any]) -> Dict[str, Any]:
    definition = screening_strategies.normalize_definition(strategy.get("definition"))
    return {
        "id": strategy["id"],
        "name": strategy["name"],
        "description": str(strategy.get("description") or ""),
        "identity": screening_identity(strategy),
        "definition": definition,
        "filter_count": sum(1 for item in definition["filters"] if item.get("enabled", True)),
        "ranking_count": len(definition["ranking"]),
    }


def _screening_warnings(strategy: Dict[str, Any]) -> list[str]:
    definition = screening_strategies.normalize_definition(strategy.get("definition"))
    warnings = []
    if not any(item.get("enabled", True) for item in definition["filters"]):
        warnings.append("筛选策略没有启用过滤条件，候选范围可能过宽")
    if not definition["ranking"]:
        warnings.append("筛选策略没有排名因子，Top N 的顺序缺少明确依据")
    return warnings


async def _latest_preflight(request: LatestRunRequest) -> Dict[str, Any]:
    strategy, framework = _resolve_inputs(
        request.screening_strategy_id, request.framework_id
    )
    status = await research.screening_status()
    llm = _llm_status()
    blockers = []
    if not status.get("available") or not status.get("latest_date"):
        blockers.append("当前数据源没有可用的本地截面数据")
    if not llm["configured"]:
        blockers.append("尚未配置 LLM API Key")
    if framework["integrity_blockers"]:
        blockers.append("研究框架结构不完整，请先修复无效章节、依赖或算子引用")
    calls = int(request.top_n)
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": _screening_warnings(strategy),
        "provider": status.get("provider"),
        "latest_date": status.get("latest_date"),
        "requested_date": date.today().isoformat(),
        "screening_strategy": _screening_scope(strategy),
        "framework": framework,
        "estimated": {
            "analyses": calls,
            "cost_yuan": round(calls * 0.4, 1),
            "minutes": round(calls * 5 / max(1, request.concurrency)),
        },
        "llm": llm,
    }


async def _validation_preflight(request: ValidationRunRequest) -> Dict[str, Any]:
    if request.start_date > request.end_date:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    if not re.fullmatch(r"(?:[1-9]\d*)[mwy]", request.interval.lower()):
        raise HTTPException(status_code=400, detail="截面频率格式应为 1m、3m、1y 或 2w")
    strategy, framework = _resolve_inputs(
        request.screening_strategy_id, request.framework_id
    )
    status = await research.screening_status()
    llm = _llm_status()
    dates = generate_crosssection_dates(
        request.start_date, request.end_date, request.interval
    )
    blockers = []
    if not dates:
        blockers.append("所选区间没有可执行截面")
    if not status.get("available"):
        blockers.append("当前数据源没有可用的严格历史数据")
    if not llm["configured"]:
        blockers.append("尚未配置 LLM API Key")
    if framework["integrity_blockers"]:
        blockers.append("研究框架结构不完整，请先修复无效章节、依赖或算子引用")
    if framework["history_blockers"]:
        blockers.append("框架包含不能用于严格历史验证的算子")
    calls = len(dates) * int(request.top_n)
    warnings = _screening_warnings(strategy)
    if status.get("latest_date") and request.end_date > status["latest_date"]:
        warnings.append(f"结束日期晚于本地数据截止日 {status['latest_date']}，后段截面可能无数据")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "provider": status.get("provider"),
        "latest_date": status.get("latest_date"),
        "dates": dates,
        "screening_strategy": _screening_scope(strategy),
        "framework": framework,
        "estimated": {
            "slices": len(dates),
            "analyses": calls,
            "cost_yuan": round(calls * 0.4, 1),
            "minutes": round(calls * 5 / max(1, request.concurrency)),
        },
        "llm": llm,
    }


def _job_params(request: BaseModel, preflight: Dict[str, Any]) -> Dict[str, Any]:
    values = request.dict()
    strategy = screening_strategies.get_strategy(values["screening_strategy_id"])
    values.update(
        screening_strategy_name=strategy["name"],
        screening_strategy_identity=preflight["screening_strategy"]["identity"],
        screening_strategy_snapshot=strategy,
        framework_name=preflight["framework"]["name"],
        framework_identity=preflight["framework"]["identity"],
        framework_snapshot=preflight["framework"],
        provider=preflight.get("provider"),
        model=preflight.get("llm", {}).get("model"),
    )
    return values


def _is_current(job: Dict[str, Any]) -> bool:
    params = job.get("params", {})
    try:
        strategy = screening_strategies.get_strategy(params["screening_strategy_id"])
        framework = framework_snapshot(params["framework_id"])
    except (KeyError, TypeError):
        return False
    return (
        params.get("screening_strategy_identity") == screening_identity(strategy)
        and params.get("framework_identity") == framework["identity"]
        and params.get("provider") == get_active_provider_name()
    )


@router.get("/options")
async def qualitative_options():
    strategies = screening_strategies.list_strategies()
    frameworks = []
    root = FRAMEWORKS_ROOT
    if root.exists():
        for directory in sorted(root.iterdir()):
            if not (directory / "strategy.yaml").exists():
                continue
            try:
                item = framework_snapshot(directory.name)
                frameworks.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "chapter_count": item["chapter_count"],
                        "operator_count": item["operator_count"],
                        "identity": item["identity"],
                        "valid": not item["integrity_blockers"],
                        "history_safe": not item["integrity_blockers"] and not item["history_blockers"],
                        "history_native": not item["history_blockers"] and not item["history_adaptations"],
                        "history_adaptation_count": len(item["history_adaptations"]),
                        "history_blocker_count": len(item["history_blockers"]),
                    }
                )
            except Exception:
                continue
    status = await research.screening_status()
    return {
        "screening_strategies": strategies,
        "frameworks": frameworks,
        "status": status,
        "llm": _llm_status(),
    }


@router.post("/latest/preflight")
async def latest_preflight(request: LatestRunRequest):
    return await _latest_preflight(request)


@router.post("/latest/start")
async def start_latest(request: LatestRunRequest):
    preflight = await _latest_preflight(request)
    if not preflight["ready"]:
        raise HTTPException(status_code=409, detail="；".join(preflight["blockers"]))
    params = _job_params(request, preflight)
    params["cutoff_date"] = preflight["requested_date"]
    try:
        return qualitative_job_manager.start("latest_judgement", params)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/validation/preflight")
async def validation_preflight(request: ValidationRunRequest):
    return await _validation_preflight(request)


@router.post("/validation/start")
async def start_validation(request: ValidationRunRequest):
    preflight = await _validation_preflight(request)
    if not preflight["ready"]:
        raise HTTPException(status_code=409, detail="；".join(preflight["blockers"]))
    try:
        return qualitative_job_manager.start(
            "framework_validation", _job_params(request, preflight)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs")
async def list_qualitative_jobs(
    kind: str = "latest_judgement",
    limit: int = 20,
    current_only: bool = True,
):
    jobs = qualitative_job_manager.list_jobs(kind, limit)
    for job in jobs:
        job["is_current"] = _is_current(job)
    return [job for job in jobs if job["is_current"] or not current_only]


@router.get("/validation/archive")
async def validation_archive():
    """Expose converted legacy backtests without treating them as current jobs."""
    archives = list_validation_archive(FRAMEWORKS_ROOT)
    for archive in archives:
        provenance = archive.setdefault("provenance", {})
        try:
            snapshot = framework_snapshot(archive["params"]["framework_id"])
            blockers = snapshot.get("history_blockers", [])
            adaptations = snapshot.get("history_adaptations", [])
            # Imported archives predate runtime adaptation and must not be relabelled.
            provenance["current_history_safe"] = not blockers and not adaptations
            provenance["current_history_blocker_count"] = len(blockers) + len(adaptations)
        except (KeyError, TypeError):
            provenance["current_history_safe"] = None
            provenance["current_history_blocker_count"] = None
    return archives


@router.get("/jobs/{job_id}")
async def get_qualitative_job(job_id: str):
    try:
        job = qualitative_job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批量任务不存在") from exc
    job["is_current"] = _is_current(job)
    return job


@router.post("/jobs/{job_id}/pause")
async def pause_qualitative_job(job_id: str):
    try:
        return qualitative_job_manager.pause(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批量任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/resume")
async def resume_qualitative_job(job_id: str):
    try:
        return qualitative_job_manager.resume(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批量任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
