"""
最新资产负债率

时序因子: 取最近一期年报的资产负债率。
价值投资关注负债水平，低负债 = 财务安全。
"""

META = {
    'id': 'debt_to_assets',
    'name': '资产负债率(%)',
    'type': 'timeseries',
    'description': '最近年报资产负债率',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'debt_to_assets' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['debt_to_assets']
    if val is None or (hasattr(val, '__class__') and val != val):  # NaN check
        return None
    return round(float(val), 2)
