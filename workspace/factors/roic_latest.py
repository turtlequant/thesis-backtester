"""
最新投入资本回报率 ROIC

时序因子: 最近年报 ROIC。
ROIC > WACC 说明在创造价值。高 ROIC 是护城河的量化体现。
"""

META = {
    'id': 'roic',
    'name': 'ROIC(%)',
    'type': 'timeseries',
    'description': '最近年报投入资本回报率',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'roic' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['roic']
    if val is None or (hasattr(val, '__class__') and val != val):
        return None
    return round(float(val), 2)
