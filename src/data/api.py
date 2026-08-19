"""
数据查询接口 (只读)

提供行情、财报、预计算因子的统一查询入口。
所有上层模块 (screener, agent, backtest) 通过此模块读取数据。

CLI:
    python -m src.engine.launcher data status    # 查看数据覆盖状态

Python:
    from src.data import api
    api.get_stock_list()                                          # 股票列表
    api.get_daily('2024-01-01', '2024-06-30', ts_code='601288.SH')  # 不复权日线
    api.get_daily_adjusted('2024-01-01', '2024-06-30', adjust='qfq') # 前复权日线
    api.get_daily_adjusted('2024-01-01', '2024-06-30', adjust='hfq') # 后复权日线
    api.get_daily_indicator('2024-01-01', '2024-06-30')           # PE/PB/DV/市值
    api.get_income('601288.SH')                                   # 利润表
    api.get_factors('2024-01-01', '2024-06-30')                   # 截面因子
    api.get_ts_factors()                                          # 时序因子
    api.get_data_status()                                         # 数据状态字典
"""
from typing import List, Optional, Sequence, Union
import functools
import pandas as pd
from . import storage
from .config import get_active_provider_name


# ==================== 缓存层 ====================

@functools.lru_cache(maxsize=6)
def _load_stock_list(provider: str) -> pd.DataFrame:
    """缓存加载股票列表（会话内复用，避免重复读磁盘）"""
    return storage.load_one('basic', '', 'stock_list', provider=provider)


@functools.lru_cache(maxsize=3)
def _load_trade_calendar(provider: str) -> pd.DataFrame:
    """缓存加载交易日历"""
    return storage.load_one('basic', '', 'trade_calendar', provider=provider)


def clear_basic_caches() -> None:
    """Invalidate provider-aware stock and calendar caches after an update."""
    _load_stock_list.cache_clear()
    _load_trade_calendar.cache_clear()


# ==================== 股票列表 ====================

def get_stock_list(only_active: bool = True) -> pd.DataFrame:
    """获取股票列表"""
    df = _load_stock_list(get_active_provider_name())
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
    df = _load_trade_calendar(get_active_provider_name())
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
    ts_code: Optional[Union[str, Sequence[str]]] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """获取日线行情"""
    months = storage.get_months_between(start_date, end_date)
    if isinstance(ts_code, str):
        ts_codes = [ts_code]
    elif ts_code is None:
        ts_codes = []
    else:
        ts_codes = list(dict.fromkeys(str(code) for code in ts_code if code))

    if ts_code is not None and not ts_codes:
        return pd.DataFrame(columns=columns)

    filters = [('trade_date', '>=', start_date), ('trade_date', '<=', end_date)]
    if len(ts_codes) == 1:
        filters.append(('ts_code', '==', ts_codes[0]))
    elif ts_codes:
        filters.append(('ts_code', 'in', ts_codes))
    df = storage.load('daily', 'raw', months, columns, filters=filters)
    if df.empty:
        return df
    df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
    if ts_codes and 'ts_code' in df.columns:
        df = df[df['ts_code'].isin(ts_codes)]
    return df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


