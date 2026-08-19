"""
盈利收益率因子 (EP)

PE 的倒数，便于和利率比较。EP > 无风险利率×2 → 有吸引力。
"""
import pandas as pd
import numpy as np

META = {
    'id': 'ep',
    'name': '盈利收益率(%)',
    'description': '1/PE × 100, 即 E/P',
    'data_needed': ['daily_indicator'],
}


def compute(df: pd.DataFrame) -> pd.Series:
    if 'pe_ttm' not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype='float64')
    pe = df['pe_ttm'].replace(0, np.nan)
    return (100.0 / pe).round(2)
