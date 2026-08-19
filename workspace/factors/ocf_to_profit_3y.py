"""
3年经营现金流/净利润比率 (现金转换率)

时序因子: 近3年经营活动净现金流累计 / 归母净利润累计。
>100% 说明利润质量好，不是纸面利润。V5.5.6 核心指标。
"""
import pandas as pd

META = {
    'id': 'ocf_to_profit_3y',
    'name': '3年现金转换率(%)',
    'type': 'timeseries',
    'description': '近3年累计OCF/累计归母净利润',
    'data_needed': ['cashflow', 'income'],
}


def compute(ts_code: str, api) -> float:
    cf = api.get_cashflow(ts_code)
    inc = api.get_income(ts_code)
    if cf.empty or inc.empty:
        return None

    # 只取年报
    cf = cf[cf['end_date'].str.endswith('12-31')].copy()
    inc = inc[inc['end_date'].str.endswith('12-31')].copy()

    if 'n_cashflow_act' not in cf.columns or 'n_income_attr_p' not in inc.columns:
        return None

    cf = cf.drop_duplicates(subset=['end_date'], keep='last').sort_values('end_date').tail(3)
    inc = inc.drop_duplicates(subset=['end_date'], keep='last').sort_values('end_date').tail(3)

    # 取交集年份
    common_years = set(cf['end_date']) & set(inc['end_date'])
    if len(common_years) < 2:
        return None

    cf = cf[cf['end_date'].isin(common_years)]
    inc = inc[inc['end_date'].isin(common_years)]

    total_ocf = cf['n_cashflow_act'].dropna().sum()
    total_profit = inc['n_income_attr_p'].dropna().sum()

    if total_profit <= 0:
        return None

    return round(total_ocf / total_profit * 100, 2)
