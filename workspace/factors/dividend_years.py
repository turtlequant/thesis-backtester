"""
连续分红年数

时序因子: 统计该股票连续派息的年数 (从最近一年往回数)。
连续多年分红是稳定现金流和治理良好的信号。
"""
import pandas as pd

META = {
    'id': 'dividend_years',
    'name': '连续分红年数',
    'type': 'timeseries',
    'description': '从最近年度往回连续派息的年数',
    'data_needed': ['dividend'],
}


def compute(ts_code: str, api) -> float:
    div = api.get_dividend(ts_code)
    if div.empty or 'cash_div' not in div.columns:
        return 0.0

    # 只看已实施的分红
    if 'div_proc' in div.columns:
        div = div[div['div_proc'] == '实施']

    if div.empty:
        return 0.0

    # 按年度汇总派息
    div = div[div['cash_div'].notna() & (div['cash_div'] > 0)].copy()
    if div.empty:
        return 0.0

    # 提取年份
    div['year'] = div['end_date'].str[:4].astype(int)
    years_with_div = sorted(div['year'].unique(), reverse=True)

    if not years_with_div:
        return 0.0

    # 从最近的年份往回数连续的
    count = 1
    for i in range(1, len(years_with_div)):
        if years_with_div[i] == years_with_div[i - 1] - 1:
            count += 1
        else:
            break

    return float(count)
