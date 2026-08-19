"""
数据提供者抽象层

定义 DataProvider 协议，解耦数据获取与具体数据源。
不同数据源 (Tushare, AKShare, Wind, CSV) 只需实现此协议即可接入。

用法:
    from src.data.provider import get_provider
    provider = get_provider()           # 默认 baostock
    provider = get_provider("tushare")  # 指定

环境变量:
    DATA_PROVIDER   默认数据源名称 (默认 "baostock")
    TUSHARE_TOKEN   Tushare Pro API token
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderCapabilities:
    """Stable, UI-friendly description of a provider's data boundary."""

    name: str
    label: str
    description: str
    access_mode: str
    requires_token: bool
    supports_download: bool
    supports_history: bool
    supports_instant_analysis: bool
    datasets: Tuple[str, ...]
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


PROVIDER_CAPABILITIES: Dict[str, ProviderCapabilities] = {
    "baostock": ProviderCapabilities(
        name="baostock",
        label="BaoStock",
        description="免费 A 股行情与基础估值数据源，适合价格、技术和有限估值因子研究。",
        access_mode="免费",
        requires_token=False,
        supports_download=True,
        supports_history=True,
        supports_instant_analysis=False,
        datasets=("股票列表", "交易日历", "日线行情", "复权因子", "估值指标", "季度财务指标", "分红"),
        limitations=(
            "财务数据为季度比率集，不是完整三大报表",
            "缺少总市值、日股息率、报告修订和治理类数据",
            "不作为完整基本面因子研究口径",
            "不提供新闻、资金流等即时资讯",
        ),
    ),
    "tushare": ProviderCapabilities(
        name="tushare",
        label="Tushare Pro",
        description="可独立构成完整投研基线的订阅数据源，权限范围由账号积分和套餐决定。",
        access_mode="Token / 订阅",
        requires_token=True,
        supports_download=True,
        supports_history=True,
        supports_instant_analysis=False,
        datasets=("股票列表", "交易日历", "日线行情", "复权因子", "每日指标", "完整财报", "股东治理", "分红"),
        limitations=("部分核心接口需要付费权限",),
    ),
    "akshare": ProviderCapabilities(
        name="akshare",
        label="AKShare",
        description="无需订阅的即时分析数据源；独立使用，不参与历史数据库跨源补齐。",
        access_mode="免费",
        requires_token=False,
        supports_download=False,
        supports_history=False,
        supports_instant_analysis=True,
        datasets=("即时行情", "公开财务页面", "新闻", "资金流", "行业与指数"),
        limitations=("网页来源字段和可用性可能变化", "不作为严格历史回测基线"),
    ),
}


# ==================== 协议定义 ====================

@runtime_checkable
class DataProvider(Protocol):
    """数据提供者协议

    所有方法返回标准化 DataFrame，列名使用统一约定:
    - 日期列: trade_date, ann_date, end_date (格式 YYYY-MM-DD)
    - 代码列: ts_code (格式 600000.SH / 000001.SZ)
    """

    @property
    def name(self) -> str:
        """提供者名称"""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """数据能力边界。"""
        ...

    # ---------- 基础数据 ----------

    def fetch_stock_list(self) -> pd.DataFrame:
        """股票列表

        必须包含: ts_code, name, industry, list_status, list_date
        """
        ...

    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """交易日历

        必须包含: cal_date, is_open
        """
        ...

    # ---------- 日线数据 (批量) ----------

    def fetch_daily_bulk(self, trade_date: str) -> pd.DataFrame:
        """批量获取某一交易日全市场日线行情

        Args:
            trade_date: 交易日 YYYY-MM-DD

        Returns:
            必须包含: ts_code, trade_date, open, high, low, close, volume, amount
        """
        ...

    def fetch_adj_factor_bulk(self, trade_date: str) -> pd.DataFrame:
        """批量获取某一交易日全市场复权因子

        Args:
            trade_date: 交易日 YYYY-MM-DD

        Returns:
            必须包含: ts_code, trade_date, adj_factor
        """
        ...

    def fetch_daily_indicator_bulk(self, trade_date: str) -> pd.DataFrame:
        """批量获取某一交易日全市场估值指标

        Args:
            trade_date: 交易日 YYYY-MM-DD

        Returns:
            必须包含 ts_code、trade_date；其余字段以 native_fields.yaml 中该
            Provider 的精确绑定为准，不要求 BaoStock 伪装成 Tushare 字段集。
        """
        ...

    # ---------- 财报数据 (按股票) ----------

    def fetch_balancesheet(self, ts_code: str) -> pd.DataFrame:
        """资产负债表 (全历史)

        必须包含: ts_code, ann_date, end_date, report_type
        """
        ...

    def fetch_income(self, ts_code: str) -> pd.DataFrame:
        """利润表 (全历史)"""
        ...

    def fetch_cashflow(self, ts_code: str) -> pd.DataFrame:
        """现金流量表 (全历史)"""
        ...

    def fetch_financial_indicator(self, ts_code: str) -> pd.DataFrame:
        """财务指标 (ROE/毛利率等)"""
        ...

    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        """分红数据"""
        ...

    def fetch_dividends_by_announcement(self, ann_date: str) -> pd.DataFrame:
        """指定公告日的全市场分红数据（Provider 支持时）。"""
        ...

    def fetch_top10_holders(self, ts_code: str) -> pd.DataFrame:
        """前十大股东"""
        ...

    def fetch_top10_floatholders(self, ts_code: str) -> pd.DataFrame:
        """前十大流通股东"""
        ...

    def fetch_pledge_stat(self, ts_code: str) -> pd.DataFrame:
        """股权质押统计"""
        ...

    def fetch_pledge_detail(self, ts_code: str) -> pd.DataFrame:
        """股权质押明细"""
        ...

    def fetch_fina_audit(self, ts_code: str) -> pd.DataFrame:
        """审计意见"""
        ...

    def fetch_fina_mainbz(self, ts_code: str) -> pd.DataFrame:
        """主营业务构成"""
        ...

    def fetch_stk_holdernumber(self, ts_code: str) -> pd.DataFrame:
        """股东人数"""
        ...

    def fetch_stk_holdertrade(self, ts_code: str) -> pd.DataFrame:
        """股东增减持"""
        ...

    def fetch_share_float(self, ts_code: str) -> pd.DataFrame:
        """限售解禁"""
        ...

    def fetch_repurchase(self, ts_code: str) -> pd.DataFrame:
        """股票回购"""
        ...

    def fetch_disclosure_date(self, end_date: Optional[str] = None) -> pd.DataFrame:
        """财报披露日期 (全市场)"""
        ...

    # ---------- 财报数据 (按报告期截面, 全市场) ----------

    def fetch_income_by_period(self, period: str) -> pd.DataFrame:
        """利润表 — 按报告期截面获取全市场

        Args:
            period: 报告期 YYYY-MM-DD (如 2024-12-31)
        """
        ...

    def fetch_balancesheet_by_period(self, period: str) -> pd.DataFrame:
        """资产负债表 — 按报告期截面获取全市场"""
        ...

    def fetch_cashflow_by_period(self, period: str) -> pd.DataFrame:
        """现金流量表 — 按报告期截面获取全市场"""
        ...

    def fetch_fina_indicator_by_period(self, period: str) -> pd.DataFrame:
        """财务指标 — 按报告期截面获取全市场"""
        ...


