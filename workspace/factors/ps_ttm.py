"""
市销率 PS_TTM

统一提取 ps_ttm 字段，兜底 ps。
低 PS 在周期底部有意义（利润被压缩但收入仍在）。
"""
import pandas as pd
import numpy as np

META = {
    'id': 'ps_ttm',
    'name': '市销率TTM',
    'description': '市销率(滚动12个月)',
    'data_needed': ['daily_indicator'],
}


def compute(df: pd.DataFrame) -> pd.Series:
    series = pd.Series(np.nan, index=df.index, dtype='float64')
    for col in ['ps_ttm', 'ps']:
        if col in df.columns:
            series = series.fillna(df[col])
    return series.round(2)
