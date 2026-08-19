"""BaoStock adapter with normalized A-share history and financial metrics."""
from __future__ import annotations

import logging
from datetime import datetime
from threading import RLock
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

from ..config import get_data_start_date
from ..provider import PROVIDER_CAPABILITIES, ProviderCapabilities

logger = logging.getLogger(__name__)

_DAILY_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
    "tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)
_DATE_COLUMNS = {
    "date",
    "pubDate",
    "statDate",
    "ipoDate",
    "outDate",
    "dividPreNoticeDate",
    "dividAgmPumDate",
    "dividPlanAnnounceDate",
    "dividPlanDate",
    "dividRegistDate",
    "dividOperateDate",
    "dividPayDate",
    "dividStockMarketDate",
}


def _to_bs_code(ts_code: str) -> str:
    code, market = ts_code.upper().split(".")
    return f"{market.lower()}.{code}"


def _to_ts_code(code: str) -> str:
    market, number = str(code).split(".")
    return f"{number}.{market.upper()}"


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize empty cells, dates and numeric result columns."""
    if df.empty:
        return df
    result = df.copy()
    result = result.replace("", pd.NA)
    for column in result.columns:
        if column in _DATE_COLUMNS:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.strftime("%Y-%m-%d")
        elif column not in {"code", "code_name", "type", "status", "tradeStatus", "adjustflag", "isST"}:
            converted = pd.to_numeric(result[column], errors="coerce")
            if converted.notna().any():
                result[column] = converted
    return result


def _concat_frames_preserving_columns(frames: List[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate provider frames without Pandas' all-NA dtype ambiguity.

    BaoStock returns a stable field list even when a field has no value for a
    particular quarter or year.  All-NA columns are excluded only while Pandas
    resolves dtypes, then restored so the provider schema remains stable.
    """
    nonempty = [frame for frame in frames if frame is not None and not frame.empty]
    if not nonempty:
        return pd.DataFrame()

    columns = list(dict.fromkeys(column for frame in nonempty for column in frame.columns))
    meaningful = [frame.dropna(axis="columns", how="all") for frame in nonempty]
    meaningful = [frame for frame in meaningful if not frame.empty]
    if not meaningful:
        return pd.DataFrame(columns=columns)

    result = pd.concat(meaningful, ignore_index=True, sort=False)
    return result.reindex(columns=columns)


