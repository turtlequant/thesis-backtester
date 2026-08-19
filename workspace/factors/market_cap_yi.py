"""
市值(亿元)因子

将 tushare 的 total_mv (万元) 转为亿元，方便阅读和设阈值。
"""
import pandas as pd

META = {
    'id': 'market_cap_yi',
    'name': '总市值(亿)',
    'description': 'total_mv / 10000',
    'data_needed': ['daily_indicator'],
}


def compute(df: pd.DataFrame) -> pd.Series:
    if 'total_mv' in df.columns:
        return (df['total_mv'] / 10000).round(2)
    return pd.Series(pd.NA, index=df.index, dtype='float64')