# ==================== 提供者注册表 ====================

_registry: Dict[str, DataProvider] = {}
_default_name: Optional[str] = None
_registry_lock = RLock()


def register(name: str, provider: DataProvider) -> None:
    """注册数据提供者"""
    normalized = name.lower()
    with _registry_lock:
        _registry[normalized] = provider
    logger.info(f"数据提供者已注册: {normalized}")


def get_provider(name: str = None) -> DataProvider:
    """获取数据提供者

    Args:
        name: 提供者名称，None 使用默认

    Returns:
        DataProvider 实例
    """
    if name:
        target = name.lower()
    elif _default_name:
        target = _default_name
    else:
        from .config import get_active_provider_name

        target = get_active_provider_name()

    if target == "crawler":
        target = "akshare"

    with _registry_lock:
        if target not in _registry:
            # 延迟加载: 首次访问时自动注册。同一进程内按数据源复用实例。
            if target == "tushare":
                from .tushare import TushareProvider

                register("tushare", TushareProvider())
            elif target == "baostock":
                from .baostock import BaoStockProvider

                register("baostock", BaoStockProvider())
            elif target == "akshare":
                from .crawler import CrawlerProvider

                register("akshare", CrawlerProvider())
            else:
                raise ValueError(f"未知数据提供者: {target}，已注册: {list(_registry.keys())}")

        return _registry[target]


def set_default(name: str) -> None:
    """设置默认数据提供者"""
    global _default_name
    target = "akshare" if name.lower() == "crawler" else name.lower()
    if target not in PROVIDER_CAPABILITIES:
        raise ValueError(f"未知数据提供者: {name}")
    _default_name = target
def list_providers() -> List[str]:
    """列出所有可配置的提供者，而不仅是已经实例化的提供者。"""
    return list(PROVIDER_CAPABILITIES.keys())


def get_provider_capabilities(name: str) -> ProviderCapabilities:
    target = "akshare" if name == "crawler" else name.lower()
    try:
        return PROVIDER_CAPABILITIES[target]
    except KeyError as exc:
        raise ValueError(f"未知数据提供者: {name}") from exc


def clear_provider_cache(name: Optional[str] = None) -> None:
    """Close and evict providers after credential changes or connection failures."""
    with _registry_lock:
        if name is None:
            providers = list(_registry.items())
            _registry.clear()
        else:
            target = "akshare" if name.lower() == "crawler" else name.lower()
            provider = _registry.pop(target, None)
            providers = [(target, provider)] if provider is not None else []

    for provider_name, provider in providers:
        closer = getattr(provider, "close", None)
        if closer:
            try:
                closer()
            except Exception as exc:
                logger.warning("关闭数据提供者 %s 失败: %s", provider_name, exc)
