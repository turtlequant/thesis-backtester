"""
股息率统一因子

合并 dv_ratio / dv_ttm 为统一的 dv 字段，优先取 dv_ttm。
解决 tushare daily_basic 中股息率字段不一致的问题。
"""
import pandas as pd

META = {
    'id': 'dv',
    'name': '股息率(%)',
    'description': '统一股息率 = dv_ttm > dv_ratio (fallback)',
    'data_needed': ['daily_indicator'],
}


def compute(df: pd.DataFrame) -> pd.Series:
    import numpy as np
    series = pd.Series(np.nan, index=df.index, dtype='float64')
    for col in ['dv_ttm', 'dv_ratio']:
        if col in df.columns:
            series = series.fillna(df[col])
    return series
