"""
Tushare 数据提供者

将 tushare API 包装为 DataProvider 协议实现。
处理 API 限流、日期格式转换、分页等 Tushare 特有逻辑。
"""
import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import tushare as ts

from ..config import get_tushare_token
from ..provider import PROVIDER_CAPABILITIES, ProviderCapabilities

logger = logging.getLogger(__name__)

# API 调用间隔 (秒)
_API_SLEEP = 0.3
_PAGE_SIZE = 5000


def _fmt(date: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return date.replace('-', '') if date else ''


def _format_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """格式化日期列为 YYYY-MM-DD"""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
    return df


def _align_indicator_to_quotes(
    raw: pd.DataFrame,
    indicator: pd.DataFrame,
) -> pd.DataFrame:
    """Align daily_basic to the tradable universe returned by daily.

    Tushare can legitimately return different stock sets for ``daily`` and
    ``daily_basic``.  Quotes define the canonical backtest universe; missing
    valuation fields remain null instead of making the atomic day fail.
    """
    if raw.empty or indicator.empty:
        return indicator
    keys = ["ts_code", "trade_date"]
    quote_keys = raw[keys].drop_duplicates(keys, keep="last")
    indicator = indicator.drop_duplicates(keys, keep="last")
    quote_index = set(quote_keys.itertuples(index=False, name=None))
    indicator_index = set(indicator[keys].itertuples(index=False, name=None))
    if not quote_index.intersection(indicator_index):
        raise RuntimeError("Tushare 日线行情与每日指标没有可对齐的股票记录")
    missing = len(quote_index - indicator_index)
    extra = len(indicator_index - quote_index)
    if missing or extra:
        logger.info(
            "Tushare 日线与每日指标集合存在差异：行情缺指标 %s 条，指标无行情 %s 条",
            missing,
            extra,
        )
    return quote_keys.merge(indicator, on=keys, how="left", validate="one_to_one")
class TushareProvider:
    """Tushare 数据提供者"""

    def __init__(self, token: str = None):
        token = token or get_tushare_token()
        if not token:
            raise ValueError("TUSHARE_TOKEN 未设置，请在 .env 或环境变量中配置")
        # Pass the token directly. ``ts.set_token`` writes ``tk.csv`` to the
        # user's home directory, which is unnecessary for an application-owned
        # credential and can fail in packaged/sandboxed desktop environments.
        self._pro = ts.pro_api(token)

    @property
    def name(self) -> str:
        return "tushare"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return PROVIDER_CAPABILITIES["tushare"]

    def _fetch_paged(
        self,
        endpoint_name: str,
        page_size: int = _PAGE_SIZE,
        **params,
    ) -> pd.DataFrame:
        """Fetch every page and fail if an endpoint silently ignores offsets."""
        endpoint = getattr(self._pro, endpoint_name)
        frames: List[pd.DataFrame] = []
        offset = 0
        previous_signature = None
        for _ in range(1000):
            frame = endpoint(limit=page_size, offset=offset, **params)
            time.sleep(_API_SLEEP)
            if frame is None or frame.empty:
                break
            frame = frame.copy()
            signature = (
                len(frame),
                tuple(str(value) for value in frame.iloc[0].tolist()[:4]),
                tuple(str(value) for value in frame.iloc[-1].tolist()[:4]),
            )
            if offset and signature == previous_signature:
                raise RuntimeError(f"Tushare {endpoint_name} 未正确响应 offset={offset}")
            frames.append(frame)
            if len(frame) < page_size:
                break
            previous_signature = signature
            offset += len(frame)
        else:
            raise RuntimeError(f"Tushare {endpoint_name} 分页超过安全上限")
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ---------- 基础数据 ----------

    def fetch_stock_list(self) -> pd.DataFrame:
        df = self._fetch_paged(
            "stock_basic",
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry,market,list_status,list_date,delist_date,is_hs',
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'list_date')
        df = _format_date_col(df, 'delist_date')

        # 也获取退市的
        df_d = self._fetch_paged(
            "stock_basic",
            exchange='', list_status='D',
            fields='ts_code,symbol,name,area,industry,market,list_status,list_date,delist_date,is_hs',
        )
        if df_d is not None and not df_d.empty:
            df_d = _format_date_col(df_d, 'list_date')
            df_d = _format_date_col(df_d, 'delist_date')
            df = pd.concat([df, df_d], ignore_index=True)

        return df

    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._fetch_paged(
            "trade_cal",
            exchange='SSE',
            start_date=_fmt(start_date),
            end_date=_fmt(end_date),
            fields='cal_date,is_open,pretrade_date',
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'cal_date')
        df = _format_date_col(df, 'pretrade_date')
        return df

    # ---------- 日线数据 (按交易日批量) ----------

    def fetch_daily_bulk(self, trade_date: str) -> pd.DataFrame:
        """获取单个交易日全市场日线行情"""
        df = self._fetch_paged("daily", trade_date=_fmt(trade_date))
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={'vol': 'volume'})
        df = _format_date_col(df, 'trade_date')
        return df

    def fetch_adj_factor_bulk(self, trade_date: str) -> pd.DataFrame:
        """获取单个交易日全市场复权因子"""
        df = self._fetch_paged("adj_factor", trade_date=_fmt(trade_date))
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'trade_date')
        return df[['ts_code', 'trade_date', 'adj_factor']]

    def fetch_daily_indicator_bulk(self, trade_date: str) -> pd.DataFrame:
        """获取单个交易日全市场估值指标"""
        df = self._fetch_paged("daily_basic", trade_date=_fmt(trade_date))
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'trade_date')
        return df

    def fetch_daily_snapshot(self, trade_date: str) -> Dict[str, pd.DataFrame]:
        """Fetch all datasets required for one atomic trading-day commit."""
        raw = self.fetch_daily_bulk(trade_date)
        indicator = self.fetch_daily_indicator_bulk(trade_date)
        if not raw.empty and not indicator.empty:
            indicator = _align_indicator_to_quotes(raw, indicator)
        return {
            "raw": raw,
            "adj_factor": self.fetch_adj_factor_bulk(trade_date),
            "indicator": indicator,
        }

    # ---------- 指数日线 ----------

    def fetch_index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指数日线行情 (如 000300.SH 沪深300, 000905.SH 中证500)"""
        df = self._fetch_paged(
            "index_daily",
            ts_code=ts_code,
            start_date=_fmt(start_date),
            end_date=_fmt(end_date),
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'trade_date')
        return df[['ts_code', 'trade_date', 'close', 'open', 'high', 'low', 'pct_chg']]

    # ---------- 财报数据 (按股票) ----------

    def fetch_balancesheet(self, ts_code: str) -> pd.DataFrame:
        df = self._fetch_paged("balancesheet_vip", ts_code=ts_code, report_type='1')
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'f_ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_income(self, ts_code: str) -> pd.DataFrame:
        df = self._fetch_paged("income_vip", ts_code=ts_code, report_type='1')
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'f_ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_cashflow(self, ts_code: str) -> pd.DataFrame:
        df = self._fetch_paged("cashflow_vip", ts_code=ts_code, report_type='1')
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'f_ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_financial_indicator(self, ts_code: str) -> pd.DataFrame:
        df = self._fetch_paged("fina_indicator_vip", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        df = self._fetch_paged(
            "dividend",
            ts_code=ts_code,
            fields=(
                'ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,'
                'cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,'
                'imp_ann_date,base_date,base_share'
            ),
        )
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date', 'record_date', 'ex_date', 'pay_date',
                     'div_listdate', 'imp_ann_date', 'base_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_dividends_by_announcement(self, ann_date: str) -> pd.DataFrame:
        """Fetch all dividend records announced on one date.

        Tushare's dividend endpoint accepts an announcement date without a
        stock code.  This path is used only after the per-stock history
        baseline exists, so routine incremental updates do not rescan every
        security.
        """
        df = self._fetch_paged(
            "dividend",
            ann_date=_fmt(ann_date),
            fields=(
                'ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,'
                'cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,'
                'imp_ann_date,base_date,base_share'
            ),
        )
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date', 'record_date', 'ex_date', 'pay_date',
                    'div_listdate', 'imp_ann_date', 'base_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_top10_holders(self, ts_code: str) -> pd.DataFrame:
        df = self._fetch_paged("top10_holders", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_top10_floatholders(self, ts_code: str) -> pd.DataFrame:
        """十大流通股东"""
        df = self._fetch_paged("top10_floatholders", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_pledge_stat(self, ts_code: str) -> pd.DataFrame:
        """股权质押统计"""
        df = self._fetch_paged("pledge_stat", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'end_date')
        return df

    def fetch_pledge_detail(self, ts_code: str) -> pd.DataFrame:
        """股权质押明细"""
        df = self._fetch_paged("pledge_detail", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'pledge_start_date', 'pledge_end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_fina_audit(self, ts_code: str) -> pd.DataFrame:
        """审计意见"""
        df = self._fetch_paged("fina_audit_vip", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_fina_mainbz(self, ts_code: str) -> pd.DataFrame:
        """主营业务构成 (按产品 + 按地区)"""
        df = self._fetch_paged("fina_mainbz_vip", ts_code=ts_code, type='P')
        if df is None or df.empty:
            df = pd.DataFrame()
        else:
            df = _format_date_col(df, 'end_date')
        # 也获取按地区
        df_area = self._fetch_paged("fina_mainbz_vip", ts_code=ts_code, type='D')
        if df_area is not None and not df_area.empty:
            df_area = _format_date_col(df_area, 'end_date')
            df_area['bz_item'] = '[地区]' + df_area['bz_item'].astype(str)
            if df.empty:
                df = df_area
            else:
                df = pd.concat([df, df_area], ignore_index=True)
        return df

    def fetch_stk_holdernumber(self, ts_code: str) -> pd.DataFrame:
        """股东人数"""
        df = self._fetch_paged("stk_holdernumber", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_stk_holdertrade(self, ts_code: str) -> pd.DataFrame:
        """股东增减持"""
        df = self._fetch_paged("stk_holdertrade", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'ann_date')
        return df

    def fetch_share_float(self, ts_code: str) -> pd.DataFrame:
        """限售解禁"""
        df = self._fetch_paged("share_float", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'float_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_repurchase(self, ts_code: str) -> pd.DataFrame:
        """股票回购"""
        df = self._fetch_paged("repurchase", ts_code=ts_code)
        if df is None or df.empty:
            return pd.DataFrame()
        df = _format_date_col(df, 'ann_date')
        return df

    # ---------- 财报数据 (按报告期截面, 全市场) ----------

    def fetch_income_by_period(self, period: str) -> pd.DataFrame:
        df = self._fetch_paged("income_vip", period=_fmt(period), report_type='1')
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'f_ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_balancesheet_by_period(self, period: str) -> pd.DataFrame:
        df = self._fetch_paged("balancesheet_vip", period=_fmt(period), report_type='1')
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'f_ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_cashflow_by_period(self, period: str) -> pd.DataFrame:
        df = self._fetch_paged("cashflow_vip", period=_fmt(period), report_type='1')
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'f_ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_fina_indicator_by_period(self, period: str) -> pd.DataFrame:
        df = self._fetch_paged("fina_indicator_vip", period=_fmt(period))
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date']:
            df = _format_date_col(df, col)
        return df

    def fetch_disclosure_date(self, end_date: Optional[str] = None) -> pd.DataFrame:
        params = {}
        if end_date:
            params['end_date'] = _fmt(end_date)
        df = self._fetch_paged("disclosure_date", **params)
        if df is None or df.empty:
            return pd.DataFrame()
        for col in ['ann_date', 'end_date', 'pre_date', 'actual_date', 'modify_date']:
            df = _format_date_col(df, col)
        return df
