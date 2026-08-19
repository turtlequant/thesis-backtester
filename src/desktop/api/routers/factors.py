"""Provider-aware factor catalog and Polars DSL management endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.data.config import SUPPORTED_PROVIDERS, get_active_provider_name
from src.data.factor_materialization import (
    invalidate_factor_materializations,
    set_factor_materialization,
)
from src.data.jobs import JobManagerClosed, job_manager
from src.engine.factor_catalog import (
    FactorCatalog,
    save_factor_definition,
    validate_factor_definition,
)


router = APIRouter(prefix="/api/factors", tags=["factors"])


class FactorOutputRequest(BaseModel):
    dtype: str = "float64"
    unit: str = ""
    direction: str = "neutral"


class FactorPoliciesRequest(BaseModel):
    null: str = "propagate"
    point_in_time: str = "strict"
    enabled: bool = True


class FactorExecutionRequest(BaseModel):
    mode: Optional[str] = None
    frequency: str = "annual"


class FactorDefinitionRequest(BaseModel):
    schema_version: int = 1
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    category: str = Field(default="other", min_length=1, max_length=80)
    tags: List[str] = Field(default_factory=list)
    type: str = "cross_section"
    grain: str = "security_date"
    engine: str = "polars"
    execution: Optional[FactorExecutionRequest] = None
    inputs: Dict[str, str] = Field(default_factory=dict)
    optional_inputs: List[str] = Field(default_factory=list)
    expression: str = Field(min_length=1, max_length=4000)
    output: FactorOutputRequest = Field(default_factory=FactorOutputRequest)
    policies: FactorPoliciesRequest = Field(default_factory=FactorPoliciesRequest)


def _model_dict(model: BaseModel) -> Dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    return dump() if dump else model.dict()


def _provider_or_400(provider: Optional[str]) -> str:
    selected = (provider or get_active_provider_name()).lower()
    if selected not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的数据源: {selected}")
    return selected


def _schedule_materialization(definition, *, invalidate_existing: bool) -> Optional[Dict[str, Any]]:
    provider = get_active_provider_name()
    if invalidate_existing:
        invalidate_factor_materializations(definition.id, definition.definition_hash)

    catalog = FactorCatalog(provider=provider)
    asset = catalog.get_asset(definition.id)
    indicator = catalog.snapshot.datasets.get("daily/indicator", {})
    if (
        asset is None
        or asset["provider"]["compatibility"] != "exact"
        or bool(asset.get("materialization_blockers"))
        or not int(indicator.get("row_count", 0))
    ):
        return None

    set_factor_materialization(
        provider,
        definition.id,
        definition.definition_hash,
        "pending",
    )
    try:
        return job_manager.start_job(provider, "factors", codes=[definition.id])
    except JobManagerClosed as exc:
        set_factor_materialization(
            provider,
            definition.id,
            definition.definition_hash,
            "stale",
            error=None,
        )
        return {
            "id": "",
            "provider": provider,
            "job_type": "factors",
            "codes": [definition.id],
            "status": "interrupted",
            "percent": 0,
            "message": str(exc),
            "error": None,
        }
    except ValueError as exc:
        set_factor_materialization(
            provider,
            definition.id,
            definition.definition_hash,
            "failed",
            error=str(exc),
        )
        return {
            "id": "",
            "provider": provider,
            "job_type": "factors",
            "codes": [definition.id],
            "status": "failed",
            "percent": 0,
            "message": "自动计算未能进入队列",
            "error": str(exc),
        }


def schedule_catalog_materializations() -> Optional[Dict[str, Any]]:
    """Queue shipped or migrated DSL definitions once their raw inputs exist."""
    return job_manager.reconcile_factor_definitions(get_active_provider_name())


@router.get("")
async def list_factor_catalog(provider: Optional[str] = Query(default=None)):
    selected = _provider_or_400(provider)
    return FactorCatalog(provider=selected).payload()


@router.post("/validate")
async def validate_factor(request: FactorDefinitionRequest):
    try:
        return validate_factor_definition(_model_dict(request))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
async def create_factor(request: FactorDefinitionRequest):
    try:
        definition = save_factor_definition(_model_dict(request))
        job = _schedule_materialization(definition, invalidate_existing=False)
        asset = FactorCatalog().get_asset(definition.id)
        result = asset or {"id": definition.id, "status": "created"}
        result["materialization_job"] = job
        return result
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{factor_id}")
async def update_factor(factor_id: str, request: FactorDefinitionRequest):
    try:
        definition = save_factor_definition(
            _model_dict(request),
            existing_id=factor_id,
        )
        job = _schedule_materialization(definition, invalidate_existing=True)
        asset = FactorCatalog().get_asset(definition.id)
        result = asset or {"id": definition.id, "status": "updated"}
        result["materialization_job"] = job
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{factor_id}/materialize")
async def materialize_factor(factor_id: str):
    catalog = FactorCatalog()
    definition = catalog.get_definition(factor_id)
    asset = catalog.get_asset(factor_id)
    if definition is None or asset is None:
        raise HTTPException(status_code=404, detail=f"因子不存在: {factor_id}")
    if not definition.editable:
        raise HTTPException(status_code=400, detail="只支持物化 Polars DSL 因子")
    if asset["provider"]["compatibility"] != "exact":
        raise HTTPException(status_code=409, detail="当前数据源缺少精确输入字段")
    if asset.get("materialization_blockers"):
        raise HTTPException(
            status_code=409,
            detail="；".join(asset["materialization_blockers"]),
        )
    if asset["materialization"]["status"] in {"pending", "computing"}:
        raise HTTPException(status_code=409, detail="该因子已经在计算队列中")
    job = _schedule_materialization(definition, invalidate_existing=False)
    if job is None:
        raise HTTPException(status_code=409, detail="当前数据源尚无每日指标历史")
    if job.get("status") == "failed":
        raise HTTPException(status_code=409, detail=str(job.get("error") or "无法开始计算"))
    return job


@router.post("/{factor_id}/prepare")
async def prepare_factor(factor_id: str):
    """Queue missing raw data; reconciliation materializes the factor next."""
    provider = get_active_provider_name()
    catalog = FactorCatalog(provider=provider)
    definition = catalog.get_definition(factor_id)
    asset = catalog.get_asset(factor_id)
    if definition is None or asset is None:
        raise HTTPException(status_code=404, detail=f"因子不存在: {factor_id}")
    if not definition.editable:
        raise HTTPException(status_code=400, detail="只支持准备 Polars DSL 因子")
    if asset["provider"]["compatibility"] != "exact":
        raise HTTPException(status_code=409, detail="当前数据源缺少精确输入字段，无法自动补齐")

    blockers = asset.get("materialization_blockers") or []
    if not blockers:
        job = _schedule_materialization(definition, invalidate_existing=False)
        if job is None:
            raise HTTPException(status_code=409, detail="当前没有需要补齐的数据依赖")
        return job

    datasets = []
    for semantic_id in definition.inputs.values():
        source = catalog.fields.require(semantic_id)
        binding = source.binding_for(provider)
        if binding is not None:
            datasets.append(binding.dataset)
    job_type = "financials" if any(
        dataset.startswith("financial/") for dataset in datasets
    ) else "market"
    try:
        job = job_manager.start_job(provider, job_type)
    except (JobManagerClosed, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job["continuation"] = {
        "factor_id": factor_id,
        "next": "materialize",
    }
    return job


@router.get("/{factor_id}")
async def get_factor(factor_id: str, provider: Optional[str] = Query(default=None)):
    selected = _provider_or_400(provider)
    asset = FactorCatalog(provider=selected).get_asset(factor_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"因子不存在: {factor_id}")
    return asset
