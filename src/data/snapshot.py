"""
时间点快照生成器

给定股票代码和截止日期，生成该时间点下可获取的全部数据快照。
快照严格按公告日期过滤，杜绝前视偏差，供 Agent 盲测分析使用。

时间边界规则（Layer 1 - 数据层硬过滤）：
  - 财报：按 ann_date（公告日期）过滤，不是 end_date（报告期）
  - 股价：trade_date <= cutoff_date
  - 分红：ann_date <= cutoff_date
  - 股东：ann_date <= cutoff_date

CLI:
    python -m src.data.snapshot 601288.SH 2024-06-30          # 生成快照并保存
    python -m src.data.snapshot 601288.SH 2024-06-30 --blind  # 盲测模式（隐藏公司名称）

Python:
    from src.data.snapshot import create_snapshot, snapshot_to_markdown
    snap = create_snapshot('601288.SH', '2024-06-30')
    md = snapshot_to_markdown(snap, blind_mode=True)
"""
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd

from . import api
from .settings import SNAPSHOT_DIR


@dataclass
class StockSnapshot:
    """时间点数据快照"""
    ts_code: str
    stock_name: str
    cutoff_date: str
    generated_at: str
    industry: str = ''
    area: str = ''
    list_date: str = ''

    # 行情数据
    price_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    daily_indicators: pd.DataFrame = field(default_factory=pd.DataFrame)

    # 基本面数据
    balancesheet: pd.DataFrame = field(default_factory=pd.DataFrame)
    income: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow: pd.DataFrame = field(default_factory=pd.DataFrame)
    fina_indicator: pd.DataFrame = field(default_factory=pd.DataFrame)
    dividend: pd.DataFrame = field(default_factory=pd.DataFrame)
    top10_holders: pd.DataFrame = field(default_factory=pd.DataFrame)
    top10_floatholders: pd.DataFrame = field(default_factory=pd.DataFrame)

    # 治理与风险数据
    fina_audit: pd.DataFrame = field(default_factory=pd.DataFrame)
    fina_mainbz: pd.DataFrame = field(default_factory=pd.DataFrame)
    pledge_stat: pd.DataFrame = field(default_factory=pd.DataFrame)
    stk_holdernumber: pd.DataFrame = field(default_factory=pd.DataFrame)
    stk_holdertrade: pd.DataFrame = field(default_factory=pd.DataFrame)
    share_float: pd.DataFrame = field(default_factory=pd.DataFrame)
    repurchase: pd.DataFrame = field(default_factory=pd.DataFrame)

    # 实时增强数据（live-analyze 专用，回测时为空）
    news: pd.DataFrame = field(default_factory=pd.DataFrame)            # 最新新闻
    fund_flow: pd.DataFrame = field(default_factory=pd.DataFrame)       # 主力资金流
    index_daily: pd.DataFrame = field(default_factory=pd.DataFrame)     # 大盘指数行情
    industry_summary: pd.DataFrame = field(default_factory=pd.DataFrame)# 行业板块汇总

    # 元数据
    latest_report_period: str = ''
    data_sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def snapshot_id(self) -> str:
        """唯一标识"""
        raw = f"{self.ts_code}_{self.cutoff_date}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


