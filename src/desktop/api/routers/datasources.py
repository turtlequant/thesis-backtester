"""Data catalog, provider status and local download management endpoints."""
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.config import load_data_config
from src.data.jobs import job_manager
from src.data.provider import (
    PROVIDER_CAPABILITIES,
    clear_provider_cache,
    get_provider,
)
from src.data.storage import get_database_status

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

# ==================== Data Source Registry ====================

DATA_SOURCES = [
    # ---- 基础信息 ----
    {
        "id": "basic_info",
        "name": "基础信息",
        "category": "基础",
        "description": "股票代码、名称、行业、地区、上市日期等",
        "source": "AKShare / Tushare",
        "snapshot_field": "stock_name, industry, area, list_date",
        "always_available": True,
    },
    # ---- 行情数据 ----
    {
        "id": "price_history",
        "name": "日线行情",
        "category": "行情",
        "description": "近2年日线 OHLCV（开高低收量），含涨跌幅、换手率",
        "source": "AKShare (东方财富/新浪)",
        "snapshot_field": "price_history",
        "key_columns": ["日期", "开盘", "收盘", "最高", "最低", "成交量", "涨跌幅"],
    },
    {
        "id": "daily_indicators",
        "name": "每日指标",
        "category": "行情",
        "description": "PE(TTM)、PB、股息率、总市值等每日估值指标",
        "source": "AKShare (同花顺)",
        "snapshot_field": "daily_indicators",
        "key_columns": ["trade_date", "pe_ttm", "pb", "dv_ttm", "total_mv"],
    },
    # ---- 财务报表 ----
    {
        "id": "balancesheet",
        "name": "资产负债表",
        "category": "财报",
        "description": "资产、负债、股东权益的完整结构，含公告日期",
        "source": "AKShare (东方财富)",
        "snapshot_field": "balancesheet",
        "key_columns": ["REPORT_DATE", "NOTICE_DATE", "TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"],
    },
    {
        "id": "income",
        "name": "利润表",
        "category": "财报",
        "description": "营收、成本、利润的完整结构",
        "source": "AKShare (东方财富)",
        "snapshot_field": "income",
        "key_columns": ["REPORT_DATE", "NOTICE_DATE", "OPERATE_INCOME", "OPERATE_PROFIT", "NETPROFIT"],
    },
    {
        "id": "cashflow",
        "name": "现金流量表",
        "category": "财报",
        "description": "经营、投资、筹资活动现金流",
        "source": "AKShare (东方财富)",
        "snapshot_field": "cashflow",
        "key_columns": ["REPORT_DATE", "NOTICE_DATE", "NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE"],
    },
    {
        "id": "fina_indicator",
        "name": "财务指标",
        "category": "财报",
        "description": "86项财务分析指标：ROE、利润率、周转率、杠杆率等",
        "source": "AKShare (网易财经)",
        "snapshot_field": "fina_indicator",
        "key_columns": ["日期", "净资产收益率(%)", "销售净利率(%)", "资产负债率(%)"],
    },
    # ---- 股东与治理 ----
    {
        "id": "top10_holders",
        "name": "十大股东",
        "category": "股东",
        "description": "前十大股东持股数量、比例、性质",
        "source": "AKShare (同花顺)",
        "snapshot_field": "top10_holders",
        "key_columns": ["股东名称", "持股数量", "持股比例", "股本性质"],
    },
    {
        "id": "top10_floatholders",
        "name": "十大流通股东",
        "category": "股东",
        "description": "前十大流通股东，含机构和个人",
        "source": "AKShare",
        "snapshot_field": "top10_floatholders",
    },
    {
        "id": "stk_holdernumber",
        "name": "股东户数",
        "category": "股东",
        "description": "股东户数变动趋势（筹码集中度）",
        "source": "AKShare",
        "snapshot_field": "stk_holdernumber",
    },
    {
        "id": "stk_holdertrade",
        "name": "股东增减持",
        "category": "股东",
        "description": "重要股东增减持记录",
        "source": "AKShare",
        "snapshot_field": "stk_holdertrade",
    },
    # ---- 分红与回购 ----
    {
        "id": "dividend",
        "name": "分红历史",
        "category": "分红",
        "description": "历年分红记录：送股、转增、派息",
        "source": "AKShare (同花顺)",
        "snapshot_field": "dividend",
        "key_columns": ["公告日期", "派息", "除权除息日"],
    },
    {
        "id": "repurchase",
        "name": "回购记录",
        "category": "分红",
        "description": "股票回购计划和执行情况",
        "source": "AKShare",
        "snapshot_field": "repurchase",
    },
    # ---- 风险数据 ----
    {
        "id": "fina_audit",
        "name": "审计意见",
        "category": "风险",
        "description": "历年审计意见类型（标准无保留/保留/否定等）",
        "source": "AKShare",
        "snapshot_field": "fina_audit",
    },
    {
        "id": "pledge_stat",
        "name": "股权质押",
        "category": "风险",
        "description": "大股东股权质押比例和详情",
        "source": "AKShare",
        "snapshot_field": "pledge_stat",
    },
    {
        "id": "fina_mainbz",
        "name": "主营构成",
        "category": "业务",
        "description": "按产品/地区的营收构成（判断业务集中度）",
        "source": "AKShare",
        "snapshot_field": "fina_mainbz",
    },
    # ---- 市场数据（增强，通过 Tool 调用）----
    {
        "id": "news",
        "name": "近期新闻",
        "category": "市场",
        "description": "最近 10-20 条个股相关新闻标题和摘要",
        "source": "AKShare (东方财富)",
        "snapshot_field": "news",
        "key_columns": ["新闻标题", "发布时间", "文章来源"],
    },
    {
        "id": "fund_flow",
        "name": "资金流向",
        "category": "市场",
        "description": "近 30 天主力/超大单/大单/中单/小单资金净流入",
        "source": "AKShare (东方财富)",
        "snapshot_field": "fund_flow",
        "key_columns": ["日期", "主力净流入-净额", "主力净流入-净占比"],
    },
    {
        "id": "index_daily",
        "name": "大盘指数",
        "category": "市场",
        "description": "沪深300 近 60 天行情（判断大盘环境）",
        "source": "AKShare (新浪)",
        "snapshot_field": "index_daily",
    },
    {
        "id": "industry_summary",
        "name": "行业概况",
        "category": "市场",
        "description": "所属行业整体涨跌、成交、资金流向",
        "source": "AKShare (同花顺)",
        "snapshot_field": "industry_summary",
    },
]

