"""
最新1年净利润同比增速

时序因子: 取最近年报的归母净利润同比增速。
短期增速反映当前景气度。
"""

META = {
    'id': 'profit_growth_1y',
    'name': '1年利润增速(%)',
    'type': 'timeseries',
    'description': '最近年报归母净利润同比增速',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'netprofit_yoy' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['netprofit_yoy']
    if val is None or (hasattr(val, '__class__') and val != val):
        return None
    return round(float(val), 2)
