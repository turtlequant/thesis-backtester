"""
近3年平均ROE

时序因子: 读取该股票近3年财务指标, 计算ROE均值。
高且稳定的ROE是优质企业的标志。
"""
import pandas as pd
import numpy as np

META = {
    'id': 'roe_avg_3y',
    'name': '3年平均ROE(%)',
    'type': 'timeseries',
    'description': '近3年年报ROE算术平均',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty:
        return None

    # 只取年报
    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    if 'roe' not in fi.columns:
        return None

    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    # 取最近3年
    fi = fi.tail(3)
    if len(fi) < 2:
        return None

    roe_values = fi['roe'].dropna()
    if len(roe_values) < 2:
        return None

    return round(roe_values.mean(), 2)
