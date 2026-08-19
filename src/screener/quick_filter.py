"""
声明式量化筛选引擎

从 StrategyConfig 读取声明式过滤条件和评分因子，
对全A股进行筛选、评分、分级。不硬编码任何字段名。

支持的过滤操作: min, max, fallback
支持的评分方向: lower_better, higher_better
支持的分级条件: min, max (per field, AND 逻辑)

用法:
    python -m src.engine.launcher workspace/strategies/v6_value/strategy.yaml screen 2024-06-30
"""
import logging
from dataclasses import dataclass, field
from typing import List

import pandas as pd

from src.data import api
from src.engine.config import StrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class ScreenResult:
    """筛选结果"""
    cutoff_date: str
    effective_date: str = ""
    total_stocks: int = 0
    after_basic_filter: int = 0
    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def summary(self) -> str:
        tier_counts = {}
        if not self.candidates.empty and 'tier_rating' in self.candidates.columns:
            tier_counts = self.candidates['tier_rating'].value_counts().to_dict()
        parts = [
            f"截面: {self.cutoff_date}",
            f"全市场: {self.total_stocks}",
            f"基础过滤后: {self.after_basic_filter}",
            f"候选: {len(self.candidates)}",
        ]
        for name, count in tier_counts.items():
            parts.append(f"{name}:{count}")
        return " | ".join(parts)


# ==================== 声明式引擎核心 ====================

def _resolve_field(df: pd.DataFrame, filter_def: dict) -> pd.Series:
    """
    解析字段值，支持 fallback 链。
    filter_def 示例: {field: "dv", fallback: "dv_ttm,dv_ratio"}
    """
    field_name = filter_def['field']

    if field_name in df.columns:
        series = df[field_name].copy()
    else:
        series = pd.Series(pd.NA, index=df.index)

    # fallback: 主字段为空时，依次尝试备选字段
    fallback = filter_def.get('fallback', '')
    if fallback:
        for fb_field in fallback.split(','):
            fb_field = fb_field.strip()
            if fb_field in df.columns:
                series = series.fillna(df[fb_field])

    return series


def _apply_excludes(df: pd.DataFrame, stock_list: pd.DataFrame, exclude_rules: List[dict]) -> pd.DataFrame:
    """应用排除规则"""
    if stock_list.empty:
        return df

    for rule in exclude_rules:
        field_name = rule.get('field', '')
        contains = rule.get('contains', [])

        if field_name in stock_list.columns and contains:
            pattern = '|'.join(contains)
            bad_mask = stock_list[field_name].str.contains(pattern, na=False)
            valid_codes = set(stock_list[~bad_mask]['ts_code'].tolist())
            df = df[df['ts_code'].isin(valid_codes)]

    return df


def _apply_filters(df: pd.DataFrame, filters: List[dict]) -> pd.DataFrame:
    """应用声明式过滤条件"""
    for f in filters:
        if not f.get('enabled', True):
            continue
        field_name = f['field']

        # 先解析字段（含 fallback），写回 df 以便后续评分使用
        series = _resolve_field(df, f)
        if field_name not in df.columns:
            df[field_name] = series
        else:
            df[field_name] = series

        # 过滤非空
        df = df[df[field_name].notna()]

        if 'percentile_min' in f or 'percentile_max' in f:
            values = df[field_name].dropna()
            if values.empty:
                return df.iloc[0:0]
            lower = float(f.get('percentile_min', 0)) / 100
            upper = float(f.get('percentile_max', 100)) / 100
            lower_value = values.quantile(lower)
            upper_value = values.quantile(upper)
            df = df[(df[field_name] >= lower_value) & (df[field_name] <= upper_value)]
        else:
            if 'min' in f:
                df = df[df[field_name] >= f['min']]
            if 'max' in f:
                df = df[df[field_name] <= f['max']]

    return df