def create_snapshot(
    ts_code: str,
    cutoff_date: str,
    price_lookback_days: int = 365 * 3,
) -> StockSnapshot:
    """
    生成时间点数据快照

    Args:
        ts_code: 股票代码，如 '601288.SH'
        cutoff_date: 截止日期，如 '2024-06-30'
        price_lookback_days: 行情回看天数，默认3年

    Returns:
        StockSnapshot 包含截止日期前所有可用数据
    """
    # 从 stock_list 一次性获取名称、行业、地区（避免重复读盘）
    stock_name, industry, area, list_date = ts_code, '', '', ''
    stock_list = api.get_stock_list(only_active=False)
    if not stock_list.empty:
        row = stock_list[stock_list['ts_code'] == ts_code]
        if not row.empty:
            r = row.iloc[0]
            stock_name = str(r.get('name', ts_code)) if pd.notna(r.get('name')) else ts_code
            industry = str(r.get('industry', '')) if pd.notna(r.get('industry')) else ''
            area = str(r.get('area', '')) if pd.notna(r.get('area')) else ''
            list_date = str(r.get('list_date', '')) if pd.notna(r.get('list_date')) else ''

    snapshot = StockSnapshot(
        ts_code=ts_code,
        stock_name=stock_name,
        industry=industry,
        area=area,
        list_date=list_date,
        cutoff_date=cutoff_date,
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )

    # ==================== 行情数据 ====================
    price_start = (pd.to_datetime(cutoff_date) - pd.Timedelta(days=price_lookback_days)).strftime('%Y-%m-%d')

    snapshot.price_history = api.get_daily(price_start, cutoff_date, ts_code=ts_code)
    if not snapshot.price_history.empty:
        snapshot.data_sources.append('daily_price')

    snapshot.daily_indicators = api.get_daily_indicator(price_start, cutoff_date, ts_code=ts_code)
    if not snapshot.daily_indicators.empty:
        snapshot.data_sources.append('daily_indicator')

    # ==================== 基本面数据（并行加载 + 按公告日期过滤）====================

    # 并行读取所有财务 parquet 文件（I/O 密集，线程池加速）
    _fin_loaders = {
        'disclosure_dates': lambda: api.get_disclosure_dates(ts_code),
        'balancesheet': lambda: api.get_balancesheet(ts_code),
        'income': lambda: api.get_income(ts_code),
        'cashflow': lambda: api.get_cashflow(ts_code),
        'fina_indicator': lambda: api.get_financial_indicator(ts_code),
        'dividend': lambda: api.get_dividend(ts_code),
        'top10_holders': lambda: api.get_top10_holders(ts_code),
        'top10_floatholders': lambda: api.get_top10_floatholders(ts_code),
        'fina_audit': lambda: api.get_fina_audit(ts_code, end_date=cutoff_date),
        'fina_mainbz': lambda: api.get_fina_mainbz(ts_code, end_date=cutoff_date),
        'pledge_stat': lambda: api.get_pledge_stat(ts_code, end_date=cutoff_date),
        'stk_holdernumber': lambda: api.get_stk_holdernumber(ts_code, end_date=cutoff_date),
        'stk_holdertrade': lambda: api.get_stk_holdertrade(ts_code),
        'share_float': lambda: api.get_share_float(ts_code),
        'repurchase': lambda: api.get_repurchase(ts_code),
    }
    _fin_data = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {k: executor.submit(fn) for k, fn in _fin_loaders.items()}
        for k, fut in futures.items():
            try:
                _fin_data[k] = fut.result()
            except Exception:
                _fin_data[k] = pd.DataFrame()

    disclosure_df = _fin_data['disclosure_dates']

    # 需要按公告日期过滤的财报
    for attr, key in [('balancesheet', 'balancesheet'), ('income', 'income'),
                      ('cashflow', 'cashflow'), ('fina_indicator', 'fina_indicator')]:
        df = _fin_data[key]
        if not df.empty:
            df = _filter_by_announcement_date(df, cutoff_date, disclosure_df)
        setattr(snapshot, attr, df)
        if not df.empty:
            snapshot.data_sources.append(key)

    # 按 ann_date 过滤的数据
    for attr, key, date_col in [
        ('dividend', 'dividend', 'ann_date'),
        ('top10_holders', 'top10_holders', 'ann_date'),
        ('top10_floatholders', 'top10_floatholders', 'ann_date'),
        ('fina_audit', 'fina_audit', 'ann_date'),
        ('stk_holdernumber', 'stk_holdernumber', 'ann_date'),
        ('stk_holdertrade', 'stk_holdertrade', 'ann_date'),
        ('repurchase', 'repurchase', 'ann_date'),
        ('share_float', 'share_float', 'float_date'),
    ]:
        df = _fin_data[key]
        if not df.empty:
            if date_col in df.columns:
                df = df[df[date_col] <= cutoff_date]
            elif 'end_date' in df.columns:
                # 兜底: 用 end_date 过滤，防止未来数据泄露
                df = df[df['end_date'] <= cutoff_date.replace('-', '')]
        setattr(snapshot, attr, df)
        if not df.empty:
            snapshot.data_sources.append(key)

    # 无需日期过滤的数据
    for attr, key in [('fina_mainbz', 'fina_mainbz'), ('pledge_stat', 'pledge_stat')]:
        df = _fin_data[key]
        setattr(snapshot, attr, df)
        if not df.empty:
            snapshot.data_sources.append(key)

    # ==================== 元数据 ====================
    if not snapshot.balancesheet.empty:
        snapshot.latest_report_period = snapshot.balancesheet['end_date'].max()

    # 警告检查
    if snapshot.price_history.empty:
        snapshot.warnings.append("无行情数据")
    if snapshot.balancesheet.empty:
        snapshot.warnings.append("无资产负债表数据")
    if snapshot.income.empty:
        snapshot.warnings.append("无利润表数据")

    return snapshot


