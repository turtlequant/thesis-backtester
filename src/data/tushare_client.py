"""
Tushare 数据获取接口

包含行情数据和基本面数据获取
"""
from .settings import TUSHARE_TOKEN
import tushare as ts
import pandas as pd
from typing import Optional

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


# ==================== 行情数据 ====================

def fetch_stock_list(list_status: str = 'L') -> pd.DataFrame:
    """股票列表"""
    df = pro.stock_basic(
        exchange='',
        list_status=list_status,
        fields='ts_code,symbol,name,area,industry,market,list_status,list_date,delist_date,is_hs',
        limit=10000
    )
    if df is not None and not df.empty:
        df['list_date'] = pd.to_datetime(df['list_date']).dt.strftime('%Y-%m-%d')
        df['delist_date'] = pd.to_datetime(df['delist_date']).dt.strftime('%Y-%m-%d')
    return df if df is not None else pd.DataFrame()


def fetch_trade_calendar(start_date: str, end_date: str) -> pd.DataFrame:
    """交易日历"""
    df = pro.trade_cal(
        exchange='SSE',
        start_date=start_date.replace('-', ''),
        end_date=end_date.replace('-', ''),
        fields='cal_date,is_open,pretrade_date',
        limit=100000
    )
    if df is not None and not df.empty:
        df['cal_date'] = pd.to_datetime(df['cal_date']).dt.strftime('%Y-%m-%d')
        df['pretrade_date'] = pd.to_datetime(df['pretrade_date']).dt.strftime('%Y-%m-%d')
    return df if df is not None else pd.DataFrame()


def fetch_daily(
    trade_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """日线行情（不复权）"""
    params = {}
    if trade_date:
        params['trade_date'] = trade_date.replace('-', '')
    if ts_code:
        params['ts_code'] = ts_code
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.daily(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={'vol': 'volume'})
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
    return df


def fetch_adj_factor(
    trade_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """复权因子"""
    params = {}
    if trade_date:
        params['trade_date'] = trade_date.replace('-', '')
    if ts_code:
        params['ts_code'] = ts_code
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.adj_factor(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
    return pd.DataFrame(df[['trade_date', 'ts_code', 'adj_factor']])


def fetch_daily_indicator(
    trade_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """每日指标（PE/PB/换手率/市值等）"""
    params = {}
    if trade_date:
        params['trade_date'] = trade_date.replace('-', '')
    if ts_code:
        params['ts_code'] = ts_code
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.daily_basic(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
    return df


# ==================== 基本面数据（新增）====================

def _format_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """格式化日期列为 YYYY-MM-DD"""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
    return df


def fetch_balancesheet(
    ts_code: Optional[str] = None,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    report_type: str = '1',
) -> pd.DataFrame:
    """
    资产负债表

    Args:
        ts_code: 股票代码
        period: 报告期，如 '20231231'
        start_date/end_date: 公告日期范围
        report_type: '1'合并报表 '2'单季
    """
    params = {'report_type': report_type}
    if ts_code:
        params['ts_code'] = ts_code
    if period:
        params['period'] = period.replace('-', '')
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.balancesheet_vip(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df = _format_date_col(df, 'ann_date')
    df = _format_date_col(df, 'f_ann_date')
    df = _format_date_col(df, 'end_date')
    return df


def fetch_income(
    ts_code: Optional[str] = None,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    report_type: str = '1',
) -> pd.DataFrame:
    """利润表"""
    params = {'report_type': report_type}
    if ts_code:
        params['ts_code'] = ts_code
    if period:
        params['period'] = period.replace('-', '')
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.income_vip(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df = _format_date_col(df, 'ann_date')
    df = _format_date_col(df, 'f_ann_date')
    df = _format_date_col(df, 'end_date')
    return df


def fetch_cashflow(
    ts_code: Optional[str] = None,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    report_type: str = '1',
) -> pd.DataFrame:
    """现金流量表"""
    params = {'report_type': report_type}
    if ts_code:
        params['ts_code'] = ts_code
    if period:
        params['period'] = period.replace('-', '')
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.cashflow_vip(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df = _format_date_col(df, 'ann_date')
    df = _format_date_col(df, 'f_ann_date')
    df = _format_date_col(df, 'end_date')
    return df


def fetch_dividend(ts_code: str) -> pd.DataFrame:
    """
    分红数据

    Returns:
        ts_code, end_date, ann_date, div_proc(进度), stk_div(每股送转),
        cash_div(每股派息), cash_div_tax(税后派息), record_date, ex_date, pay_date, ...
    """
    df = pro.dividend(ts_code=ts_code, fields=(
        'ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,'
        'cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,'
        'imp_ann_date,base_date,base_share'
    ))

    if df is None or df.empty:
        return pd.DataFrame()

    for col in ['ann_date', 'end_date', 'record_date', 'ex_date', 'pay_date',
                'div_listdate', 'imp_ann_date', 'base_date']:
        df = _format_date_col(df, col)
    return df


def fetch_disclosure_date(
    ts_code: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    财报披露日期（关键：用于时间边界过滤）

    Returns:
        ts_code, ann_date(实际披露日), end_date(报告期), pre_date(预约披露), actual_date(修正后)
    """
    params = {}
    if ts_code:
        params['ts_code'] = ts_code
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.disclosure_date(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    for col in ['ann_date', 'end_date', 'pre_date', 'actual_date', 'modify_date']:
        df = _format_date_col(df, col)
    return df


def fetch_top10_holders(
    ts_code: str,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """前十大股东"""
    params = {'ts_code': ts_code}
    if period:
        params['period'] = period.replace('-', '')
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.top10_holders(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df = _format_date_col(df, 'ann_date')
    df = _format_date_col(df, 'end_date')
    return df


def fetch_financial_indicator(
    ts_code: str,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    财务指标（ROE、毛利率、资产负债率等综合指标）

    Returns:
        ts_code, ann_date, end_date, roe, roe_dt, grossprofit_margin,
        debt_to_assets, current_ratio, quick_ratio, ...
    """
    params = {'ts_code': ts_code}
    if period:
        params['period'] = period.replace('-', '')
    if start_date:
        params['start_date'] = start_date.replace('-', '')
    if end_date:
        params['end_date'] = end_date.replace('-', '')

    df = pro.fina_indicator_vip(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df = _format_date_col(df, 'ann_date')
    df = _format_date_col(df, 'end_date')
    return df
