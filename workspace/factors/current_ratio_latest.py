"""
最新流动比率

时序因子: 最近一期年报流动比率。
>2 一般认为短期偿债能力良好。
"""

META = {
    'id': 'current_ratio',
    'name': '流动比率',
    'type': 'timeseries',
    'description': '最近年报流动比率',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'current_ratio' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['current_ratio']
    if val is None or (hasattr(val, '__class__') and val != val):
        return None
    return round(float(val), 2)