def _compute_scores(df: pd.DataFrame, factors: List[dict]) -> pd.Series:
    """根据评分因子计算综合得分（0-100）"""
    if not factors:
        return pd.Series(0.0, index=df.index)

    # 归一化权重
    total_weight = sum(f.get('weight', 1.0) for f in factors)
    if total_weight == 0:
        total_weight = 1.0

    score = pd.Series(0.0, index=df.index)

    for f in factors:
        field_name = f['field']
        weight = f.get('weight', 1.0) / total_weight

        if f.get('method') == 'percentile' or 'direction' in f:
            if field_name not in df.columns:
                continue
            direction = f.get('direction', 'desc')
            ranked = df[field_name].rank(
                pct=True,
                ascending=(direction == 'desc'),
            ) * 100
            fill_value = 0.0 if f.get('na_handling') == 'worst' else 50.0
            score += ranked.fillna(fill_value) * weight
            continue

        full_val = f.get('full', 0)
        zero_val = f.get('zero', 0)
        lower_better = f.get('lower_better', False)

        if field_name not in df.columns:
            continue

        vals = df[field_name].fillna(zero_val)

        if lower_better:
            # PE 类: 值越小越好, full=6(满分), zero=15(零分)
            raw = (zero_val - vals) / (zero_val - full_val) * 100
        else:
            # DV 类: 值越大越好, full=8(满分), zero=2(零分)
            raw = (vals - zero_val) / (full_val - zero_val) * 100

        factor_score = raw.clip(0, 100)
        score += factor_score * weight

    return score.round(1)


def _compute_tiers(df: pd.DataFrame, tiers: List[dict], default_label: str) -> pd.Series:
    """根据分级条件判定评级"""
    ratings = pd.Series(default_label, index=df.index)

    # 逆序处理：最宽松的先赋值，最严格的后赋值覆盖
    for tier in reversed(tiers):
        name = tier['name']
        conditions = tier.get('conditions', [])

        # 旧格式兼容: {name, pe_max, pb_max, dv_min} → conditions
        if not conditions and any(k.endswith('_max') or k.endswith('_min') for k in tier):
            conditions = []
            for k, v in tier.items():
                if k == 'name':
                    continue
                if k.endswith('_max'):
                    field = k[:-4]  # pe_max → pe
                    # 映射常见缩写
                    field_map = {'pe': 'pe_ttm', 'dv': 'dv'}
                    conditions.append({'field': field_map.get(field, field), 'max': v})
                elif k.endswith('_min'):
                    field = k[:-4]
                    field_map = {'pe': 'pe_ttm', 'dv': 'dv'}
                    conditions.append({'field': field_map.get(field, field), 'min': v})

        mask = pd.Series(True, index=df.index)
        for cond in conditions:
            field_name = cond['field']
            if field_name not in df.columns:
                mask = pd.Series(False, index=df.index)
                break
            if 'min' in cond:
                mask &= df[field_name] >= cond['min']
            if 'max' in cond:
                mask &= df[field_name] <= cond['max']

        ratings[mask] = name

    return ratings


# ==================== 主入口 ====================

def _apply_industry_cap(df: pd.DataFrame, industry_map: dict, cap: int) -> pd.DataFrame:
    """
    行业上限：每行业最多保留 cap 只，按 tier_score 降序取 top。
    industry_map: {ts_code: industry_name}
    """
    df = df.copy()
    df['_industry'] = df['ts_code'].map(industry_map).fillna('未知')
    # 按 tier_score 降序，每行业取 top cap
    df = df.sort_values('tier_score', ascending=False)
    df = df.groupby('_industry', sort=False).head(cap)
    # 恢复原排序
    df = df.sort_values('tier_score', ascending=False)
    df = df.drop(columns=['_industry'])
    return df


