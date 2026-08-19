"""
3年ROE波动系数

时序因子: 近3年ROE标准差/均值 (CV)。
值越小 = ROE越稳定。稳定高ROE是巴菲特选股核心标准。
"""
import numpy as np

META = {
    'id': 'roe_stability_3y',
    'name': '3年ROE波动系数',
    'type': 'timeseries',
    'description': 'ROE变异系数(std/mean), 越小越稳',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'roe' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date').tail(3)

    vals = fi['roe'].dropna()
    if len(vals) < 2:
        return None

    mean_val = vals.mean()
    if abs(mean_val) < 0.01:
        return None

    cv = vals.std() / abs(mean_val)
    return round(cv, 4)
