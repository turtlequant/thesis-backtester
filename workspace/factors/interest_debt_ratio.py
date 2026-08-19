"""
有息负债占比

时序因子: 有息负债占总资本的比例。
"无有息负债"是价值投资的重要正面信号（V5.5.6 Ch03）。
"""

META = {
    'id': 'interest_debt_ratio',
    'name': '有息负债占比(%)',
    'type': 'timeseries',
    'description': '最近年报有息负债/总资本',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'int_to_talcap' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['int_to_talcap']
    if val is None or (hasattr(val, '__class__') and val != val):
        return None
    return round(float(val), 2)
