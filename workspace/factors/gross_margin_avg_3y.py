"""
3年平均毛利率

时序因子: 近3年年报毛利率均值。
高毛利率 = 产品有定价权或竞争优势。
"""

META = {
    'id': 'gross_margin_avg_3y',
    'name': '3年平均毛利率(%)',
    'type': 'timeseries',
    'description': '近3年年报毛利率算术平均',
    'data_needed': ['fina_indicator'],
}


def compute(ts_code: str, api) -> float:
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'grossprofit_margin' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi = fi.sort_values('end_date').tail(3)

    vals = fi['grossprofit_margin'].dropna()
    if len(vals) < 2:
        return None
    return round(vals.mean(), 2)
