"""
Data sources registry — describes all available data for operator analysis.
"""
from fastapi import APIRouter

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
    grouped = {}
    for cat in _CATEGORIES:
        grouped[cat] = [s for s in DATA_SOURCES if s["category"] == cat]
    return {
        "categories": _CATEGORIES,
        "sources": grouped,
        "total": len(DATA_SOURCES),
        "all": DATA_SOURCES,
    }


@router.get("/{source_id}")
async def get_datasource(source_id: str):
    """Get detail for a specific data source."""
    if source_id not in _SOURCE_MAP:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Data source not found: {source_id}")
    return _SOURCE_MAP[source_id]
