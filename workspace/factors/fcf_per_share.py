"""
每股自由现金流 (FCFF)

时序因子: 最近年报的每股企业自由现金流。
正 FCF 是分红和回购的基础。EV/FCF < 10 = 便宜。
"""

META = {
    'id': 'fcf_ps',
    'name': '每股FCF(元)',
    'type': 'timeseries',
    'description': '最近年报每股企业自由现金流',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'fcff_ps' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date')

    if fi.empty:
        return None

    val = fi.iloc[-1]['fcff_ps']
    if val is None or (hasattr(val, '__class__') and val != val):
        return None
    return round(float(val), 4)
