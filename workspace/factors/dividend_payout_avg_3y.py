"""
3年平均分红比率

时序因子: 近3年现金分红总额/归母净利润总额。
稳定高分红比率 = 分红可持续性强。
"""
import pandas as pd

META = {
    'id': 'dividend_payout_3y',
    'name': '3年分红比率(%)',
    'type': 'timeseries',
    'description': '近3年累计现金分红/累计归母净利润',
    'data_needed': ['dividend', 'income'],
}


def compute(ts_code: str, api) -> float:
    div = api.get_dividend(ts_code)
    inc = api.get_income(ts_code)
    if div.empty or inc.empty:
        return None

    # 只看已实施的分红
    if 'div_proc' in div.columns:
        div = div[div['div_proc'] == '实施']
    if div.empty or 'cash_div_tax' not in div.columns:
        return None

    # 年报净利润
    inc = inc[inc['end_date'].str.endswith('12-31')].copy()
    if 'n_income_attr_p' not in inc.columns:
        return None
    inc = inc.drop_duplicates(subset=['end_date'], keep='last').sort_values('end_date').tail(3)

    if len(inc) < 2:
        return None

    # 按年度汇总分红 (cash_div_tax 是每股税前分红，需要 × 总股本; 但更简单的是看 total_share * cash_div_tax)
    # 实际上 tushare dividend 有 stk_div_tax (每10股分红), 也可能有不同字段
    # 用 end_date 年份匹配
    years = set(inc['end_date'].str[:4])
    div['year'] = div['end_date'].str[:4]
    div_in_range = div[div['year'].isin(years)]

    if div_in_range.empty:
        return None

    # 用每股分红 × 股本估算总分红，或直接用 cash_div_tax
    # 简化: 使用 cash_div_tax 的年度汇总作为每股分红代理
    annual_div = div_in_range.groupby('year')['cash_div_tax'].sum()
    annual_profit = inc.set_index(inc['end_date'].str[:4])['n_income_attr_p']

    common = set(annual_div.index) & set(annual_profit.index)
    if len(common) < 2:
        return None

    # 这里用比率的平均值 (每年分红/每年利润的均值)
    # 因为 cash_div_tax 是每股分红, n_income_attr_p 是总利润, 量纲不同
    # 改用 EPS 做分母
    fi = api.get_financial_indicator(ts_code)
    if fi.empty or 'eps' not in fi.columns:
        return None

    fi = fi[fi['end_date'].str.endswith('12-31')].copy()
    fi = fi.drop_duplicates(subset=['end_date'], keep='last')
    fi['year'] = fi['end_date'].str[:4]
    annual_eps = fi.set_index('year')['eps']

    ratios = []
    for y in common:
        eps_val = annual_eps.get(y)
        div_val = annual_div.get(y)
        if eps_val and eps_val > 0 and div_val and div_val > 0:
            ratios.append(div_val / eps_val * 100)

    if len(ratios) < 2:
        return None

    return round(sum(ratios) / len(ratios), 2)
