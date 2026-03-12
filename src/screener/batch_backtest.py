"""
批量筛选回测

在多个截面日期运行量化筛选，采集前向收益，评估筛选策略有效性。
支持通过 StrategyConfig 配置筛选条件和输出路径。

用法:
    python -m src.screener.batch_backtest --top 50
    python -m src.screener.batch_backtest --dates 2023-06-30,2023-12-31,2024-06-30
    python -m src.screener.batch_backtest --strategy strategies/v556_value/strategy.yaml
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, TYPE_CHECKING

import pandas as pd

from src.data import api
from src.backtest.outcome_collector import collect_forward_outcome, ForwardOutcome
from .quick_filter import screen_at_date, ScreenResult

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig


def _resolve_backtest_dir(config: Optional["StrategyConfig"] = None) -> Path:
    if config is not None:
        return config.get_backtest_dir()
    from src.engine.config import get_default_config
    return get_default_config().get_backtest_dir()


def get_default_crosssection_dates(
    start_year: int = 2023,
    end_year: int = 2024,
) -> List[str]:
    """
    生成默认截面日期列表（每半年一个）

    每年取6-30和12-31
    """
    dates = []
    for year in range(start_year, end_year + 1):
        dates.append(f"{year}-06-30")
        dates.append(f"{year}-12-31")
    # 过滤掉未来日期
    today = datetime.now().strftime('%Y-%m-%d')
    dates = [d for d in dates if d <= today]
    return dates


@dataclass
class CrossSectionResult:
    """单截面筛选+前向收益结果"""
    cutoff_date: str
    screen_result: Optional[ScreenResult] = None
    outcomes: Dict[str, ForwardOutcome] = field(default_factory=dict)  # ts_code -> outcome

    @property
    def candidates_with_returns(self) -> pd.DataFrame:
        """合并筛选候选与前向收益"""
        if self.screen_result is None or self.screen_result.candidates.empty:
            return pd.DataFrame()

        df = self.screen_result.candidates.copy()
        # 添加前向收益列
        for months, col in [(1, 'fwd_1m'), (3, 'fwd_3m'), (6, 'fwd_6m'), (12, 'fwd_12m')]:
            df[col] = df['ts_code'].map(
                lambda tc: getattr(self.outcomes.get(tc, ForwardOutcome(tc, self.cutoff_date)),
                                   f'return_{months}m', None)
            )
        df['max_dd_6m'] = df['ts_code'].map(
            lambda tc: getattr(self.outcomes.get(tc, ForwardOutcome(tc, self.cutoff_date)),
                               'max_drawdown_6m', None)
        )
        return df


def run_single_crosssection(
    cutoff_date: str,
    top_n: int = 50,
    collect_outcomes: bool = True,
    config: Optional["StrategyConfig"] = None,
) -> CrossSectionResult:
    """
    运行单个截面的筛选+前向收益采集

    Args:
        cutoff_date: 截面日期
        top_n: 筛选候选数
        collect_outcomes: 是否采集前向收益
    """
    print(f"\n{'='*60}")
    print(f"截面: {cutoff_date}")
    print(f"{'='*60}")

    cs_result = CrossSectionResult(cutoff_date=cutoff_date)

    # 1. 运行筛选
    print(f"\n[1/2] 运行量化筛选...")
    screen = screen_at_date(cutoff_date, top_n=top_n, config=config)
    cs_result.screen_result = screen
    print(f"  {screen.summary}")

    if screen.candidates.empty:
        print("  无候选，跳过前向收益采集")
        return cs_result

    # 2. 采集前向收益
    if collect_outcomes:
        print(f"\n[2/2] 采集前向收益 ({len(screen.candidates)} 只)...")
        for i, (_, row) in enumerate(screen.candidates.iterrows(), 1):
            ts_code = row['ts_code']
            name = row.get('stock_name', ts_code)
            try:
                outcome = collect_forward_outcome(ts_code, cutoff_date)
                cs_result.outcomes[ts_code] = outcome
                ret_6m = f"{outcome.return_6m*100:+.1f}%" if outcome.return_6m is not None else "N/A"
                print(f"  [{i}/{len(screen.candidates)}] {name}: 6m={ret_6m}")
            except Exception as e:
                print(f"  [{i}/{len(screen.candidates)}] {name}: 采集失败 ({e})")
    else:
        print("  跳过前向收益采集")

    return cs_result


def run_batch_backtest(
    dates: List[str] = None,
    top_n: int = 50,
    collect_outcomes: bool = True,
    config: Optional["StrategyConfig"] = None,
) -> List[CrossSectionResult]:
    """
    批量运行多截面筛选回测

    Args:
        dates: 截面日期列表，默认使用2023-2024半年度
        top_n: 每截面候选数
        collect_outcomes: 是否采集前向收益
    """
    if dates is None:
        dates = get_default_crosssection_dates()

    print(f"批量筛选回测: {len(dates)} 个截面, top {top_n}")
    print(f"截面日期: {', '.join(dates)}")

    results = []
    for date in dates:
        cs = run_single_crosssection(date, top_n=top_n, collect_outcomes=collect_outcomes, config=config)
        results.append(cs)

    return results


def generate_report(results: List[CrossSectionResult]) -> str:
    """生成批量回测统计报告"""
    lines = [
        "# 量化筛选策略回测报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**截面数量**: {len(results)}",
        "",
    ]

    # 汇总统计
    lines.append("## 各截面概览")
    lines.append("| 截面日期 | 候选数 | 金龟 | 银龟 | 铜龟 | 6m均收益 | 6m胜率 | 6m均回撤 |")
    lines.append("|----------|--------|------|------|------|----------|--------|----------|")

    all_returns_6m = []

    for cs in results:
        if cs.screen_result is None or cs.screen_result.candidates.empty:
            lines.append(f"| {cs.cutoff_date} | 0 | - | - | - | - | - | - |")
            continue

        df = cs.candidates_with_returns
        n = len(df)
        tc = df['turtle_rating'].value_counts()

        # 6个月收益统计
        valid_6m = df['fwd_6m'].dropna()
        if len(valid_6m) > 0:
            avg_6m = valid_6m.mean() * 100
            win_rate_6m = (valid_6m > 0).mean() * 100
            all_returns_6m.extend(valid_6m.tolist())
        else:
            avg_6m = float('nan')
            win_rate_6m = float('nan')

        # 6个月最大回撤
        valid_dd = df['max_dd_6m'].dropna()
        avg_dd = valid_dd.mean() * 100 if len(valid_dd) > 0 else float('nan')

        avg_6m_str = f"{avg_6m:+.1f}%" if not pd.isna(avg_6m) else "N/A"
        wr_str = f"{win_rate_6m:.0f}%" if not pd.isna(win_rate_6m) else "N/A"
        dd_str = f"{avg_dd:.1f}%" if not pd.isna(avg_dd) else "N/A"

        lines.append(
            f"| {cs.cutoff_date} | {n} "
            f"| {tc.get('金龟', 0)} | {tc.get('银龟', 0)} | {tc.get('铜龟', 0)} "
            f"| {avg_6m_str} | {wr_str} | {dd_str} |"
        )

    # 总体统计
    if all_returns_6m:
        lines.extend([
            "",
            "## 总体统计（6个月前向收益）",
            "",
            f"- **样本数**: {len(all_returns_6m)}",
            f"- **平均收益**: {sum(all_returns_6m)/len(all_returns_6m)*100:+.1f}%",
            f"- **胜率**: {sum(1 for r in all_returns_6m if r > 0)/len(all_returns_6m)*100:.0f}%",
            f"- **中位数**: {sorted(all_returns_6m)[len(all_returns_6m)//2]*100:+.1f}%",
            f"- **最大收益**: {max(all_returns_6m)*100:+.1f}%",
            f"- **最大亏损**: {min(all_returns_6m)*100:+.1f}%",
        ])

    # 按龟级分组统计
    lines.extend(["", "## 按龟级分组统计（6个月前向收益）", ""])
    lines.append("| 龟级 | 样本数 | 平均收益 | 胜率 | 中位数 |")
    lines.append("|------|--------|----------|------|--------|")

    for rating in ['金龟', '银龟', '铜龟', '不达标']:
        rets = []
        for cs in results:
            df = cs.candidates_with_returns
            if df.empty:
                continue
            mask = df['turtle_rating'] == rating
            valid = df.loc[mask, 'fwd_6m'].dropna()
            rets.extend(valid.tolist())

        if rets:
            avg = sum(rets) / len(rets) * 100
            wr = sum(1 for r in rets if r > 0) / len(rets) * 100
            med = sorted(rets)[len(rets) // 2] * 100
            lines.append(f"| {rating} | {len(rets)} | {avg:+.1f}% | {wr:.0f}% | {med:+.1f}% |")

    # 频繁出现的候选
    lines.extend(["", "## 多截面反复入选的股票（出现≥2次）", ""])
    code_counts = {}
    code_names = {}
    code_ratings = {}
    for cs in results:
        if cs.screen_result is None:
            continue
        for _, row in cs.screen_result.candidates.iterrows():
            tc = row['ts_code']
            code_counts[tc] = code_counts.get(tc, 0) + 1
            code_names[tc] = row.get('stock_name', tc)
            code_ratings[tc] = row.get('turtle_rating', '')

    repeat_codes = [(code, cnt) for code, cnt in code_counts.items() if cnt >= 2]
    repeat_codes.sort(key=lambda x: -x[1])

    if repeat_codes:
        lines.append("| 代码 | 名称 | 出现次数 | 最近龟级 |")
        lines.append("|------|------|----------|----------|")
        for code, cnt in repeat_codes[:30]:
            lines.append(f"| {code} | {code_names[code]} | {cnt} | {code_ratings[code]} |")
    else:
        lines.append("（无重复出现的股票）")

    return '\n'.join(lines)


def save_report(results: List[CrossSectionResult], report: str, config: Optional["StrategyConfig"] = None):
    """保存报告和原始数据"""
    bt_dir = _resolve_backtest_dir(config)
    bt_dir.mkdir(parents=True, exist_ok=True)

    # 保存报告
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    report_path = bt_dir / f"screen_backtest_{ts}.md"
    report_path.write_text(report, encoding='utf-8')
    print(f"\n报告已保存: {report_path}")

    # 保存原始数据 (CSV)
    all_rows = []
    for cs in results:
        df = cs.candidates_with_returns
        if not df.empty:
            df = df.copy()
            df['cutoff_date'] = cs.cutoff_date
            all_rows.append(df)

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        csv_path = bt_dir / f"screen_backtest_{ts}.csv"
        combined.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"原始数据已保存: {csv_path}")


# ==================== CLI ====================

def main():
    import sys
    args = sys.argv[1:]

    top_n = 50
    dates = None
    no_outcomes = False
    config = None

    i = 0
    while i < len(args):
        if args[i] == '--top' and i + 1 < len(args):
            top_n = int(args[i + 1])
            i += 2
        elif args[i] == '--dates' and i + 1 < len(args):
            dates = args[i + 1].split(',')
            i += 2
        elif args[i] == '--no-outcomes':
            no_outcomes = True
            i += 1
        elif args[i] == '--strategy' and i + 1 < len(args):
            from src.engine.config import StrategyConfig
            config = StrategyConfig.from_yaml(args[i + 1])
            print(f"使用策略: {config.name}")
            i += 2
        else:
            i += 1

    results = run_batch_backtest(
        dates=dates,
        top_n=top_n,
        collect_outcomes=not no_outcomes,
        config=config,
    )

    report = generate_report(results)
    print(f"\n{'='*60}")
    print(report)
    save_report(results, report, config=config)


if __name__ == '__main__':
    main()
