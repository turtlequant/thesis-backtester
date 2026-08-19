"""
最新1年营收同比增速

时序因子: 取最近年报的营业收入同比增速。
"""

META = {
    'id': 'revenue_growth_1y',
    'name': '1年营收增速(%)',
    'type': 'timeseries',
    'description': '最近年报营业收入同比增速',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'or_yoy' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['or_yoy']
    if val is None or (hasattr(val, '__class__') and val != val):
        return None
    return round(float(val), 2)
