"""
数据更新

行情数据：逐日拉取，按月分区存储
基本面数据：按股票拉取，按类型存储
"""
from datetime import datetime, timedelta
import time
from typing import List, Optional
import pandas as pd

from . import tushare_client as ts_api
from . import storage
from . import api


# ==================== 基础数据 ====================

def update_stock_list():
    """更新股票列表"""
    print("更新股票列表...", end=' ')
    df = ts_api.fetch_stock_list()
    if df.empty:
        print("失败: 无数据")
        return False
    storage.save(df, 'basic', '', 'stock_list')
    print(f"完成, {len(df)} 条")
    return True


def update_trade_calendar(start_date: str = '2000-01-01', end_date: str = None):
    """更新交易日历"""
    if end_date is None:
        end_date = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
    print(f"更新交易日历 {start_date} ~ {end_date}...", end=' ')
    df = ts_api.fetch_trade_calendar(start_date, end_date)
    if df.empty:
        print("失败: 无数据")
        return False
    storage.save(df, 'basic', '', 'trade_calendar')
    print(f"完成, {len(df)} 条")
    return True


# ==================== 日线数据 ====================

def update_daily(start_date: str = None, end_date: str = None):
    """更新日线行情 + 复权因子"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    if start_date is None:
        latest = storage.get_latest_date('daily', 'raw')
        if latest:
            start_date = (pd.to_datetime(latest) + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            start_date = '2015-01-01'

    if start_date > end_date:
        print(f"日线数据已是最新 ({end_date})")
        return True

    print(f"更新日线 {start_date} ~ {end_date}")
    trade_dates = api.get_trade_dates(start_date, end_date)
    if not trade_dates:
        print("  无交易日")
        return True

    for date in trade_dates:
        print(f"  {date}...", end=' ')
        df_raw = ts_api.fetch_daily(trade_date=date)
        if df_raw.empty:
            print("无数据")
            continue
        df_adj = ts_api.fetch_adj_factor(trade_date=date)
        month = storage.get_month(date)
        merge_on = ['ts_code', 'trade_date']
        storage.save(df_raw, 'daily', 'raw', month, mode='merge', merge_on=merge_on)
        if not df_adj.empty:
            storage.save(df_adj, 'daily', 'adj_factor', month, mode='merge', merge_on=merge_on)
        print(f"行情 {len(df_raw)}, 复权 {len(df_adj)}")

    print("日线更新完成")
    return True


def update_daily_indicator(start_date: str = None, end_date: str = None):
    """更新每日指标"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    if start_date is None:
        latest = storage.get_latest_date('daily', 'indicator')
        if latest:
            start_date = (pd.to_datetime(latest) + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            start_date = '2015-01-01'

    if start_date > end_date:
        print(f"每日指标已是最新 ({end_date})")
        return True

    print(f"更新每日指标 {start_date} ~ {end_date}")
    trade_dates = api.get_trade_dates(start_date, end_date)
    if not trade_dates:
        print("  无交易日")
        return True

    for date in trade_dates:
        print(f"  {date}...", end=' ')
        df = ts_api.fetch_daily_indicator(trade_date=date)
        if df.empty:
            print("无数据")
            continue
        month = storage.get_month(date)
        storage.save(df, 'daily', 'indicator', month, mode='merge', merge_on=['ts_code', 'trade_date'])
        print(f"{len(df)} 条")

    print("每日指标更新完成")
    return True


# ==================== 基本面数据 ====================

def update_financial_statements(ts_code: str, force: bool = False):
    """
    更新单只股票的三大报表 + 财务指标

    Args:
        ts_code: 股票代码
        force: True 则强制重新拉取
    """
    print(f"更新财报 {ts_code}...")
    merge_on = ['ts_code', 'end_date', 'report_type']

    # 资产负债表
    print("  资产负债表...", end=' ')
    df = ts_api.fetch_balancesheet(ts_code=ts_code)
    if not df.empty:
        storage.save_financial(df, 'balancesheet', ts_code, mode='merge',
                               merge_on=['ts_code', 'end_date'])
        print(f"{len(df)} 条")
    else:
        print("无数据")
    time.sleep(0.3)

    # 利润表
    print("  利润表...", end=' ')
    df = ts_api.fetch_income(ts_code=ts_code)
    if not df.empty:
        storage.save_financial(df, 'income', ts_code, mode='merge',
                               merge_on=['ts_code', 'end_date'])
        print(f"{len(df)} 条")
    else:
        print("无数据")
    time.sleep(0.3)

    # 现金流量表
    print("  现金流量表...", end=' ')
    df = ts_api.fetch_cashflow(ts_code=ts_code)
    if not df.empty:
        storage.save_financial(df, 'cashflow', ts_code, mode='merge',
                               merge_on=['ts_code', 'end_date'])
        print(f"{len(df)} 条")
    else:
        print("无数据")
    time.sleep(0.3)

    # 财务指标
    print("  财务指标...", end=' ')
    df = ts_api.fetch_financial_indicator(ts_code=ts_code)
    if not df.empty:
        storage.save_financial(df, 'fina_indicator', ts_code, mode='merge',
                               merge_on=['ts_code', 'end_date'])
        print(f"{len(df)} 条")
    else:
        print("无数据")
    time.sleep(0.3)

    print(f"  {ts_code} 财报更新完成")
    return True


def update_dividend(ts_code: str):
    """更新分红数据"""
    print(f"  分红数据 {ts_code}...", end=' ')
    df = ts_api.fetch_dividend(ts_code=ts_code)
    if not df.empty:
        storage.save_financial(df, 'dividend', ts_code, mode='overwrite')
        print(f"{len(df)} 条")
    else:
        print("无数据")
    time.sleep(0.3)
    return True


def update_disclosure_date(end_date: Optional[str] = None):
    """
    更新财报披露日期（全市场）

    Args:
        end_date: 报告期，如 '2024-12-31'，None 则更新最近4个报告期
    """
    if end_date:
        periods = [end_date]
    else:
        # 最近4个报告期
        now = datetime.now()
        periods = []
        for year in [now.year, now.year - 1]:
            for month in ['12-31', '06-30']:
                periods.append(f"{year}-{month}")
        periods.sort()

    for period in periods:
        print(f"  披露日期 {period}...", end=' ')
        df = ts_api.fetch_disclosure_date(end_date=period)
        if not df.empty:
            storage.save_financial(df, 'disclosure_date', period.replace('-', ''),
                                   mode='overwrite')
            print(f"{len(df)} 条")
        else:
            print("无数据")
        time.sleep(0.5)

    return True


def update_top10_holders(ts_code: str):
    """更新前十大股东"""
    print(f"  前十大股东 {ts_code}...", end=' ')
    df = ts_api.fetch_top10_holders(ts_code=ts_code)
    if not df.empty:
        storage.save_financial(df, 'top10_holders', ts_code, mode='overwrite')
        print(f"{len(df)} 条")
    else:
        print("无数据")
    time.sleep(0.3)
    return True


def update_stock_all(ts_code: str):
    """更新单只股票的全部基本面数据"""
    print(f"{'=' * 40}")
    print(f"全量更新 {ts_code}")
    print(f"{'=' * 40}")
    update_financial_statements(ts_code)
    update_dividend(ts_code)
    update_top10_holders(ts_code)
    print(f"{ts_code} 全部完成")


# ==================== 便捷方法 ====================

def init_basic():
    """初始化基础数据"""
    print("=" * 50)
    print("初始化基础数据")
    print("=" * 50)
    update_stock_list()
    update_trade_calendar()


def init_market_data(start_date: str = '2020-01-01'):
    """初始化行情数据"""
    print("=" * 50)
    print(f"初始化行情数据 (从 {start_date})")
    print("=" * 50)
    update_daily(start_date=start_date)
    update_daily_indicator(start_date=start_date)


def daily_update():
    """每日增量更新（行情）"""
    print("=" * 50)
    print(f"每日增量更新 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    update_stock_list()
    update_daily()
    update_daily_indicator()
    print("=" * 50)
    print("更新完成")
    print("=" * 50)
