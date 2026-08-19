"""
5年营收复合增速 (CAGR)

时序因子: 读取该股票过去5年利润表, 计算营业收入CAGR。
"""
import pandas as pd
import numpy as np

META = {
    'id': 'revenue_growth_5y',
    'name': '5年营收增速(%)',
    'type': 'timeseries',
    'description': '近5年营业收入CAGR, 基于年报数据',
    'data_needed': ['income'],
}


def compute(ts_code: str, api) -> float:
    inc = api.get_income(ts_code)
    if inc.empty:
        return None

    inc = inc[inc['end_date'].str.endswith('12-31')].copy()
    if 'revenue' not in inc.columns:
        return None

    inc = inc.drop_duplicates(subset=['end_date'], keep='last')
    inc = inc.sort_values('end_date')

    if len(inc) < 3:
        return None

    inc = inc.tail(6)

    start_val = inc.iloc[0]['revenue']
    end_val = inc.iloc[-1]['revenue']
    years = len(inc) - 1

    if pd.isna(start_val) or pd.isna(end_val):
        return None
    if start_val <= 0 or end_val <= 0:
        return None

    cagr = (end_val / start_val) ** (1.0 / years) - 1
    return round(cagr * 100, 2)