def get_daily_adjusted(
    start_date: str,
    end_date: str,
    ts_code: Optional[Union[str, Sequence[str]]] = None,
    adjust: str = 'qfq',
    columns: Optional[List[str]] = None,
    keep_raw_prices: bool = False,
) -> pd.DataFrame:
    """获取复权日线行情

    自动合并 raw + adj_factor，计算复权价格。

    Args:
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        ts_code: 股票代码或代码列表，None 返回全市场
        adjust: 复权方式
            'qfq' - 前复权 (默认，以最新价为基准向前调整)
            'hfq' - 后复权 (以上市首日价为基准向后调整)
        columns: 原始日线需要返回的列；复权计算会自动补充代码、日期和价格列
        keep_raw_prices: 是否同时保留 raw_open/raw_high/raw_low/raw_close

    Returns:
        DataFrame 包含: ts_code, trade_date, open, high, low, close, volume, amount
        其中 open/high/low/close 已按复权方式调整
    """
    if adjust not in {'qfq', 'hfq'}:
        raise ValueError("adjust 必须是 'qfq' 或 'hfq'")

    if isinstance(ts_code, str):
        ts_codes = [ts_code]
    elif ts_code is None:
        ts_codes = []
    else:
        ts_codes = list(dict.fromkeys(str(code) for code in ts_code if code))
    if ts_code is not None and not ts_codes:
        return pd.DataFrame(columns=columns)

    months = storage.get_months_between(start_date, end_date)
    filters = [('trade_date', '>=', start_date), ('trade_date', '<=', end_date)]
    if len(ts_codes) == 1:
        filters.append(('ts_code', '==', ts_codes[0]))
    elif ts_codes:
        filters.append(('ts_code', 'in', ts_codes))

    requested_columns = list(dict.fromkeys(columns)) if columns else None
    raw_columns = requested_columns
    if raw_columns is not None:
        raw_columns = list(dict.fromkeys(['ts_code', 'trade_date', *raw_columns]))
    raw = storage.load('daily', 'raw', months, raw_columns, filters=filters)
    if raw.empty:
        return raw
    adj = storage.load(
        'daily',
        'adj_factor',
        months,
        ['ts_code', 'trade_date', 'adj_factor'],
        filters=filters,
    )
    if adj.empty:
        raise RuntimeError(
            f"{start_date} ~ {end_date} 缺少复权因子，不能退回不复权行情"
        )

    raw = raw[(raw['trade_date'] >= start_date) & (raw['trade_date'] <= end_date)]
    adj = adj[(adj['trade_date'] >= start_date) & (adj['trade_date'] <= end_date)]
    if ts_codes and 'ts_code' in raw.columns:
        raw = raw[raw['ts_code'].isin(ts_codes)]
        adj = adj[adj['ts_code'].isin(ts_codes)]

    df = raw.merge(adj, on=['ts_code', 'trade_date'], how='left')
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    missing_factors = df['adj_factor'].isna()
    if missing_factors.any():
        missing_rows = int(missing_factors.sum())
        missing_stocks = int(df.loc[missing_factors, 'ts_code'].nunique())
        raise RuntimeError(
            f"复权因子不完整：{missing_stocks} 只股票、{missing_rows} 行行情无法复权"
        )
    df['adj_factor'] = pd.to_numeric(df['adj_factor'], errors='coerce')
    if df['adj_factor'].isna().any():
        raise RuntimeError("复权因子包含非数值，无法计算复权行情")

    price_cols = [column for column in ['open', 'high', 'low', 'close'] if column in df.columns]
    if keep_raw_prices:
        for col in price_cols:
            df[f'raw_{col}'] = pd.to_numeric(df[col], errors='coerce')
    if adjust == 'hfq':
        # 后复权: price * adj_factor
        for col in price_cols:
            df[col] = (pd.to_numeric(df[col], errors='coerce') * df['adj_factor']).round(4)
    else:
        # 前复权: price * adj_factor / latest_adj_factor_per_stock
        latest_adj = df.groupby('ts_code')['adj_factor'].transform('last')
        for col in price_cols:
            df[col] = (
                pd.to_numeric(df[col], errors='coerce') * df['adj_factor'] / latest_adj
            ).round(4)

    df = df.drop(columns=['adj_factor'])
    return df


def get_daily_hfq_windows(
    windows: Sequence[tuple[str, str, str]],
) -> pd.DataFrame:
    """批量读取多个股票日期窗口的后复权收盘价。

    ``windows`` 每项为 ``(ts_code, start_date, end_date)``。重叠窗口会在
    SQLite 查询前合并，适用于多截面前向收益采集。
    """
    return storage.load_hfq_close_windows(
        windows,
        provider=get_active_provider_name(),
    )


