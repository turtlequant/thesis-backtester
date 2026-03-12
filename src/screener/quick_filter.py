"""
量化快速筛选器

基于日线指标（PE/PB/股息率/市值）对全A股进行快速筛选，
按评级标准打分排序，输出候选池。
支持通过 StrategyConfig 配置不同的筛选条件和评级体系。

用法:
    python -m src.screener.quick_filter 2024-06-30
    python -m src.screener.quick_filter 2024-06-30 --top 50
    python -m src.screener.quick_filter 2024-06-30 --strategy strategies/v556_value/strategy.yaml
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, TYPE_CHECKING

import pandas as pd

from src.data import api

if TYPE_CHECKING:
    from src.engine.config import StrategyConfig


# ==================== 默认值（向后兼容） ====================

GOLD_TURTLE = {'pe_max': 8, 'pb_max': 0.8, 'dv_min': 7.0}
SILVER_TURTLE = {'pe_max': 10, 'pb_max': 1.0, 'dv_min': 5.0}
BRONZE_TURTLE = {'pe_max': 12, 'pb_max': 1.2, 'dv_min': 4.0}

MIN_MARKET_CAP = 100  # 最低总市值（亿元）
MAX_PE = 15           # PE上限
MIN_PE = 0            # PE下限

_DEFAULT_TIERS = [
    {'name': '金龟', 'pe_max': 8, 'pb_max': 0.8, 'dv_min': 7.0},
    {'name': '银龟', 'pe_max': 10, 'pb_max': 1.0, 'dv_min': 5.0},
    {'name': '铜龟', 'pe_max': 12, 'pb_max': 1.2, 'dv_min': 4.0},
]

_DEFAULT_SCORING_WEIGHTS = {'pe': 0.3, 'pb': 0.3, 'dv': 0.4}
_DEFAULT_SCORING_RANGES = {
    'pe_full': 6, 'pe_zero': 15,
    'pb_full': 0.5, 'pb_zero': 1.5,
    'dv_zero': 2, 'dv_full': 8,
}
_DEFAULT_TIER_LABEL = '不达标'


def _resolve_config(config: Optional["StrategyConfig"] = None):
    """从 config 提取筛选参数，或使用默认值"""
    if config is not None:
        sc = config.get_screening_config()
        tiers = config.get_tiers()
        weights = config.get_scoring_weights()
        ranges = config.get_scoring_ranges()
        default_label = config.get_default_tier_label()
        min_cap = sc.get('min_market_cap', MIN_MARKET_CAP)
        max_pe = sc.get('max_pe', MAX_PE)
        min_pe = sc.get('min_pe', MIN_PE)
    else:
        tiers = _DEFAULT_TIERS
        weights = _DEFAULT_SCORING_WEIGHTS
        ranges = _DEFAULT_SCORING_RANGES
        default_label = _DEFAULT_TIER_LABEL
        min_cap = MIN_MARKET_CAP
        max_pe = MAX_PE
        min_pe = MIN_PE

    return tiers, weights, ranges, default_label, min_cap, max_pe, min_pe


@dataclass
class ScreenResult:
    """筛选结果"""
    cutoff_date: str
    total_stocks: int = 0
    after_basic_filter: int = 0
    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def summary(self) -> str:
        turtle_counts = {}
        if not self.candidates.empty and 'turtle_rating' in self.candidates.columns:
            turtle_counts = self.candidates['turtle_rating'].value_counts().to_dict()
        parts = [
            f"截面: {self.cutoff_date}",
            f"全市场: {self.total_stocks}",
            f"基础过滤后: {self.after_basic_filter}",
            f"候选: {len(self.candidates)}",
        ]
        for name, count in turtle_counts.items():
            parts.append(f"{name}:{count}")
        return " | ".join(parts)


def screen_at_date(
    cutoff_date: str,
    top_n: int = 50,
    min_market_cap: float = None,
    max_pe: float = None,
    config: Optional["StrategyConfig"] = None,
) -> ScreenResult:
    """
    在指定截面日期进行全量筛选

    Args:
        cutoff_date: 截面日期 YYYY-MM-DD
        top_n: 返回前N名候选
        min_market_cap: 最低市值（亿元），None 时使用 config 或默认值
        max_pe: PE上限，None 时使用 config 或默认值
        config: 策略配置（可选）
    """
    tiers, weights, ranges, default_label, cfg_min_cap, cfg_max_pe, cfg_min_pe = _resolve_config(config)

    # 参数优先级：显式参数 > config > 默认值
    if min_market_cap is None:
        min_market_cap = cfg_min_cap
    if max_pe is None:
        max_pe = cfg_max_pe

    result = ScreenResult(cutoff_date=cutoff_date)

    # 1. 获取截面日的全市场日线指标
    start = pd.to_datetime(cutoff_date) - pd.Timedelta(days=10)
    start_str = start.strftime('%Y-%m-%d')

    di = api.get_daily_indicator(start_str, cutoff_date)
    if di.empty:
        print(f"  警告: {cutoff_date} 无日线指标数据")
        return result

    latest_date = di['trade_date'].max()
    df = di[di['trade_date'] == latest_date].copy()
    result.total_stocks = len(df)
    print(f"  截面交易日: {latest_date}, 全市场 {len(df)} 只股票")

    # 2. 排除ST和退市
    stock_list = api.get_stock_list(only_active=True)
    if not stock_list.empty:
        st_mask = stock_list['name'].str.contains('ST|退', na=False)
        valid_codes = set(stock_list[~st_mask]['ts_code'].tolist())
        df = df[df['ts_code'].isin(valid_codes)]

    # 3. 基础过滤
    df = df[df['pe_ttm'].notna() & (df['pe_ttm'] > cfg_min_pe)]
    df = df[df['pe_ttm'] <= max_pe]
    df = df[df['pb'].notna() & (df['pb'] > 0)]
    df = df[df['total_mv'].notna() & (df['total_mv'] >= min_market_cap * 10000)]
    df['dv'] = df['dv_ttm'].fillna(df['dv_ratio']).fillna(0)
    df = df[df['dv'] > 0]

    result.after_basic_filter = len(df)
    print(f"  基础过滤后: {len(df)} 只（排除ST/亏损/高PE/低市值/无股息）")

    if df.empty:
        return result

    # 4. 评分和评级
    df = df.copy()
    df['turtle_score'] = df.apply(lambda row: _score_turtle(row, weights, ranges), axis=1)
    df['turtle_rating'] = df.apply(lambda row: _rate_turtle(row, tiers, default_label), axis=1)

    # 5. 排序
    df = df.sort_values(
        ['turtle_score', 'dv', 'pb'],
        ascending=[False, False, True],
    )

    # 6. 取top_n
    candidates = df.head(top_n).copy()

    # 7. 补充股票名称
    if not stock_list.empty:
        name_map = stock_list.set_index('ts_code')['name'].to_dict()
        candidates['stock_name'] = candidates['ts_code'].map(name_map)
    else:
        candidates['stock_name'] = ''

    output_cols = [
        'ts_code', 'stock_name', 'trade_date',
        'pe_ttm', 'pb', 'dv', 'total_mv',
        'turtle_score', 'turtle_rating',
    ]
    existing = [c for c in output_cols if c in candidates.columns]
    candidates = candidates[existing].reset_index(drop=True)

    if 'total_mv' in candidates.columns:
        candidates['total_mv_yi'] = (candidates['total_mv'] / 10000).round(2)

    result.candidates = candidates
    print(f"  候选: {len(candidates)} 只")

    return result


def _score_turtle(row, weights=None, ranges=None) -> float:
    """评分（0-100）"""
    if weights is None:
        weights = _DEFAULT_SCORING_WEIGHTS
    if ranges is None:
        ranges = _DEFAULT_SCORING_RANGES

    pe = row.get('pe_ttm', 99)
    pb = row.get('pb', 99)
    dv = row.get('dv', 0)

    pe_full = ranges.get('pe_full', 6)
    pe_zero = ranges.get('pe_zero', 15)
    pb_full = ranges.get('pb_full', 0.5)
    pb_zero = ranges.get('pb_zero', 1.5)
    dv_zero = ranges.get('dv_zero', 2)
    dv_full = ranges.get('dv_full', 8)

    pe_score = max(0, min(100, (pe_zero - pe) / (pe_zero - pe_full) * 100))
    pb_score = max(0, min(100, (pb_zero - pb) / (pb_zero - pb_full) * 100))
    dv_score = max(0, min(100, (dv - dv_zero) / (dv_full - dv_zero) * 100))

    return round(
        pe_score * weights.get('pe', 0.3) +
        pb_score * weights.get('pb', 0.3) +
        dv_score * weights.get('dv', 0.4),
        1
    )


def _rate_turtle(row, tiers=None, default_label=None) -> str:
    """根据阈值判定评级"""
    if tiers is None:
        tiers = _DEFAULT_TIERS
    if default_label is None:
        default_label = _DEFAULT_TIER_LABEL

    pe = row.get('pe_ttm', 99)
    pb = row.get('pb', 99)
    dv = row.get('dv', 0)

    for tier in tiers:
        if pe <= tier['pe_max'] and pb <= tier['pb_max'] and dv >= tier['dv_min']:
            return tier['name']
    return default_label


def format_screen_result(result: ScreenResult) -> str:
    """格式化筛选结果为Markdown"""
    lines = [
        f"# 量化筛选结果: {result.cutoff_date}",
        "",
        f"- 全市场股票数: {result.total_stocks}",
        f"- 基础过滤后: {result.after_basic_filter}",
        f"- 候选数: {len(result.candidates)}",
        "",
    ]

    if result.candidates.empty:
        lines.append("（无候选）")
        return '\n'.join(lines)

    turtle_counts = result.candidates['turtle_rating'].value_counts()
    lines.append("## 评级分布")
    for rating in turtle_counts.index:
        count = turtle_counts.get(rating, 0)
        if count > 0:
            lines.append(f"- {rating}: {count} 只")
    lines.append("")

    lines.append("## 候选列表")
    lines.append("| 排名 | 代码 | 名称 | PE(TTM) | PB | 股息率% | 市值(亿) | 评分 | 评级 |")
    lines.append("|------|------|------|---------|-----|---------|----------|------|------|")

    for i, (_, row) in enumerate(result.candidates.iterrows(), 1):
        lines.append(
            f"| {i} "
            f"| {row.get('ts_code', '')} "
            f"| {row.get('stock_name', '')} "
            f"| {row.get('pe_ttm', 0):.1f} "
            f"| {row.get('pb', 0):.2f} "
            f"| {row.get('dv', 0):.2f} "
            f"| {row.get('total_mv_yi', 0):.0f} "
            f"| {row.get('turtle_score', 0):.1f} "
            f"| {row.get('turtle_rating', '')} |"
        )

    return '\n'.join(lines)


# ==================== CLI ====================

def main():
    import sys
    args = sys.argv[1:]
    if not args:
        print("用法: python -m src.screener.quick_filter <cutoff_date> [--top N] [--strategy <yaml>]")
        print("示例: python -m src.screener.quick_filter 2024-06-30")
        print("      python -m src.screener.quick_filter 2024-06-30 --top 30")
        sys.exit(1)

    cutoff_date = args[0]
    top_n = 50
    config = None

    if '--top' in args:
        idx = args.index('--top')
        if idx + 1 < len(args):
            top_n = int(args[idx + 1])

    if '--strategy' in args:
        idx = args.index('--strategy')
        if idx + 1 < len(args):
            from src.engine.config import StrategyConfig
            config = StrategyConfig.from_yaml(args[idx + 1])
            print(f"使用策略: {config.name}")

    print(f"量化筛选: {cutoff_date} (top {top_n})")
    result = screen_at_date(cutoff_date, top_n=top_n, config=config)
    print()
    print(format_screen_result(result))


if __name__ == '__main__':
    main()
