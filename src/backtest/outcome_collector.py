"""
实际结果采集器

采集分析截面日期之后的实际价格变动，用于评估分析质量。

采集内容：
  - 截面后3/6/12个月的实际收益率
  - 期间最大回撤
  - 实际分红情况
  - 关键事件（如有）

用法:
    python -m src.backtest.outcome_collector 601288.SH 2024-06-30
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

import pandas as pd

from src.data import api
from src.data.settings import ANALYSIS_DB_PATH
from src.analyzer.analysis_runner import init_db


@dataclass
class ForwardOutcome:
    """截面后实际结果"""
    ts_code: str
    cutoff_date: str
    cutoff_price: float = 0.0

    # 前向收益率
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_6m: Optional[float] = None
    return_12m: Optional[float] = None

    # 前向价格
    price_1m: Optional[float] = None
    price_3m: Optional[float] = None
    price_6m: Optional[float] = None
    price_12m: Optional[float] = None

    # 期间统计
    max_drawdown_6m: Optional[float] = None   # 6个月内最大回撤
    max_gain_6m: Optional[float] = None       # 6个月内最大涨幅
    volatility_6m: Optional[float] = None     # 6个月日收益波动率

    # 分红
    actual_dividends: float = 0.0  # 期间实际分红（每股）

    # 数据可用性
    data_available_months: int = 0
    collection_date: str = ""


def _add_months(date_str: str, months: int) -> str:
    """日期加N个月（近似），返回 YYYY-MM-DD 格式"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    target = dt + timedelta(days=months * 30)
    return target.strftime("%Y-%m-%d")


def _find_nearest_trade_date(
    daily: pd.DataFrame,
    target_date: str,
    direction: str = "forward",
    max_offset: int = 10,
) -> Optional[str]:
    """
    找到最近的交易日

    Args:
        daily: 日线数据（含trade_date列，格式YYYY-MM-DD）
        target_date: 目标日期（YYYY-MM-DD格式）
        direction: "forward"向后找, "backward"向前找
        max_offset: 最大偏移天数
    """
    dates = sorted(daily['trade_date'].unique())
    if not dates:
        return None

    if direction == "forward":
        candidates = [d for d in dates if d >= target_date]
        return candidates[0] if candidates else None
    else:
        candidates = [d for d in dates if d <= target_date]
        return candidates[-1] if candidates else None