def screen_at_date(
    cutoff_date: str,
    config: StrategyConfig,
    top_n: int = 50,
) -> ScreenResult:
    """
    在指定截面日期进行全量筛选

    Args:
        cutoff_date: 截面日期 YYYY-MM-DD
        config: 策略配置
        top_n: 返回前N名候选
    """
    filters = config.get_filters()
    factors = config.get_scoring_factors()
    tiers = config.get_tiers()
    default_label = config.get_default_tier_label()
    exclude_rules = config.get_exclude_rules()
    industry_cap = config.get_industry_cap()
    required_factor_ids = list(dict.fromkeys(
        [item.get('field') for item in filters + factors if item.get('field')]
        + [
            condition.get('field')
            for tier in tiers
            for condition in tier.get('conditions', [])
            if condition.get('field')
        ]
    ))

    result = ScreenResult(cutoff_date=cutoff_date)

    # 1. 获取截面日的全市场日线指标
    start = pd.to_datetime(cutoff_date) - pd.Timedelta(days=10)
    start_str = start.strftime('%Y-%m-%d')

    di = api.get_daily_indicator(start_str, cutoff_date)
    if di.empty:
        print(f"  警告: {cutoff_date} 无日线指标数据")
        return result

    latest_date = di['trade_date'].max()
    result.effective_date = str(latest_date)
    df = di[di['trade_date'] == latest_date].copy()
    result.total_stocks = len(df)
    print(f"  截面交易日: {latest_date}, 全市场 {len(df)} 只股票")

    # 2. 排除规则
    stock_list = api.get_stock_list(only_active=False)
    if not stock_list.empty:
        if 'list_date' in stock_list.columns:
            stock_list = stock_list[
                stock_list['list_date'].fillna('9999-12-31').astype(str) <= str(latest_date)
            ]
        if 'delist_date' in stock_list.columns:
            delist_date = stock_list['delist_date'].fillna('').astype(str)
            stock_list = stock_list[(delist_date == '') | (delist_date > str(latest_date))]
    if not stock_list.empty and exclude_rules:
        df = _apply_excludes(df, stock_list, exclude_rules)

    # 2.5 加载预计算截面因子，并在线补算尚未物化的新 DSL 因子。
    factors_df = api.get_factors(latest_date, latest_date)
    if not factors_df.empty:
        factor_cols = [c for c in factors_df.columns if c not in ('ts_code', 'trade_date')]
        new_cols = [c for c in factor_cols if c not in df.columns]
        if new_cols:
            df = df.merge(
                factors_df[['ts_code'] + new_cols],
                on='ts_code', how='left',
            )
        logger.debug(f"使用预计算截面因子: {new_cols}")

    from src.engine.factors import FactorRegistry
    factor_registry = FactorRegistry(strategy_dir=config.strategy_dir)
    from src.engine.factor_catalog import FactorCatalog

    catalog_assets = FactorCatalog().list_assets()
    factor_assets = {
        asset["id"]: asset
        for asset in catalog_assets
        if asset["asset_kind"] == "derived" and asset["engine"] == "polars"
    }
    stale_columns = [
        factor_id
        for factor_id, asset in factor_assets.items()
        if not asset["materialization"].get("usable", False) and factor_id in df.columns
    ]
    if stale_columns:
        df = df.drop(columns=stale_columns)
        logger.debug("忽略定义版本过期的预计算因子: %s", stale_columns)
    columns_before_online = set(df.columns)
    df = factor_registry.compute_selected(df, required_factor_ids)
    online_columns = sorted(set(df.columns) - columns_before_online)
    if online_columns:
        logger.debug("在线补算未物化因子: %s", online_columns)

    # 2.6 加载预计算时序因子 (静态属性, 按 ts_code 合并)
    point_in_time_ids = {
        asset["id"]
        for asset in catalog_assets
        if asset.get("execution_mode") == "point_in_time"
    }
    timeseries_ids = {factor.id for factor in factor_registry.list_timeseries()}
    required_ts_ids = sorted(
        set(required_factor_ids).intersection(timeseries_ids) - point_in_time_ids
    )
    ts_factors_df = (
        api.get_ts_factors(columns=['ts_code', *required_ts_ids])
        if required_ts_ids
        else pd.DataFrame()
    )
    if not ts_factors_df.empty:
        ts_cols = [
            column
            for column in ts_factors_df.columns
            if column != "ts_code" and column not in point_in_time_ids
        ]
        new_ts_cols = [c for c in ts_cols if c not in df.columns]
        if new_ts_cols:
            df = df.merge(
                ts_factors_df[['ts_code'] + new_ts_cols],
                on='ts_code', how='left',
            )
        logger.debug(f"使用预计算时序因子: {new_ts_cols}")

    # 3. 声明式过滤
    df = _apply_filters(df.copy(), filters)

    result.after_basic_filter = len(df)
    print(f"  基础过滤后: {len(df)} 只")

    if df.empty:
        return result

    # 4. 评分
    df = df.copy()
    df['tier_score'] = _compute_scores(df, factors)

    # 5. 分级
    df['tier_rating'] = _compute_tiers(df, tiers, default_label)

    # 6. 排序 — 按综合得分降序
    sort_cols = ['tier_score']
    sort_asc = [False]
    # 如果有评分因子，用第一个 higher_better=False 的字段做次排序
    for f in factors:
        if f['field'] in df.columns:
            sort_cols.append(f['field'])
            sort_asc.append(f.get('lower_better', False))
            break

    df = df.sort_values(sort_cols, ascending=sort_asc)

    # 6.5 行业上限 — 避免单行业扎堆
    if industry_cap and industry_cap > 0 and not stock_list.empty:
        industry_map = stock_list.set_index('ts_code')['industry'].to_dict()
        before_cap = len(df)
        df = _apply_industry_cap(df, industry_map, industry_cap)
        if len(df) < before_cap:
            print(f"  行业上限({industry_cap}只/行业): {before_cap} → {len(df)}")

    # 7. 取 top_n
    candidates = df.head(top_n).copy()

    # 8. 补充股票名称和行业
    if not stock_list.empty:
        sl_index = stock_list.set_index('ts_code')
        candidates['stock_name'] = candidates['ts_code'].map(sl_index['name'].to_dict())
        candidates['industry'] = candidates['ts_code'].map(sl_index['industry'].to_dict())
    else:
        candidates['stock_name'] = ''
        candidates['industry'] = ''

    # 9. 整理输出列
    base_cols = ['ts_code', 'stock_name', 'industry', 'trade_date']
    factor_fields = [f['field'] for f in factors if f['field'] in candidates.columns]
    filter_fields = [f['field'] for f in filters if f['field'] in candidates.columns and f['field'] not in factor_fields]
    score_cols = ['tier_score', 'tier_rating']
    output_cols = base_cols + filter_fields + factor_fields + ['total_mv'] + score_cols
    # 去重保序
    seen = set()
    unique_cols = []
    for c in output_cols:
        if c not in seen and c in candidates.columns:
            seen.add(c)
            unique_cols.append(c)
    candidates = candidates[unique_cols].reset_index(drop=True)

    if 'total_mv' in candidates.columns:
        candidates['total_mv_yi'] = (candidates['total_mv'] / 10000).round(2)

    result.candidates = candidates
    print(f"  候选: {len(candidates)} 只")

    return result


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

    if 'tier_rating' in result.candidates.columns:
        tier_counts = result.candidates['tier_rating'].value_counts()
        lines.append("## 评级分布")
        for rating in tier_counts.index:
            count = tier_counts.get(rating, 0)
            if count > 0:
                lines.append(f"- {rating}: {count} 只")
        lines.append("")

    # 动态表头
    df = result.candidates
    lines.append("## 候选列表")

    display_cols = [c for c in df.columns if c not in ('trade_date', 'total_mv')]
    header = "| 排名 | " + " | ".join(display_cols) + " |"
    sep = "|------" + "|------" * len(display_cols) + "|"
    lines.append(header)
    lines.append(sep)

    for i, (_, row) in enumerate(df.iterrows(), 1):
        vals = []
        for c in display_cols:
            v = row.get(c, '')
            if isinstance(v, float):
                vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        lines.append(f"| {i} | " + " | ".join(vals) + " |")

    return '\n'.join(lines)