def get_daily_indicator(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """获取每日指标（PE/PB/换手率/市值等）"""
    months = storage.get_months_between(start_date, end_date)
    filters = [
        ('trade_date', '>=', start_date),
        ('trade_date', '<=', end_date),
    ]
    if ts_code:
        filters.append(('ts_code', '==', ts_code))
    df = storage.load('daily', 'indicator', months, columns, filters=filters)
    if df.empty:
        return df
    df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
    if ts_code and 'ts_code' in df.columns:
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
    df = storage.load_financial('balancesheet', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_income(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取利润表"""
    df = storage.load_financial('income', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_cashflow(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取现金流量表"""
    df = storage.load_financial('cashflow', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_dividends(
    ts_codes: Sequence[str],
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """批量获取多只股票的分红数据。"""
    codes = list(dict.fromkeys(str(code) for code in ts_codes if code))
    if not codes:
        return pd.DataFrame(columns=columns)
    df = storage.load_financial('dividend', partitions=codes, columns=columns)
    if df.empty:
        return df
    sort_columns = [column for column in ('ts_code', 'end_date') if column in df.columns]
    return df.sort_values(sort_columns).reset_index(drop=True) if sort_columns else df.reset_index(drop=True)


def get_dividend(ts_code: str) -> pd.DataFrame:
    """获取单只股票的分红数据。"""
    return get_dividends([ts_code])


def get_financial_indicator(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取财务指标（ROE、毛利率等）"""
    df = storage.load_financial('fina_indicator', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_disclosure_dates(ts_code: str) -> pd.DataFrame:
    """获取财报披露日期（disclosure_date 按报告期分区，需加载全部后按股票过滤）"""
    df = storage.load_financial('disclosure_date')
    if df.empty:
        return df
    if 'ts_code' in df.columns:
        df = df[df['ts_code'] == ts_code]
    return df.sort_values('end_date').reset_index(drop=True)


def get_top10_holders(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取前十大股东"""
    df = storage.load_financial('top10_holders', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values(['end_date', 'hold_ratio'], ascending=[True, False]).reset_index(drop=True)


def get_top10_floatholders(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取前十大流通股东"""
    df = storage.load_financial('top10_floatholders', partitions=[ts_code])
    if df.empty:
        return df
    if end_date and 'end_date' in df.columns:
        df = df[df['end_date'] <= end_date]
    return df.reset_index(drop=True)


def get_pledge_stat(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取股权质押统计"""
    df = storage.load_financial('pledge_stat', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_pledge_detail(ts_code: str) -> pd.DataFrame:
    """获取股权质押明细"""
    df = storage.load_financial('pledge_detail', partitions=[ts_code])
    if df.empty:
        return df
    return df.reset_index(drop=True)


def get_fina_audit(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取审计意见"""
    df = storage.load_financial('fina_audit', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_fina_mainbz(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取主营业务构成"""
    df = storage.load_financial('fina_mainbz', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_stk_holdernumber(
    ts_code: str,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取股东人数"""
    df = storage.load_financial('stk_holdernumber', partitions=[ts_code])
    if df.empty:
        return df
    if end_date:
        df = df[df['end_date'] <= end_date]
    return df.sort_values('end_date').reset_index(drop=True)


def get_stk_holdertrade(ts_code: str) -> pd.DataFrame:
    """获取股东增减持"""
    df = storage.load_financial('stk_holdertrade', partitions=[ts_code])
    if df.empty:
        return df
    return df.reset_index(drop=True)


def get_share_float(ts_code: str) -> pd.DataFrame:
    """获取限售解禁"""
    df = storage.load_financial('share_float', partitions=[ts_code])
    if df.empty:
        return df
    return df.reset_index(drop=True)


def get_repurchase(ts_code: str) -> pd.DataFrame:
    """获取股票回购"""
    df = storage.load_financial('repurchase', partitions=[ts_code])
    if df.empty:
        return df
    return df.reset_index(drop=True)


# ==================== 预计算因子 ====================

def get_factors(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """获取预计算的因子数据"""
    from .factor_store import get_factor_data
    return get_factor_data(start_date, end_date, ts_code, columns)


def get_daily_indicator_with_factors(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
) -> pd.DataFrame:
    """获取每日指标 + 预计算因子 (合并)"""
    from .factor_store import get_indicator_with_factors
    return get_indicator_with_factors(start_date, end_date, ts_code)


def get_ts_factors(
    ts_code=None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """获取预计算的时序因子 (每股票一行静态属性)"""
    from .factor_store import get_ts_factor_data
    return get_ts_factor_data(ts_code, columns)


# ==================== 元信息 ====================

def get_latest_date(category: str = 'daily', sub: str = 'raw') -> Optional[str]:
    """获取本地数据最新日期"""
    return storage.get_latest_date(category, sub)


def get_index_daily(
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    获取当前数据口径的指数日线行情。

    Args:
        ts_code: 指数代码，如 '000300.SH' (沪深300), '000905.SH' (中证500)
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        DataFrame [ts_code, trade_date, close, open, high, low, pct_chg]
    """
    from .provider import get_provider

    provider = get_provider()
    fetch = getattr(provider, 'fetch_index_daily', None)
    if fetch is None:
        return pd.DataFrame()
    return fetch(ts_code, start_date, end_date)


def get_data_status() -> dict:
    """获取本地数据状态摘要"""
    status = {}

    # 日线数据
    for sub in ['raw', 'indicator', 'adj_factor', 'factors']:
        partitions = storage.list_partitions('daily', sub)
        latest = storage.get_latest_date('daily', sub) if partitions else None
        status[f'daily_{sub}'] = {
            'partitions': len(partitions),
            'latest_date': latest,
            'months': f"{partitions[0]}~{partitions[-1]}" if partitions else None,
        }

    # 时序因子
    ts_df = get_ts_factors()
    ts_factor_cols = [c for c in ts_df.columns if c != 'ts_code'] if not ts_df.empty else []
    status['ts_factors'] = {
        'stocks': len(ts_df),
        'factors': len(ts_factor_cols),
        'factor_ids': ts_factor_cols,
    }

    # 财报数据
    for sub in ['balancesheet', 'income', 'cashflow', 'fina_indicator',
                'dividend', 'top10_holders', 'top10_floatholders',
                'pledge_stat', 'pledge_detail', 'fina_audit', 'fina_mainbz',
                'stk_holdernumber', 'stk_holdertrade', 'share_float', 'repurchase',
                'disclosure_date']:
        partitions = storage.list_financial_partitions(sub)
        status[f'financial_{sub}'] = {
            'count': len(partitions),
        }

    # 基础数据
    stock_list = get_stock_list(only_active=True)
    status['stock_list'] = {'active_count': len(stock_list)}

    return status