def _filter_by_announcement_date(
    df: pd.DataFrame,
    cutoff_date: str,
    disclosure_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    按公告日期过滤财报数据（时间边界核心逻辑）

    优先使用 ann_date/f_ann_date，若缺失则通过 disclosure_date 表查找
    """
    if df.empty:
        return df

    # 优先用 f_ann_date（首次公告日），其次 ann_date
    ann_col = None
    if 'f_ann_date' in df.columns and df['f_ann_date'].notna().any():
        ann_col = 'f_ann_date'
    elif 'ann_date' in df.columns and df['ann_date'].notna().any():
        ann_col = 'ann_date'

    if ann_col:
        # 直接按公告日期过滤
        mask = df[ann_col].notna() & (df[ann_col] <= cutoff_date)
        return df[mask].reset_index(drop=True)

    # 回退：通过 disclosure_date 表关联
    if not disclosure_df.empty and 'end_date' in df.columns:
        # disclosure_df 有 end_date 和 actual_date（实际披露日）
        disc_map = {}
        for _, row in disclosure_df.iterrows():
            actual = row.get('actual_date') or row.get('ann_date')
            if pd.notna(actual) and pd.notna(row.get('end_date')):
                disc_map[row['end_date']] = actual

        mask = df['end_date'].map(lambda x: disc_map.get(x, '9999-12-31')) <= cutoff_date
        return df[mask].reset_index(drop=True)

    # 最终回退：保守策略，只保留报告期在截止日6个月前的数据
    if 'end_date' in df.columns:
        safe_cutoff = (pd.to_datetime(cutoff_date) - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
        return df[df['end_date'] <= safe_cutoff].reset_index(drop=True)

    return df


# ==================== 股东匿名化 ====================

# 国资/政府相关关键词
_SOE_KEYWORDS = [
    '国资委', '财政部', '国有', '汇金', '中央', '省政府', '市政府',
    '国资', '财政厅', '管委会', '人民政府', '国务院',
]

# 机构投资者关键词
_INSTITUTION_KEYWORDS = [
    '基金', '保险', '证券', '银行', '信托', '资管', '投资',
    '社保', '养老', 'QFII', 'RQFII', '陆股通', '港股通',
]


def _classify_holder(name: str) -> str:
    """将股东名称匿名化为属性标签，保留国企判定所需信息"""
    if not name:
        return "未知"
    for kw in _SOE_KEYWORDS:
        if kw in name:
            return "国有/政府关联股东"
    for kw in _INSTITUTION_KEYWORDS:
        if kw in name:
            return "机构投资者"
    # 个人股东通常是2-4个汉字
    if len(name) <= 4 and all('\u4e00' <= c <= '\u9fff' for c in name):
        return "自然人股东"
    return "其他法人股东"


# ==================== 格式化输出 ====================

def snapshot_to_markdown(snapshot: StockSnapshot, blind_mode: bool = False) -> str:
    """将快照转为 Markdown 格式，供 AI 分析使用

    Args:
        snapshot: 数据快照
        blind_mode: 盲测模式，隐藏公司名称和可识别信息
    """
    lines = []
    if blind_mode:
        lines.append("# 标的公司数据快照")
    else:
        lines.append(f"# {snapshot.stock_name}（{snapshot.ts_code}）数据快照")
    lines.append(f"")
    lines.append(f"**截止日期**: {snapshot.cutoff_date}")
    if snapshot.industry:
        lines.append(f"**所属行业**: {snapshot.industry}")
    if snapshot.area:
        lines.append(f"**所在地区**: {snapshot.area}")
    if snapshot.list_date:
        lines.append(f"**上市日期**: {snapshot.list_date}")
    lines.append(f"**最新报告期**: {snapshot.latest_report_period}")
    lines.append(f"**数据源**: {', '.join(snapshot.data_sources)}")
    if snapshot.warnings:
        lines.append(f"**警告**: {'; '.join(snapshot.warnings)}")
    lines.append(f"")

    # 最新行情
    if not snapshot.price_history.empty:
        lines.append("## 行情概览")
        ph = snapshot.price_history
        latest = ph.iloc[-1]
        lines.append(f"- 最新收盘价: {latest.get('close', 'N/A')}")
        lines.append(f"- 最新日期: {latest.get('trade_date', 'N/A')}")

        # 价格位置
        high_52w = ph.tail(250)['high'].max() if len(ph) >= 250 else ph['high'].max()
        low_52w = ph.tail(250)['low'].min() if len(ph) >= 250 else ph['low'].min()
        close = latest.get('close', 0)
        if high_52w > low_52w:
            position = (close - low_52w) / (high_52w - low_52w) * 100
            lines.append(f"- 52周高点: {high_52w:.2f}")
            lines.append(f"- 52周低点: {low_52w:.2f}")
            lines.append(f"- 价格位置: {position:.1f}%（0%=最低，100%=最高）")
        lines.append("")

    # 最新估值指标
    if not snapshot.daily_indicators.empty:
        lines.append("## 估值指标（最新交易日）")
        di = snapshot.daily_indicators.iloc[-1]
        for col, label in [
            ('pe_ttm', 'PE(TTM)'), ('pb', 'PB'), ('ps_ttm', 'PS(TTM)'),
            ('dv_ratio', '股息率(%)'), ('dv_ttm', '股息率TTM(%)'),
            ('total_mv', '总市值(万元)'), ('circ_mv', '流通市值(万元)'),
        ]:
            val = di.get(col)
            if pd.notna(val):
                if col in ('total_mv', 'circ_mv'):
                    lines.append(f"- {label}: {val/10000:.2f}亿")
                else:
                    lines.append(f"- {label}: {val:.2f}")
        lines.append("")

    # 财报数据
    if not snapshot.balancesheet.empty:
        lines.append("## 资产负债表（最近报告期）")
        lines.append(_format_financial_table(
            snapshot.balancesheet,
            key_cols=[
                ('total_assets', '总资产'), ('total_liab', '总负债'),
                ('total_hldr_eqy_exc_min_int', '归母净资产'),
                ('money_cap', '货币资金'), ('accounts_receiv', '应收账款'),
                ('inventories', '存货'), ('fix_assets', '固定资产'),
                ('lt_borr', '长期借款'), ('st_borr', '短期借款'),
                ('bond_payable', '应付债券'),
            ],
            n_periods=4,
        ))

    if not snapshot.income.empty:
        lines.append("## 利润表（最近报告期）")
        lines.append(_format_financial_table(
            snapshot.income,
            key_cols=[
                ('revenue', '营业收入'), ('oper_cost', '营业成本'),
                ('operate_profit', '营业利润'), ('n_income', '净利润'),
                ('n_income_attr_p', '归母净利润'),
                ('basic_eps', '基本每股收益'),
                ('finance_exp', '财务费用'), ('impair_ttl_am', '资产减值损失'),
            ],
            n_periods=4,
        ))

    if not snapshot.cashflow.empty:
        lines.append("## 现金流量表（最近报告期）")
        lines.append(_format_financial_table(
            snapshot.cashflow,
            key_cols=[
                ('n_cashflow_act', '经营活动现金流净额'),
                ('n_cashflow_inv_act', '投资活动现金流净额'),
                ('n_cash_flows_fnc_act', '筹资活动现金流净额'),
                ('c_pay_acq_const_fixa', '购建固定资产支出(CAPEX)'),
                ('free_cashflow', '自由现金流'),
            ],
            n_periods=4,
        ))

    # 财务指标
    if not snapshot.fina_indicator.empty:
        lines.append("## 核心财务指标（最近报告期）")
        lines.append(_format_financial_table(
            snapshot.fina_indicator,
            key_cols=[
                ('roe', 'ROE(%)'), ('roe_dt', '扣非ROE(%)'),
                ('grossprofit_margin', '毛利率(%)'),
                ('netprofit_margin', '净利率(%)'),
                ('debt_to_assets', '资产负债率(%)'),
                ('current_ratio', '流动比率'),
                ('quick_ratio', '速动比率'),
                ('ocfps', '每股经营现金流'),
                ('bps', '每股净资产'),
            ],
            n_periods=4,
        ))

    # 分红
    if not snapshot.dividend.empty:
        lines.append("## 分红历史")
        div = snapshot.dividend.tail(10)  # 最近10次
        lines.append("| 年度 | 每股派息(元) | 公告日 | 除权日 |")
        lines.append("|------|-------------|--------|--------|")
        for _, row in div.iterrows():
            cash_div = row.get('cash_div', 0)
            if pd.notna(cash_div) and cash_div > 0:
                lines.append(
                    f"| {row.get('end_date', 'N/A')[:4]} "
                    f"| {cash_div:.4f} "
                    f"| {row.get('ann_date', 'N/A')} "
                    f"| {row.get('ex_date', 'N/A')} |"
                )
        lines.append("")

    # 前十大股东
    if not snapshot.top10_holders.empty:
        # 取最新一期
        latest_period = snapshot.top10_holders['end_date'].max()
        holders = snapshot.top10_holders[snapshot.top10_holders['end_date'] == latest_period]
        lines.append(f"## 前十大股东（{latest_period}）")
        if blind_mode:
            lines.append("| 排名 | 股东属性 | 持股比例(%) | 持股数量 |")
            lines.append("|------|---------|------------|---------|")
            for i, (_, row) in enumerate(holders.head(10).iterrows(), 1):
                name = row.get('holder_name', '')
                ratio = row.get('hold_ratio', 0)
                amount = row.get('hold_amount', 0)
                attr = _classify_holder(name)
                lines.append(f"| {i} | {attr} | {ratio:.2f} | {amount:,.0f} |")
        else:
            lines.append("| 排名 | 股东名称 | 持股比例(%) | 持股数量 |")
            lines.append("|------|---------|------------|---------|")
            for i, (_, row) in enumerate(holders.head(10).iterrows(), 1):
                name = row.get('holder_name', 'N/A')
                ratio = row.get('hold_ratio', 0)
                amount = row.get('hold_amount', 0)
                lines.append(f"| {i} | {name} | {ratio:.2f} | {amount:,.0f} |")
        lines.append("")

    # 前十大流通股东
    if not snapshot.top10_floatholders.empty:
        df = snapshot.top10_floatholders
        latest_period = df['end_date'].max() if 'end_date' in df.columns else ''
        holders = df[df['end_date'] == latest_period] if latest_period else df
        lines.append(f"## 前十大流通股东（{latest_period}）")
        if blind_mode:
            lines.append("| 排名 | 股东属性 | 持股数量 |")
            lines.append("|------|---------|---------|")
            for i, (_, row) in enumerate(holders.head(10).iterrows(), 1):
                attr = _classify_holder(row.get('holder_name', ''))
                amount = row.get('hold_amount', 0)
                lines.append(f"| {i} | {attr} | {amount:,.0f} |")
        else:
            lines.append("| 排名 | 股东名称 | 持股数量 |")
            lines.append("|------|---------|---------|")
            for i, (_, row) in enumerate(holders.head(10).iterrows(), 1):
                lines.append(f"| {i} | {row.get('holder_name', 'N/A')} | {row.get('hold_amount', 0):,.0f} |")
        lines.append("")

    # 审计意见
    if not snapshot.fina_audit.empty:
        lines.append("## 审计意见")
        audit = snapshot.fina_audit.drop_duplicates(subset=['end_date'], keep='last')
        audit = audit.sort_values('end_date', ascending=False).head(4)
        lines.append("| 报告期 | 审计结果 | 审计机构 |")
        lines.append("|--------|---------|---------|")
        for _, row in audit.iterrows():
            lines.append(
                f"| {row.get('end_date', 'N/A')} "
                f"| {row.get('audit_result', 'N/A')} "
                f"| {row.get('audit_agency', 'N/A')} |"
            )
        lines.append("")

    # 主营业务构成
    if not snapshot.fina_mainbz.empty:
        df = snapshot.fina_mainbz
        latest_period = df['end_date'].max()
        latest = df[df['end_date'] == latest_period]
        lines.append(f"## 主营业务构成（{latest_period}）")
        lines.append("| 业务/地区 | 营业收入 | 营业成本 | 毛利率 |")
        lines.append("|----------|---------|---------|-------|")
        for _, row in latest.iterrows():
            item = row.get('bz_item', 'N/A')
            sales = row.get('bz_sales', 0)
            cost = row.get('bz_cost', 0)
            margin = ''
            if pd.notna(sales) and pd.notna(cost) and float(sales) > 0:
                margin = f"{(1 - float(cost)/float(sales))*100:.1f}%"
            sales_str = f"{float(sales)/1e8:.2f}亿" if pd.notna(sales) and abs(float(sales)) >= 1e4 else str(sales)
            cost_str = f"{float(cost)/1e8:.2f}亿" if pd.notna(cost) and abs(float(cost)) >= 1e4 else str(cost)
            lines.append(f"| {item} | {sales_str} | {cost_str} | {margin} |")
        lines.append("")

    # 股权质押
    if not snapshot.pledge_stat.empty:
        lines.append("## 股权质押统计")
        pledge = snapshot.pledge_stat.sort_values('end_date', ascending=False).head(4)
        lines.append("| 日期 | 质押次数 | 质押比例(%) |")
        lines.append("|------|---------|-----------|")
        for _, row in pledge.iterrows():
            ratio = row.get('pledge_ratio', 0)
            ratio_str = f"{float(ratio):.2f}" if pd.notna(ratio) else 'N/A'
            lines.append(
                f"| {row.get('end_date', 'N/A')} "
                f"| {row.get('pledge_count', 'N/A')} "
                f"| {ratio_str} |"
            )
        lines.append("")

    # 股东人数
    if not snapshot.stk_holdernumber.empty:
        lines.append("## 股东人数变化")
        hn = snapshot.stk_holdernumber.drop_duplicates(subset=['end_date'], keep='last')
        hn = hn.sort_values('end_date', ascending=False).head(6)
        lines.append("| 日期 | 股东人数 | 较上期变化 |")
        lines.append("|------|---------|----------|")
        for _, row in hn.iterrows():
            num = row.get('holder_num', 0)
            change = row.get('holder_num_change')
            try:
                change_str = f"{float(change):+.0f}" if pd.notna(change) and str(change).strip() else ''
            except (ValueError, TypeError):
                change_str = ''
            lines.append(f"| {row.get('end_date', 'N/A')} | {int(num):,} | {change_str} |")
        lines.append("")

    # 股东增减持
    if not snapshot.stk_holdertrade.empty:
        lines.append("## 股东增减持")
        ht = snapshot.stk_holdertrade
        if 'ann_date' in ht.columns:
            ht = ht.sort_values('ann_date', ascending=False).head(10)
        lines.append("| 公告日 | 股东 | 方向 | 变动股数 | 变动比例(%) |")
        lines.append("|--------|------|------|---------|-----------|")
        for _, row in ht.iterrows():
            name = _classify_holder(row.get('holder_name', '')) if blind_mode else row.get('holder_name', 'N/A')
            in_de = row.get('in_de', 'N/A')
            vol = row.get('change_vol', 0)
            vol_str = f"{float(vol):,.0f}" if pd.notna(vol) else 'N/A'
            ratio = row.get('change_ratio', 0)
            ratio_str = f"{float(ratio):.4f}" if pd.notna(ratio) else 'N/A'
            lines.append(f"| {row.get('ann_date', 'N/A')} | {name} | {in_de} | {vol_str} | {ratio_str} |")
        lines.append("")

    # 限售解禁
    if not snapshot.share_float.empty:
        lines.append("## 限售解禁")
        sf = snapshot.share_float
        if 'float_date' in sf.columns:
            sf = sf.sort_values('float_date', ascending=False).head(8)
        lines.append("| 解禁日 | 股东 | 解禁股数 | 解禁比例(%) |")
        lines.append("|--------|------|---------|-----------|")
        for _, row in sf.iterrows():
            name = _classify_holder(row.get('holder_name', '')) if blind_mode else row.get('holder_name', 'N/A')
            share = row.get('float_share', 0)
            share_str = f"{float(share):,.0f}" if pd.notna(share) else 'N/A'
            ratio = row.get('float_ratio', 0)
            ratio_str = f"{float(ratio):.4f}" if pd.notna(ratio) else 'N/A'
            lines.append(f"| {row.get('float_date', 'N/A')} | {name} | {share_str} | {ratio_str} |")
        lines.append("")

    # 股票回购
    if not snapshot.repurchase.empty:
        lines.append("## 股票回购")
        rp = snapshot.repurchase
        if 'ann_date' in rp.columns:
            rp = rp.sort_values('ann_date', ascending=False).head(6)
        lines.append("| 公告日 | 回购数量 | 回购金额 | 价格区间 | 进度 |")
        lines.append("|--------|---------|---------|---------|------|")
        for _, row in rp.iterrows():
            vol = row.get('vol', 0)
            vol_str = f"{float(vol):,.0f}" if pd.notna(vol) else 'N/A'
            amt = row.get('amount', 0)
            amt_str = f"{float(amt)/1e4:.2f}万" if pd.notna(amt) and float(amt) >= 1e4 else str(amt) if pd.notna(amt) else 'N/A'
            low = row.get('low_limit', '')
            high = row.get('high_limit', '')
            price_range = f"{low}-{high}" if pd.notna(low) and pd.notna(high) else 'N/A'
            proc = row.get('proc', 'N/A')
            lines.append(f"| {row.get('ann_date', 'N/A')} | {vol_str} | {amt_str} | {price_range} | {proc} |")
        lines.append("")

    # 时间边界声明
    lines.append("---")
    lines.append(f"> **严格时间边界**: 以上所有数据截止于 **{snapshot.cutoff_date}**。")
    lines.append(f"> 分析时禁止使用任何该日期之后的信息。")
    lines.append(f"> 未出现的数据代表在该时间点不可获取。")
    if blind_mode:
        lines.append(f"> **盲测模式**: 公司名称和股票代码已隐藏，请仅基于提供的数据进行分析。")

    return "\n".join(lines)


def _format_financial_table(
    df: pd.DataFrame,
    key_cols: list,
    n_periods: int = 4,
) -> str:
    """格式化财报数据为 Markdown 表格"""
    if df.empty:
        return "（无数据）\n"

    # 只保留年报和半年报，去重取最新
    df = df.copy()
    if 'end_date' in df.columns:
        df = df.drop_duplicates(subset=['end_date'], keep='last')
        df = df.sort_values('end_date', ascending=False).head(n_periods)
        df = df.sort_values('end_date')

    periods = df['end_date'].tolist() if 'end_date' in df.columns else []

    if not periods:
        return "（无数据）\n"

    # 构建表格
    lines = []
    header = "| 指标 | " + " | ".join(periods) + " |"
    sep = "|------|" + "|".join(["------"] * len(periods)) + "|"
    lines.append(header)
    lines.append(sep)

    for col, label in key_cols:
        if col not in df.columns:
            continue
        row_vals = []
        for _, row in df.iterrows():
            val = row.get(col)
            if pd.isna(val):
                row_vals.append("N/A")
            elif abs(val) >= 1e8:
                row_vals.append(f"{val/1e8:.2f}亿")
            elif abs(val) >= 1e4:
                row_vals.append(f"{val/1e4:.2f}万")
            else:
                row_vals.append(f"{val:.2f}")
        lines.append(f"| {label} | " + " | ".join(row_vals) + " |")

    lines.append("")

    # ==================== 实时增强数据（仅 live-analyze 时有）====================

    # 最新新闻
    if not snapshot.news.empty:
        lines.append("## 最新新闻")
        for _, row in snapshot.news.iterrows():
            title = row.get('title', '')
            dt = row.get('datetime', '')
            source = row.get('source', '')
            content = str(row.get('content', ''))[:200]
            lines.append(f"- **{title}** ({source}, {dt})")
            if content:
                lines.append(f"  {content}")
        lines.append("")

    # 主力资金流向
    if not snapshot.fund_flow.empty:
        lines.append("## 近期主力资金流向")
        lines.append("| 日期 | 收盘价 | 涨跌幅 | 主力净流入 | 主力净流入占比 |")
        lines.append("|------|--------|--------|-----------|-------------|")
        for _, row in snapshot.fund_flow.tail(10).iterrows():
            date = row.get('trade_date', '')
            close = row.get('close', 0)
            pct = row.get('pct_chg', 0)
            main_net = row.get('main_net_inflow', 0)
            main_pct = row.get('main_net_inflow_pct', 0)
            main_str = f"{main_net/1e8:.2f}亿" if abs(main_net) >= 1e4 else f"{main_net:.0f}"
            lines.append(f"| {date} | {close} | {pct}% | {main_str} | {main_pct}% |")
        lines.append("")

    # 大盘走势
    if not snapshot.index_daily.empty:
        lines.append("## 大盘走势（沪深300）")
        recent = snapshot.index_daily.tail(5)
        lines.append("| 日期 | 收盘 | 涨跌幅 |")
        lines.append("|------|------|--------|")
        for _, row in recent.iterrows():
            date = row.get('trade_date', '')
            close = row.get('close', 0)
            # 计算涨跌幅
            lines.append(f"| {date} | {close:.2f} | |")
        if len(snapshot.index_daily) >= 20:
            d20 = snapshot.index_daily.iloc[-20]['close']
            d_now = snapshot.index_daily.iloc[-1]['close']
            chg_20d = (d_now - d20) / d20 * 100
            lines.append(f"\n近20日涨跌: {chg_20d:+.1f}%")
        lines.append("")

    # 行业板块
    if not snapshot.industry_summary.empty and snapshot.industry:
        ind_name = snapshot.industry.replace('Ⅱ', '').replace('Ⅲ', '').strip()
        matched = snapshot.industry_summary[
            snapshot.industry_summary['industry'].str.contains(ind_name, na=False)
        ]
        if not matched.empty:
            row = matched.iloc[0]
            lines.append("## 所属行业板块今日表现")
            lines.append(f"- 行业: {row.get('industry', '')}")
            lines.append(f"- 涨跌幅: {row.get('pct_chg', '')}%")
            lines.append(f"- 净流入: {row.get('net_inflow', '')}亿")
            lines.append(f"- 上涨/下跌: {row.get('up_count', '')}/{row.get('down_count', '')}")
            lines.append("")

    return "\n".join(lines)


def save_snapshot(snapshot: StockSnapshot) -> Path:
    """保存快照到本地"""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{snapshot.ts_code}_{snapshot.cutoff_date}.md"
    path = SNAPSHOT_DIR / filename
    path.write_text(snapshot_to_markdown(snapshot), encoding='utf-8')
    return path


# ==================== CLI 入口 ====================

def main():
    import sys
    if len(sys.argv) < 3:
        print("用法: python -m src.data.snapshot <ts_code> <cutoff_date>")
        print("示例: python -m src.data.snapshot 601288.SH 2024-06-30")
        sys.exit(1)

    ts_code = sys.argv[1]
    cutoff_date = sys.argv[2]

    print(f"生成快照: {ts_code} @ {cutoff_date}")
    snapshot = create_snapshot(ts_code, cutoff_date)

    md = snapshot_to_markdown(snapshot)
    print(md)

    path = save_snapshot(snapshot)
    print(f"\n快照已保存: {path}")


if __name__ == '__main__':
    main()