def collect_forward_outcome(
    ts_code: str,
    cutoff_date: str,
) -> ForwardOutcome:
    """
    采集截面日期后的实际结果

    Args:
        ts_code: 股票代码
        cutoff_date: 截止日期（YYYY-MM-DD）

    Returns:
        ForwardOutcome 实际结果
    """
    outcome = ForwardOutcome(
        ts_code=ts_code,
        cutoff_date=cutoff_date,
        collection_date=datetime.now().strftime("%Y-%m-%d"),
    )

    # 获取截面后12个月的日线数据（使用 YYYY-MM-DD 格式）
    end_date = _add_months(cutoff_date, 13)  # 多取1个月余量
    start_date = (datetime.strptime(cutoff_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")

    daily = api.get_daily(start_date, end_date, ts_code=ts_code)
    if daily.empty:
        print(f"  警告: {ts_code} 无日线数据 ({start_date}~{end_date})")
        return outcome

    # 找到截面日的收盘价（向前找最近交易日）
    cutoff_trade = _find_nearest_trade_date(daily, cutoff_date, direction="backward")
    if not cutoff_trade:
        print(f"  警告: 找不到 {cutoff_date} 附近的交易日")
        return outcome

    cutoff_row = daily[daily['trade_date'] == cutoff_trade].iloc[0]
    outcome.cutoff_price = float(cutoff_row['close'])

    # 截面后的数据
    forward_daily = daily[daily['trade_date'] > cutoff_trade].sort_values('trade_date')
    if forward_daily.empty:
        print(f"  警告: {cutoff_date} 之后无交易数据")
        return outcome

    # 计算可用月数
    last_date = forward_daily['trade_date'].max()
    days_available = (datetime.strptime(last_date, "%Y-%m-%d") - datetime.strptime(cutoff_trade, "%Y-%m-%d")).days
    outcome.data_available_months = days_available // 30

    # 各时间窗口的收益率
    for months, attr_return, attr_price in [
        (1, 'return_1m', 'price_1m'),
        (3, 'return_3m', 'price_3m'),
        (6, 'return_6m', 'price_6m'),
        (12, 'return_12m', 'price_12m'),
    ]:
        target = _add_months(cutoff_date, months)
        trade_date = _find_nearest_trade_date(forward_daily, target, direction="backward")
        if trade_date:
            price = float(forward_daily[forward_daily['trade_date'] == trade_date].iloc[0]['close'])
            ret = (price - outcome.cutoff_price) / outcome.cutoff_price
            setattr(outcome, attr_return, ret)
            setattr(outcome, attr_price, price)

    # 6个月内最大回撤和最大涨幅
    target_6m = _add_months(cutoff_date, 6)
    data_6m = forward_daily[forward_daily['trade_date'] <= target_6m]
    if not data_6m.empty:
        prices = data_6m['close'].values
        # 最大回撤
        peak = prices[0]
        max_dd = 0
        for p in prices:
            if p > peak:
                peak = p
            dd = (peak - p) / peak
            if dd > max_dd:
                max_dd = dd
        outcome.max_drawdown_6m = max_dd

        # 最大涨幅（相对截面价）
        outcome.max_gain_6m = (float(prices.max()) - outcome.cutoff_price) / outcome.cutoff_price

        # 波动率
        returns = data_6m['close'].pct_change().dropna()
        if len(returns) > 5:
            outcome.volatility_6m = float(returns.std())

    # 实际分红
    try:
        dividends = api.get_dividend(ts_code)
        if not dividends.empty and 'ex_date' in dividends.columns:
            end_12m = _add_months(cutoff_date, 12)
            period_div = dividends[
                (dividends['ex_date'] > cutoff_date.replace('-', '')) &
                (dividends['ex_date'] <= end_12m.replace('-', ''))
            ]
            if not period_div.empty and 'cash_div_tax' in period_div.columns:
                outcome.actual_dividends = float(period_div['cash_div_tax'].sum())
    except Exception:
        pass  # 分红数据非关键

    return outcome


def collect_outcomes_for_run(run_id: str) -> Optional[ForwardOutcome]:
    """
    为已有分析采集实际结果

    Args:
        run_id: 分析运行ID
    """
    init_db()
    conn = sqlite3.connect(str(ANALYSIS_DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT ts_code, cutoff_date FROM analysis_runs WHERE id=?",
        (run_id,)
    ).fetchone()
    conn.close()

    if not row:
        print(f"找不到分析任务: {run_id}")
        return None

    ts_code = row['ts_code']
    cutoff_date = row['cutoff_date']

    print(f"采集实际结果: {ts_code} @ {cutoff_date}")
    outcome = collect_forward_outcome(ts_code, cutoff_date)

    # 保存到数据库
    save_outcome(run_id, outcome)
    return outcome


def save_outcome(run_id: str, outcome: ForwardOutcome):
    """保存实际结果到数据库"""
    init_db()
    conn = sqlite3.connect(str(ANALYSIS_DB_PATH))

    # 检查是否已有记录
    existing = conn.execute(
        "SELECT id FROM backtest_outcomes WHERE run_id=?", (run_id,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE backtest_outcomes SET "
            "actual_return_3m=?, actual_return_6m=?, actual_return_12m=?, "
            "quality_detail=? WHERE run_id=?",
            (
                outcome.return_3m,
                outcome.return_6m,
                outcome.return_12m,
                _outcome_to_json(outcome),
                run_id,
            )
        )
    else:
        import uuid
        conn.execute(
            "INSERT INTO backtest_outcomes "
            "(id, run_id, actual_return_3m, actual_return_6m, actual_return_12m, quality_detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex[:16],
                run_id,
                outcome.return_3m,
                outcome.return_6m,
                outcome.return_12m,
                _outcome_to_json(outcome),
            )
        )

    conn.commit()
    conn.close()


def _outcome_to_json(outcome: ForwardOutcome) -> str:
    """序列化实际结果为JSON"""
    import json
    d = {
        'cutoff_price': outcome.cutoff_price,
        'return_1m': outcome.return_1m,
        'return_3m': outcome.return_3m,
        'return_6m': outcome.return_6m,
        'return_12m': outcome.return_12m,
        'price_1m': outcome.price_1m,
        'price_3m': outcome.price_3m,
        'price_6m': outcome.price_6m,
        'price_12m': outcome.price_12m,
        'max_drawdown_6m': outcome.max_drawdown_6m,
        'max_gain_6m': outcome.max_gain_6m,
        'volatility_6m': outcome.volatility_6m,
        'actual_dividends': outcome.actual_dividends,
        'data_available_months': outcome.data_available_months,
        'collection_date': outcome.collection_date,
    }
    return json.dumps(d, ensure_ascii=False)


def format_outcome(outcome: ForwardOutcome) -> str:
    """格式化实际结果为可读文本"""
    lines = [
        f"## 实际结果: {outcome.ts_code} @ {outcome.cutoff_date}",
        "",
        f"**截面价格**: {outcome.cutoff_price:.2f}元",
        f"**数据可用月数**: {outcome.data_available_months}个月",
        "",
        "### 前向收益率",
        "",
        "| 时间窗口 | 收益率 | 价格 |",
        "|---------|--------|------|",
    ]

    for label, ret, price in [
        ("1个月", outcome.return_1m, outcome.price_1m),
        ("3个月", outcome.return_3m, outcome.price_3m),
        ("6个月", outcome.return_6m, outcome.price_6m),
        ("12个月", outcome.return_12m, outcome.price_12m),
    ]:
        ret_str = f"{ret*100:+.1f}%" if ret is not None else "N/A"
        price_str = f"{price:.2f}" if price is not None else "N/A"
        lines.append(f"| {label} | {ret_str} | {price_str} |")

    if outcome.max_drawdown_6m is not None:
        lines.extend([
            "",
            "### 期间统计（6个月）",
            f"- **最大回撤**: {outcome.max_drawdown_6m*100:.1f}%",
            f"- **最大涨幅**: {outcome.max_gain_6m*100:.1f}%" if outcome.max_gain_6m else "",
            f"- **日波动率**: {outcome.volatility_6m*100:.2f}%" if outcome.volatility_6m else "",
        ])

    if outcome.actual_dividends > 0:
        div_yield = outcome.actual_dividends / outcome.cutoff_price * 100
        lines.extend([
            "",
            f"### 实际分红: {outcome.actual_dividends:.4f}元/股 (股息率 {div_yield:.2f}%)",
        ])

    return '\n'.join(lines)


# ==================== CLI ====================

def main():
    import sys
    if len(sys.argv) < 3:
        print("用法: python -m src.backtest.outcome_collector <ts_code> <cutoff_date>")
        print("示例: python -m src.backtest.outcome_collector 601288.SH 2024-06-30")
        sys.exit(1)

    ts_code = sys.argv[1]
    cutoff_date = sys.argv[2]

    outcome = collect_forward_outcome(ts_code, cutoff_date)
    print(format_outcome(outcome))


if __name__ == '__main__':
    main()