class BaoStockProvider:
    """Free BaoStock provider.

    BaoStock keeps a process-global socket session, so calls are serialized.  The
    provider exposes both range-oriented history and full-market daily snapshots
    so ``DataUpdater`` can choose the efficient path for each phase.
    """

    def __init__(self):
        try:
            import baostock as bs
        except ImportError as exc:
            raise ImportError("BaoStockProvider 需要 baostock，请运行 uv sync") from exc
        self._bs = bs
        self._lock = RLock()
        self._logged_in = False

    @property
    def name(self) -> str:
        return "baostock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return PROVIDER_CAPABILITIES["baostock"]

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        result = self._bs.login()
        if result.error_code != "0":
            raise RuntimeError(f"BaoStock 登录失败: {result.error_msg}")
        self._logged_in = True

    def close(self) -> None:
        with self._lock:
            if self._logged_in:
                self._bs.logout()
                self._logged_in = False

    def _collect(self, query: Callable[[], object]) -> pd.DataFrame:
        with self._lock:
            self._ensure_login()
            result = query()
            if result.error_code != "0":
                # Re-login on an expired connection before surfacing the error.
                self._logged_in = False
                raise RuntimeError(f"BaoStock 查询失败: {result.error_msg}")
            rows: List[List[str]] = []
            while result.next():
                rows.append(result.get_row_data())
            return _clean_frame(pd.DataFrame(rows, columns=result.fields))

    def test_connection(self) -> Dict[str, object]:
        frame = self._collect(lambda: self._bs.query_stock_basic(code="sh.600000"))
        return {"success": not frame.empty, "message": "BaoStock 连接正常", "rows": len(frame)}

    # ---------- Basic data ----------

    def fetch_stock_list(self) -> pd.DataFrame:
        basic = self._collect(lambda: self._bs.query_stock_basic())
        if basic.empty:
            return basic
        basic = basic[(basic["type"].astype(str) == "1") & basic["code"].str.match(r"^(sh|sz)\.")]

        industry = self._collect(lambda: self._bs.query_stock_industry())
        if not industry.empty:
            basic = basic.merge(industry[["code", "industry"]], on="code", how="left")
        else:
            basic["industry"] = ""

        basic["ts_code"] = basic["code"].map(_to_ts_code)
        basic["symbol"] = basic["ts_code"].str[:6]
        basic["name"] = basic["code_name"]
        basic["list_date"] = basic["ipoDate"]
        basic["delist_date"] = basic["outDate"]
        basic["list_status"] = basic["status"].map(lambda value: "L" if str(value) == "1" else "D")
        basic["area"] = ""
        basic["market"] = basic["ts_code"].str[-2:]
        return basic[
            ["ts_code", "symbol", "name", "area", "industry", "market", "list_status", "list_date", "delist_date"]
        ].reset_index(drop=True)

    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        frame = self._collect(lambda: self._bs.query_trade_dates(start_date, end_date))
        if frame.empty:
            return frame
        frame = frame.rename(columns={"calendar_date": "cal_date", "is_trading_day": "is_open"})
        frame["is_open"] = pd.to_numeric(frame["is_open"], errors="coerce").fillna(0).astype(int)
        return frame[["cal_date", "is_open"]]

    # ---------- Daily history ----------

    @staticmethod
    def _split_daily_history(history: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        if history.empty:
            return pd.DataFrame(), pd.DataFrame()
        history = history.rename(
            columns={
                "turn": "turnover_rate",
                "tradestatus": "trade_status",
                "pctChg": "pct_chg",
                "peTTM": "pe_ttm",
                "pbMRQ": "pb",
                "psTTM": "ps_ttm",
                "pcfNcfTTM": "pcf_ncf_ttm",
                "isST": "is_st",
            }
        )
        raw_columns = [
            "ts_code", "trade_date", "open", "high", "low", "close", "preclose",
            "volume", "amount", "pct_chg", "turnover_rate", "trade_status", "is_st",
        ]
        indicator_columns = [
            "ts_code", "trade_date", "turnover_rate", "pe_ttm", "pb", "ps_ttm", "pcf_ncf_ttm",
        ]
        return history[raw_columns].copy(), history[indicator_columns].copy()

    def _fetch_daily_market_snapshot(
        self,
        trade_date: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        history = self._collect(lambda: self._bs.query_daily_history_k_AStock(trade_date))
        if history.empty:
            return pd.DataFrame(), pd.DataFrame()
        if "adjustflag" in history.columns:
            flags = set(history["adjustflag"].dropna().astype(str))
            if flags and flags != {"3"}:
                raise RuntimeError(f"BaoStock 全市场日线不是不复权口径: {sorted(flags)}")
        history = history[history["code"].astype(str).str.match(r"^(sh|sz)\.")].copy()
        history["ts_code"] = history["code"].map(_to_ts_code)
        history["trade_date"] = history["date"]
        return self._split_daily_history(history)

    def _fetch_daily_factor_snapshot(self, trade_date: str) -> pd.DataFrame:
        factors = self._collect(lambda: self._bs.query_daily_adjust_factor(trade_date))
        if factors.empty:
            return factors
        factors = factors[factors["code"].astype(str).str.match(r"^(sh|sz)\.")].copy()
        factors["ts_code"] = factors["code"].map(_to_ts_code)
        factors["trade_date"] = trade_date
        factors = factors.rename(columns={"adjustFactor": "adj_factor"})
        factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
        return factors[["ts_code", "trade_date", "adj_factor"]].dropna(subset=["adj_factor"])

    def fetch_daily_snapshot(self, trade_date: str) -> Dict[str, pd.DataFrame]:
        """Fetch one unadjusted full-market day plus factors in two API calls."""
        raw, indicator = self._fetch_daily_market_snapshot(trade_date)
        factors = self._fetch_daily_factor_snapshot(trade_date)
        return {"raw": raw, "adj_factor": factors, "indicator": indicator}

    def fetch_daily_bundle(self, ts_code: str, start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        code = _to_bs_code(ts_code)
        history = self._collect(
            lambda: self._bs.query_history_k_data_plus(
                code,
                _DAILY_FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3",
            )
        )
        if history.empty:
            empty = pd.DataFrame()
            return {"raw": empty, "adj_factor": empty, "indicator": empty}

        history["ts_code"] = ts_code
        history["trade_date"] = history["date"]
        raw, indicator = self._split_daily_history(history)

        # Include the latest corporate-action factor before ``start_date`` so an
        # incremental segment never restarts at an incorrect factor of 1.0.
        factors = self.fetch_adj_factor_range(ts_code, "1990-01-01", end_date)
        if factors.empty:
            factors = history[["ts_code", "trade_date"]].copy()
            factors["adj_factor"] = 1.0
        else:
            calendar = raw[["ts_code", "trade_date"]].sort_values("trade_date")
            calendar["trade_date"] = pd.to_datetime(calendar["trade_date"], errors="coerce")
            factors["trade_date"] = pd.to_datetime(factors["trade_date"], errors="coerce")
            factors = pd.merge_asof(
                calendar,
                factors.sort_values("trade_date"),
                on="trade_date",
                by="ts_code",
                direction="backward",
            )
            factors["adj_factor"] = factors["adj_factor"].ffill().fillna(1.0)
            factors["trade_date"] = factors["trade_date"].dt.strftime("%Y-%m-%d")
        return {"raw": raw, "adj_factor": factors, "indicator": indicator}

    def fetch_daily_range(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.fetch_daily_bundle(ts_code, start_date, end_date)["raw"]

    def fetch_index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = self.fetch_daily_range(ts_code, start_date, end_date)
        columns = ["ts_code", "trade_date", "close", "open", "high", "low", "pct_chg"]
        return frame[[column for column in columns if column in frame.columns]]

    def fetch_adj_factor_range(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        code = _to_bs_code(ts_code)
        frame = self._collect(lambda: self._bs.query_adjust_factor(code, start_date, end_date))
        if frame.empty:
            return frame
        frame["ts_code"] = ts_code
        frame["trade_date"] = frame["dividOperateDate"]
        frame = frame.rename(columns={"adjustFactor": "adj_factor"})
        frame["adj_factor"] = pd.to_numeric(frame["adj_factor"], errors="coerce")
        return frame[["ts_code", "trade_date", "adj_factor"]].dropna(subset=["trade_date", "adj_factor"])

    def fetch_daily_bulk(self, trade_date: str) -> pd.DataFrame:
        return self._fetch_daily_market_snapshot(trade_date)[0]

    def fetch_adj_factor_bulk(self, trade_date: str) -> pd.DataFrame:
        return self._fetch_daily_factor_snapshot(trade_date)

    def fetch_daily_indicator_bulk(self, trade_date: str) -> pd.DataFrame:
        return self._fetch_daily_market_snapshot(trade_date)[1]

    # ---------- Quarterly financial metrics ----------

    @staticmethod
    def _quarters(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Iterable[tuple]:
        start = pd.to_datetime(start_date or get_data_start_date()).normalize()
        today = pd.Timestamp(datetime.now().date())
        end = min(pd.to_datetime(end_date).normalize(), today) if end_date else today
        if start > end:
            return
        for year in range(start.year, end.year + 1):
            for quarter in range(1, 5):
                quarter_end = pd.Timestamp(year=year, month=quarter * 3, day=1)
                quarter_end += pd.offsets.MonthEnd(1)
                if quarter_end < start:
                    continue
                if quarter_end > end:
                    break
                yield year, quarter

    def _fetch_quarterly(
        self,
        ts_code: str,
        function_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        code = _to_bs_code(ts_code)
        frames = []
        function = getattr(self._bs, function_name)
        for year, quarter in self._quarters(start_date, end_date):
            frame = self._collect(lambda y=year, q=quarter: function(code, y, q))
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        result = _concat_frames_preserving_columns(frames)
        result["ts_code"] = ts_code
        result["ann_date"] = result["pubDate"]
        result["end_date"] = result["statDate"]
        result["report_type"] = "1"
        return result

    @staticmethod
    def _rename_financial(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.rename(
            columns={
                "roeAvg": "roe",
                "npMargin": "netprofit_margin",
                "gpMargin": "grossprofit_margin",
                "netProfit": "net_profit",
                "epsTTM": "eps",
                "MBRevenue": "revenue",
                "totalShare": "total_share",
                "liqaShare": "float_share",
                "NRTurnRatio": "ar_turn",
                "INVTurnRatio": "inv_turn",
                "CATurnRatio": "current_asset_turn",
                "AssetTurnRatio": "assets_turn",
                "YOYEquity": "equity_yoy",
                "YOYAsset": "assets_yoy",
                "YOYNI": "net_profit_yoy",
                "YOYEPSBasic": "eps_yoy",
                "YOYPNI": "profit_yoy",
                "currentRatio": "current_ratio",
                "quickRatio": "quick_ratio",
                "cashRatio": "cash_ratio",
                "YOYLiability": "liabilities_yoy",
                "liabilityToAsset": "debt_to_assets",
                "assetToEquity": "assets_to_equity",
                "CFOToOR": "ocf_to_revenue",
                "CFOToNP": "ocf_to_net_profit",
                "CFOToGr": "ocf_to_gross_profit",
                "dupontROE": "dupont_roe",
            }
        )

    def fetch_financial_bundle(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, pd.DataFrame]:
        profit = self._rename_financial(
            self._fetch_quarterly(ts_code, "query_profit_data", start_date, end_date)
        )
        operation = self._rename_financial(
            self._fetch_quarterly(ts_code, "query_operation_data", start_date, end_date)
        )
        growth = self._rename_financial(
            self._fetch_quarterly(ts_code, "query_growth_data", start_date, end_date)
        )
        balance = self._rename_financial(
            self._fetch_quarterly(ts_code, "query_balance_data", start_date, end_date)
        )
        cashflow = self._rename_financial(
            self._fetch_quarterly(ts_code, "query_cash_flow_data", start_date, end_date)
        )
        dupont = self._rename_financial(
            self._fetch_quarterly(ts_code, "query_dupont_data", start_date, end_date)
        )

        keys = ["ts_code", "ann_date", "end_date", "report_type"]
        indicator = pd.DataFrame()
        for frame in (profit, operation, growth, balance, cashflow, dupont):
            if frame.empty:
                continue
            keep = [column for column in frame.columns if column not in {"code", "pubDate", "statDate"}]
            current = frame[keep].drop_duplicates(keys, keep="last")
            indicator = current if indicator.empty else indicator.merge(current, on=keys, how="outer")
        return {
            "income": profit,
            "balancesheet": balance,
            "cashflow": cashflow,
            "fina_indicator": indicator,
            "dividend": self.fetch_dividend(
                ts_code,
                start_date=start_date,
                end_date=end_date,
            ),
        }

    def fetch_income(self, ts_code: str) -> pd.DataFrame:
        return self._rename_financial(self._fetch_quarterly(ts_code, "query_profit_data"))

    def fetch_balancesheet(self, ts_code: str) -> pd.DataFrame:
        return self._rename_financial(self._fetch_quarterly(ts_code, "query_balance_data"))

    def fetch_cashflow(self, ts_code: str) -> pd.DataFrame:
        return self._rename_financial(self._fetch_quarterly(ts_code, "query_cash_flow_data"))

    def fetch_financial_indicator(self, ts_code: str) -> pd.DataFrame:
        return self.fetch_financial_bundle(ts_code)["fina_indicator"]

    def fetch_dividend(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        code = _to_bs_code(ts_code)
        frames = []
        start_year = int((start_date or get_data_start_date())[:4])
        end_year = min(
            int((end_date or str(datetime.now().year))[:4]),
            datetime.now().year,
        )
        for year in range(start_year, end_year + 1):
            frame = self._collect(lambda y=year: self._bs.query_dividend_data(code, str(y), "report"))
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        result = _concat_frames_preserving_columns(frames)
        result["ts_code"] = ts_code
        result = result.rename(
            columns={
                "dividPlanAnnounceDate": "ann_date",
                "dividOperateDate": "end_date",
                "dividRegistDate": "record_date",
                "dividPayDate": "pay_date",
                "dividCashPsBeforeTax": "cash_div",
                "dividCashPsAfterTax": "cash_div_after_tax",
                "dividStocksPs": "stk_div",
            }
        )
        return result

    # BaoStock does not expose these datasets.  Returning an empty frame makes
    # the absence explicit without mixing in another provider.
    def fetch_top10_holders(self, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame()

    fetch_top10_floatholders = fetch_top10_holders
    fetch_pledge_stat = fetch_top10_holders
    fetch_pledge_detail = fetch_top10_holders
    fetch_fina_audit = fetch_top10_holders
    fetch_fina_mainbz = fetch_top10_holders
    fetch_stk_holdernumber = fetch_top10_holders
    fetch_stk_holdertrade = fetch_top10_holders
    fetch_share_float = fetch_top10_holders
    fetch_repurchase = fetch_top10_holders

    def fetch_disclosure_date(self, end_date: Optional[str] = None) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_income_by_period(self, period: str) -> pd.DataFrame:
        return pd.DataFrame()

    fetch_balancesheet_by_period = fetch_income_by_period
    fetch_cashflow_by_period = fetch_income_by_period
    fetch_fina_indicator_by_period = fetch_income_by_period