# Build lookup
_SOURCE_MAP = {s["id"]: s for s in DATA_SOURCES}
_CATEGORIES = sorted(set(s["category"] for s in DATA_SOURCES))


@router.get("")
async def list_datasources():
    """List all available data sources grouped by category."""
    provider = load_data_config()["provider"]
    capability = PROVIDER_CAPABILITIES[provider]
    instant_only = {"news", "fund_flow", "index_daily", "industry_summary"}
    baostock_supported = {
        "basic_info", "price_history", "daily_indicators", "balancesheet",
        "income", "cashflow", "fina_indicator", "dividend",
    }
    baostock_overrides = {
        "daily_indicators": {
            "description": "PE(TTM)、PB、PS、PCF 与换手率；BaoStock 不提供总市值和股息率日快照。",
            "key_columns": ["trade_date", "pe_ttm", "pb", "ps_ttm", "pcf_ncf_ttm"],
        },
        "balancesheet": {
            "description": "流动比率、速动比率、资产负债率等偿债结构指标，不是完整资产负债表。",
            "key_columns": ["ann_date", "end_date", "current_ratio", "quick_ratio", "debt_to_assets"],
        },
        "income": {
            "description": "营收、净利润、EPS、ROE 与利润率摘要，不是完整利润表科目。",
            "key_columns": ["ann_date", "end_date", "revenue", "net_profit", "eps", "roe"],
        },
        "cashflow": {
            "description": "经营现金流与收入、净利润等比率指标，不是完整现金流量表。",
            "key_columns": ["ann_date", "end_date", "ocf_to_revenue", "ocf_to_net_profit"],
        },
    }

    enriched = []
    for source in DATA_SOURCES:
        item = dict(source)
        if provider == "akshare":
            available = True
        elif source["id"] in instant_only:
            available = False
        elif provider == "baostock":
            available = source["id"] in baostock_supported
        else:
            available = True
        item["available"] = available
        item["source"] = capability.label if available else "当前数据口径不提供"
        if provider == "baostock" and source["id"] in baostock_overrides:
            item.update(baostock_overrides[source["id"]])
        enriched.append(item)

    grouped = {}
    for cat in _CATEGORIES:
        grouped[cat] = [s for s in enriched if s["category"] == cat]
    return {
        "categories": _CATEGORIES,
        "sources": grouped,
        "total": len(enriched),
        "all": enriched,
        "provider": provider,
    }


class DataJobRequest(BaseModel):
    provider: Optional[str] = None
    job_type: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    codes: Optional[List[str]] = None


@router.get("/providers")
async def list_provider_status():
    config = load_data_config()
    providers = []
    for name, capability in PROVIDER_CAPABILITIES.items():
        item = capability.to_dict()
        item["selected"] = name == config["provider"]
        item["storage"] = get_database_status(name)
        providers.append(item)
    return {"selected": config["provider"], "providers": providers}


@router.get("/status")
async def data_status(provider: Optional[str] = None):
    name = (provider or load_data_config()["provider"]).lower()
    if name not in PROVIDER_CAPABILITIES:
        raise HTTPException(status_code=400, detail=f"不支持的数据源: {name}")
    return get_database_status(name)


@router.post("/test/{provider_name}")
async def test_provider(provider_name: str):
    name = provider_name.lower()
    if name not in PROVIDER_CAPABILITIES:
        raise HTTPException(status_code=404, detail=f"不支持的数据源: {name}")
    started = time.time()
    try:
        provider = get_provider(name)
        if hasattr(provider, "test_connection"):
            result = provider.test_connection()
        elif name == "tushare":
            frame = provider.fetch_trade_calendar("2024-01-01", "2024-01-10")
            result = {"success": not frame.empty, "message": "Tushare 连接正常", "rows": len(frame)}
        else:
            result = {"success": True, "message": "AKShare 已安装；实际可用性取决于目标公开页面"}
        result["elapsed"] = round(time.time() - started, 2)
        return result
    except Exception as exc:
        clear_provider_cache(name)
        return {
            "success": False,
            "message": "连接失败",
            "error": str(exc)[:500],
            "elapsed": round(time.time() - started, 2),
        }


@router.post("/jobs")
async def create_data_job(request: DataJobRequest):
    provider = (request.provider or load_data_config()["provider"]).lower()
    try:
        return job_manager.start_job(
            provider,
            request.job_type,
            request.start_date,
            request.end_date,
            request.codes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs")
async def list_data_jobs(limit: int = 30):
    return {"jobs": job_manager.list_jobs(limit)}


@router.get("/jobs/{job_id}")
async def get_data_job(job_id: str):
    try:
        return job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel_data_job(job_id: str):
    try:
        return job_manager.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.get("/{source_id}")
async def get_datasource(source_id: str):
    """Get detail for a specific data source."""
    if source_id not in _SOURCE_MAP:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Data source not found: {source_id}")
    return _SOURCE_MAP[source_id]
