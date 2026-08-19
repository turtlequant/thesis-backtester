"""
5年归母净利润复合增速 (CAGR)

时序因子: 读取该股票过去5年利润表, 计算归母净利润CAGR。
结果是一个静态数值, 可作为筛选/评分的属性因子。
"""
import pandas as pd
import numpy as np

META = {
    'id': 'profit_growth_5y',
    'name': '5年利润增速(%)',
    'type': 'timeseries',
    'description': '近5年归母净利润CAGR, 基于年报数据',
    'data_needed': ['income'],
}


def compute(ts_code: str, api) -> float:
    """计算5年利润CAGR

    Args:
        ts_code: 股票代码
        api: src.data.api 模块

    Returns:
        CAGR百分比, 如 15.3 表示年均增长15.3%
    """
    inc = api.get_income(ts_code)
    if inc.empty:
        return None

    # 只取年报 (end_date 以 12-31 结尾)
    inc = inc[inc['end_date'].str.endswith('12-31')].copy()
    if 'n_income_attr_p' not in inc.columns:
        return None

    inc = inc.drop_duplicates(subset=['end_date'], keep='last')
    inc = inc.sort_values('end_date')

    # 需要至少3年数据
    if len(inc) < 3:
        return None

    # 取最近5年 (或可用的全部)
    inc = inc.tail(6)  # 6个年报 = 5年增速

    start_val = inc.iloc[0]['n_income_attr_p']
    end_val = inc.iloc[-1]['n_income_attr_p']
    years = len(inc) - 1

    # 需要起止都为正值才能算CAGR
    if pd.isna(start_val) or pd.isna(end_val):
        return None
    if start_val <= 0 or end_val <= 0:
        return None

    cagr = (end_val / start_val) ** (1.0 / years) - 1
    return round(cagr * 100, 2)
