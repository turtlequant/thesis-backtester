"""
净资产收益率 BP (Book-to-Price)

PB 的倒数，高 BP 意味着价格相对净资产便宜。
与 EP 配合使用，双高 = 深度低估信号。
"""
import pandas as pd
import numpy as np

META = {
    'id': 'bp',
    'name': 'B/P比率',
    'description': '1/PB, 即账面价值/市价',
    'data_needed': ['daily_indicator'],
}


def compute(df: pd.DataFrame) -> pd.Series:
    if 'pb' not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype='float64')
    pb = df['pb'].replace(0, np.nan)
    return (1.0 / pb).round(4)
