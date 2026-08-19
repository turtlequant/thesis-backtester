"""
量化因子库

两类因子:

1. 截面因子 (cross_section, 默认):
   compute(df: DataFrame) -> Series
   输入全市场截面数据, 输出同 index 的 Series。
   按交易日存储, 每日增量计算。

2. 时序因子 (timeseries):
   compute(ts_code: str, api) -> float|None
   输入单股票代码 + api 模块, 读取历史数据, 输出单一数值。
   每只股票跑一次, 结果是 ts_code → value 的静态属性。

文件约定:
    factors/
      dv.py              # 截面因子 (默认 type)
      profit_growth_5y.py # 时序因子 (META['type'] = 'timeseries')
    strategies/xxx/factors/
      my_factor.py        # 策略私有因子

META 字典:
    {
        'id': 'profit_growth_5y',
        'name': '5年利润增速(%)',
        'type': 'timeseries',          # 'cross_section'(默认) 或 'timeseries'
        'description': '近5年归母净利润CAGR',
        'data_needed': ['income'],
    }

截面因子 compute:
    def compute(df: pd.DataFrame) -> pd.Series:
        '''输入全市场 DataFrame, 返回同 index 的 Series'''
        return df['n_cashflow_act'] / df['total_mv']

时序因子 compute:
    def compute(ts_code: str, api) -> float:
        '''输入股票代码和api模块, 返回单一数值'''
        inc = api.get_income(ts_code)
        # ... 计算逻辑
        return 15.3
"""
