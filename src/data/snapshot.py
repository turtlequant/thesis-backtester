"""
时间点快照生成器

核心模块：给定股票代码和截止日期，生成该时间点下可获取的全部数据快照。

时间边界规则（Layer 1 - 数据层硬过滤）：
  - 财报：按 ann_date（公告日期）过滤，不是 end_date（报告期）
  - 股价：trade_date <= cutoff_date
  - 分红：ann_date <= cutoff_date
  - 股东：ann_date <= cutoff_date

用法:
    python -m src.data.snapshot 601288.SH 2024-06-30
"""
import json
import hashlib
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
    stock_name = api.get_stock_name(ts_code) or ts_code
    snapshot = StockSnapshot(
        ts_code=ts_code,
        stock_name=stock_name,
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

    # ==================== 基本面数据（按公告日期过滤）====================

    # 获取披露日期表，用于确定哪些报告在截止日前已公开
    disclosure_df = api.get_disclosure_dates(ts_code)

    # 资产负债表
    bs = api.get_balancesheet(ts_code)
    if not bs.empty:
        bs = _filter_by_announcement_date(bs, cutoff_date, disclosure_df)
        snapshot.balancesheet = bs
        if not bs.empty:
            snapshot.data_sources.append('balancesheet')

    # 利润表
    inc = api.get_income(ts_code)
    if not inc.empty:
        inc = _filter_by_announcement_date(inc, cutoff_date, disclosure_df)
        snapshot.income = inc
        if not inc.empty:
            snapshot.data_sources.append('income')

    # 现金流量表
    cf = api.get_cashflow(ts_code)
    if not cf.empty:
        cf = _filter_by_announcement_date(cf, cutoff_date, disclosure_df)
        snapshot.cashflow = cf
        if not cf.empty:
            snapshot.data_sources.append('cashflow')

    # 财务指标
    fi = api.get_financial_indicator(ts_code)
    if not fi.empty:
        fi = _filter_by_announcement_date(fi, cutoff_date, disclosure_df)
        snapshot.fina_indicator = fi
        if not fi.empty:
            snapshot.data_sources.append('fina_indicator')

    # 分红数据（按公告日期过滤）
    div = api.get_dividend(ts_code)
    if not div.empty:
        if 'ann_date' in div.columns:
            div = div[div['ann_date'] <= cutoff_date]
        snapshot.dividend = div
        if not div.empty:
            snapshot.data_sources.append('dividend')

    # 前十大股东（按公告日期过滤）
    holders = api.get_top10_holders(ts_code)
    if not holders.empty:
        if 'ann_date' in holders.columns:
            holders = holders[holders['ann_date'] <= cutoff_date]
        snapshot.top10_holders = holders
        if not holders.empty:
            snapshot.data_sources.append('top10_holders')

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
