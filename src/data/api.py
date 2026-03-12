"""
数据查询接口

提供行情和基本面数据的统一查询入口
"""
from typing import List, Optional
import pandas as pd
from . import storage


# ==================== 股票列表 ====================

def get_stock_list(only_active: bool = True) -> pd.DataFrame:
    """获取股票列表"""
    df = storage.load_one('basic', '', 'stock_list')
    if df.empty:
        return df
    if only_active:
        df = df[df['list_status'] == 'L']
    return pd.DataFrame(df)


def get_stock_codes(only_active: bool = True) -> List[str]:
    """获取股票代码列表"""
    df = get_stock_list(only_active)
    return df['ts_code'].tolist() if not df.empty else []


def get_stock_name(ts_code: str) -> Optional[str]:
    """获取股票名称"""
    df = get_stock_list(only_active=False)
    if df.empty:
        return None
    match = df[df['ts_code'] == ts_code]
    return match['name'].iloc[0] if not match.empty else None


# ==================== 交易日历 ====================

def get_trade_calendar(
    start_date: str,
    end_date: str,
    only_open: bool = True,
) -> pd.DataFrame:
    """获取交易日历"""
    df = storage.load_one('basic', '', 'trade_calendar')
    if df.empty:
        return df
    df = df[(df['cal_date'] >= start_date) & (df['cal_date'] <= end_date)]
    if only_open:
        df = df[df['is_open'] == 1]
    return df.sort_values('cal_date').reset_index(drop=True)


def get_trade_dates(start_date: str, end_date: str) -> List[str]:
    """获取交易日列表"""
    df = get_trade_calendar(start_date, end_date, only_open=True)
    return df['cal_date'].tolist() if not df.empty else []


# ==================== 日线行情 ====================

def get_daily(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """获取日线行情"""
    months = storage.get_months_between(start_date, end_date)
    df = storage.load('daily', 'raw', months, columns)
    if df.empty:
        return df
    df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
    if ts_code:
        df = df[df['ts_code'] == ts_code]
    return df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


def get_daily_indicator(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """获取每日指标（PE/PB/换手率/市值等）"""
    months = storage.get_months_between(start_date, end_date)
    df = storage.load('daily', 'indicator', months, columns)
    if df.empty:
        return df
    df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
    if ts_code:
        df = df[df['ts_code'] == ts_code]
    return df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


# ==================== 基本面数据 ====================

def get_balancesheet(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取资产负债表

    Args:
        ts_code: 股票代码
        end_date: 截止报告期，如 '2024-06-30'，None 则返回所有
    """
    df = storage.load_financial('balancesheet')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_income(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取利润表"""
    df = storage.load_financial('income')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_cashflow(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取现金流量表"""
    df = storage.load_financial('cashflow')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_dividend(ts_code: str) -> pd.DataFrame:
    """获取分红数据"""
    df = storage.load_financial('dividend')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    return df.sort_values('end_date').reset_index(drop=True)


def get_financial_indicator(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取财务指标（ROE、毛利率等）"""
    df = storage.load_financial('fina_indicator')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_disclosure_dates(ts_code: str) -> pd.DataFrame:
    """获取财报披露日期"""
    df = storage.load_financial('disclosure_date')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    return df.sort_values('end_date').reset_index(drop=True)


def get_top10_holders(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取前十大股东"""
    df = storage.load_financial('top10_holders')
    if df.empty:
        return df
    df = df[df['ts_code'] == ts_code]
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values(['end_date', 'hold_ratio'], ascending=[True, False]).reset_index(drop=True)


# ==================== 元信息 ====================

def get_latest_date(category: str = 'daily', sub: str = 'raw') -> Optional[str]:
    """获取本地数据最新日期"""
    return storage.get_latest_date(category, sub)
