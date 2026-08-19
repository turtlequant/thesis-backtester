"""
流通市值(亿元)

将 circ_mv (万元) 转为亿元。
用于区分大盘/中盘/小盘，或作为流动性代理。
"""
import pandas as pd

META = {
    'id': 'circ_mv_yi',
    'name': '流通市值(亿)',
    'description': 'circ_mv / 10000',
    'data_needed': ['daily_indicator'],
}


def compute(df: pd.DataFrame) -> pd.Series:
    if 'circ_mv' in df.columns:
        return (df['circ_mv'] / 10000).round(2)
    return pd.Series(pd.NA, index=df.index, dtype='float64')
