"""
因子预计算存储

将 FactorRegistry 中注册的所有因子预先计算并存储到当前 provider 的 SQLite。
筛选时直接读取预计算结果，无需在线计算。

两类因子存储:
    截面因子: provider market.db / daily/factors / YYYY-MM 逻辑分区
        列: ts_code, trade_date, dv, ep, market_cap_yi, ...
        每日一行每股票

    时序因子: provider market.db / daily/ts_factors / latest 逻辑分区
        列: ts_code, profit_growth_5y, revenue_growth_5y, ...
        每股票一行 (静态属性)

CLI:
    python -m src.engine.launcher data update-factors [start] [end]  # 增量更新截面因子
    python -m src.engine.launcher data recalc-factors                # 全量重算截面因子
    python -m src.engine.launcher data update-ts-factors [codes...]  # 增量更新时序因子
    python -m src.engine.launcher data recalc-ts-factors             # 全量重算时序因子

Python:
    from src.data.factor_store import compute_and_store_factors
    compute_and_store_factors('2024-01-01', '2024-06-30')

    from src.data.factor_store import compute_and_store_ts_factors
    compute_and_store_ts_factors()  # 全量增量

    from src.data.factor_store import get_factor_data, get_ts_factor_data
    df = get_factor_data('2024-01-01', '2024-06-30')     # 读取截面因子
    df = get_ts_factor_data()                              # 读取时序因子
"""
import logging
from datetime import timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import storage

logger = logging.getLogger(__name__)


def compute_and_store_factors(
    start_date: str = None,
    end_date: str = None,
    strategy_dir: Path = None,
) -> bool:
    """计算所有因子并按月存储

    Args:
        start_date: 起始日期, None 则从因子数据最新日期+1天开始
        end_date: 截止日期, None 则到指标数据最新日期
        strategy_dir: 策略目录 (加载策略私有因子), None 仅计算全局因子
    """
    from src.engine.factors import FactorRegistry

    # 确定日期范围
    if end_date is None:
        end_date = storage.get_latest_date('daily', 'indicator')
        if not end_date:
            print("  无指标数据，跳过因子计算")
            return False

    if start_date is None:
        # 自动检测: 向前回填 + 向后增量
        indicator_parts = storage.list_partitions('daily', 'indicator')
        factor_parts = storage.list_partitions('daily', 'factors')

        if not indicator_parts:
            print("  无指标数据，跳过因子计算")
            return False

        indicator_earliest = indicator_parts[0] + '-01'

        if not factor_parts:
            # 无因子数据：从指标最早到最新
            start_date = indicator_earliest
        else:
            # 有因子数据：计算需要补的范围
            factor_earliest = factor_parts[0] + '-01'
            latest_factor = storage.get_latest_date('daily', 'factors')

            segments = []
            # 向前：指标有但因子没有的早期月份
            if indicator_earliest < factor_earliest:
                backfill_end = (pd.to_datetime(factor_earliest) - timedelta(days=1)).strftime('%Y-%m-%d')
                segments.append((indicator_earliest, backfill_end))
            # 向后：因子最新日期之后
            if latest_factor and latest_factor < end_date:
                forward_start = (pd.to_datetime(latest_factor) + timedelta(days=1)).strftime('%Y-%m-%d')
                segments.append((forward_start, end_date))

            if not segments:
                print(f"因子数据已是最新 ({end_date})")
                return True

            # 有多段需要计算，逐段递归
            registry = FactorRegistry(strategy_dir=strategy_dir)
            for seg_start, seg_end in segments:
                _compute_factors_range(registry, seg_start, seg_end)
            return True

    if start_date > end_date:
        print(f"因子数据已是最新 ({end_date})")
        return True

    # 加载因子注册表
    registry = FactorRegistry(strategy_dir=strategy_dir)
    _compute_factors_range(registry, start_date, end_date)
    return True


def _compute_factors_range(registry, start_date: str, end_date: str):
    """计算指定日期范围内的截面因子 (内部函数)"""
    cs_factors = registry.list_cross_section()
    if not cs_factors:
        print("  无截面因子，跳过")
        return

    factor_ids = [factor.id for factor in cs_factors]
    row_factor_ids = [
        factor.id
        for factor in cs_factors
        if getattr(factor, "execution_mode", "row") == "row"
    ]
    point_in_time_ids = [
        factor.id
        for factor in cs_factors
        if getattr(factor, "execution_mode", "row") == "point_in_time"
    ]
    print(f"日频预计算因子: {', '.join(row_factor_ids)}")
    print(f"  日期范围: {start_date} ~ {end_date}")
    if point_in_time_ids:
        print(
            "  财报时点因子由因子库物化任务续接: "
            + ", ".join(point_in_time_ids)
        )

    months = storage.get_months_between(start_date, end_date)
    merge_on = ['ts_code', 'trade_date']
    materialized = set()
    native_columns = set()

    for month in months:
        indicator_df = storage.load_one('daily', 'indicator', month)
        if indicator_df.empty:
            continue

        month_start = max(start_date, month + '-01')
        month_end_dt = pd.to_datetime(month + '-01') + pd.offsets.MonthEnd(1)
        month_end = min(end_date, month_end_dt.strftime('%Y-%m-%d'))
        indicator_df = indicator_df[
            (indicator_df['trade_date'] >= month_start) &
            (indicator_df['trade_date'] <= month_end)
        ]

        if indicator_df.empty:
            continue

        computed = registry.compute_all(indicator_df)

        existing_cols = set(indicator_df.columns)
        native_columns.update(existing_cols.intersection(factor_ids))
        new_factor_cols = [
            column
            for column in computed.columns
            if column not in existing_cols and computed[column].notna().any()
        ]
        if not new_factor_cols:
            continue
        materialized.update(new_factor_cols)

        factor_df = computed[['ts_code', 'trade_date'] + new_factor_cols].copy()

        storage.save(factor_df, 'daily', 'factors', month, mode='merge', merge_on=merge_on)
        n_dates = factor_df['trade_date'].nunique()
        print(f"  {month}: {n_dates} 日, {len(factor_df)} 行, {len(new_factor_cols)} 因子")

    unavailable = set(row_factor_ids) - materialized - native_columns
    if materialized:
        print(f"  已物化因子: {', '.join(sorted(materialized))}")
    if native_columns:
        print(f"  数据源原生字段: {', '.join(sorted(native_columns))}")
    if unavailable:
        print(f"  日频因子未产生有效结果，已跳过: {', '.join(sorted(unavailable))}")
    print("日频因子预计算完成")


def materialize_factor_definitions(
    factor_ids: List[str],
    provider: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    progress: Optional[Callable[[Dict[str, object]], None]] = None,
) -> bool:
    """Recompute selected DSL factors over the provider's complete indicator history.

    Unlike the date-based incremental updater, this path is definition-aware: it
    rewrites only the selected factor columns and records the definition hash that
    produced them. It is therefore safe for both newly created and edited factors.
    """
    from src.data.config import get_active_provider_name
    from src.data.factor_materialization import set_factor_materialization
    from src.engine.factor_catalog import FactorCatalog
    from src.engine.factor_temporal import (
        align_event_matrix_to_daily,
        build_point_in_time_events,
        build_temporal_input_cache,
        combine_event_streams,
        is_point_in_time_definition,
    )
    from src.engine.factors import FACTOR_CROSS_SECTION, FactorRegistry

    selected_provider = (provider or get_active_provider_name()).lower()
    requested = list(dict.fromkeys(str(factor_id) for factor_id in factor_ids if factor_id))
    if not requested:
        raise ValueError("至少需要一个待物化因子")

    catalog = FactorCatalog(provider=selected_provider)
    assets = {asset["id"]: asset for asset in catalog.list_assets()}
    registry = FactorRegistry()
    definitions = {}
    for factor_id in requested:
        asset = assets.get(factor_id)
        factor = registry.get(factor_id)
        definition = catalog.get_definition(factor_id)
        if asset is None or factor is None or definition is None:
            raise ValueError(f"因子不存在: {factor_id}")
        if factor.engine != "polars" or factor.factor_type != FACTOR_CROSS_SECTION:
            raise ValueError(f"只支持物化截面 Polars DSL 因子: {factor_id}")
        if not definition.enabled:
            raise ValueError(f"因子已停用: {factor_id}")
        if asset["provider"]["compatibility"] != "exact":
            raise ValueError(f"{selected_provider} 缺少 {factor_id} 的精确输入字段")
        definitions[factor_id] = definition

    point_in_time_definitions = {
        factor_id: definition
        for factor_id, definition in definitions.items()
        if is_point_in_time_definition(definition)
    }
    row_factor_ids = [
        factor_id for factor_id in requested if factor_id not in point_in_time_definitions
    ]

    partitions = storage.list_partitions(
        "daily", "indicator", provider=selected_provider
    )
    if not partitions:
        raise ValueError(f"{selected_provider} 尚无每日指标数据，无法计算因子")
    effective_start = start_date or f"{partitions[0]}-01"
    effective_end = end_date or storage.get_latest_date(
        "daily", "indicator", provider=selected_provider
    )
    if not effective_end or effective_start > effective_end:
        raise ValueError("因子物化日期范围无效")

    months = [
        month
        for month in storage.get_months_between(effective_start, effective_end)
        if month in set(partitions)
    ]
    non_null_rows = {factor_id: 0 for factor_id in requested}
    previous_materializations = {
        factor_id: assets[factor_id].get("materialization", {}) for factor_id in requested
    }
    for factor_id, definition in definitions.items():
        previous = previous_materializations[factor_id]
        set_factor_materialization(
            selected_provider,
            factor_id,
            definition.definition_hash,
            "computing",
            start_date=previous.get("start_date") or effective_start,
            end_date=max(
                value
                for value in (previous.get("latest_date"), effective_end)
                if value
            ),
            row_count=int(previous.get("row_count", 0)),
        )

    try:
        temporal_input_cache = (
            build_temporal_input_cache(
                point_in_time_definitions.values(),
                selected_provider,
                fields=getattr(catalog, "fields", None),
            )
            if point_in_time_definitions
            else {}
        )
        temporal_events = {
            factor_id: build_point_in_time_events(
                definition,
                selected_provider,
                fields=getattr(catalog, "fields", None),
                input_cache=temporal_input_cache,
            )
            for factor_id, definition in point_in_time_definitions.items()
        }
        temporal_event_matrix = combine_event_streams(temporal_events)
        for index, month in enumerate(months, start=1):
            indicator = storage.load_one(
                "daily", "indicator", month, provider=selected_provider
            )
            if indicator.empty:
                continue
            indicator = indicator[
                (indicator["trade_date"] >= effective_start)
                & (indicator["trade_date"] <= effective_end)
            ]
            if indicator.empty:
                continue

            computed = registry.compute_selected(indicator, row_factor_ids)
            factor_frame = indicator[["ts_code", "trade_date"]].copy()
            output_columns = []
            for factor_id in row_factor_ids:
                if factor_id in computed.columns:
                    factor_frame[factor_id] = computed[factor_id]
                    output_columns.append(factor_id)
            if temporal_events:
                aligned_temporal = align_event_matrix_to_daily(
                    indicator,
                    temporal_event_matrix,
                    list(temporal_events),
                )
                for factor_id in temporal_events:
                    factor_frame[factor_id] = aligned_temporal[factor_id]
                    output_columns.append(factor_id)
            if output_columns:
                saved = storage.save(
                    factor_frame[["ts_code", "trade_date", *output_columns]],
                    "daily",
                    "factors",
                    month,
                    mode="merge",
                    merge_on=["ts_code", "trade_date"],
                    provider=selected_provider,
                )
                if not saved:
                    raise RuntimeError(f"写入 {month} 因子分区失败")
                for factor_id in output_columns:
                    non_null_rows[factor_id] += int(factor_frame[factor_id].notna().sum())

            if progress:
                progress(
                    {
                        "stage": "factors",
                        "message": f"正在计算 {month} 因子",
                        "current": index,
                        "total": len(months),
                        "percent": round(index / max(len(months), 1) * 100, 1),
                    }
                )

        failures = []
        for factor_id, definition in definitions.items():
            row_count = non_null_rows[factor_id]
            previous = previous_materializations[factor_id]
            previous_start = previous.get("start_date")
            previous_end = previous.get("latest_date")
            coverage_start = min(
                value for value in (previous_start, effective_start) if value
            )
            coverage_end = max(
                value for value in (previous_end, effective_end) if value
            )
            total_row_count = (
                int(previous.get("row_count", 0)) + row_count
                if previous_end and effective_start > previous_end
                else max(int(previous.get("row_count", 0)), row_count)
            )
            status = "ready" if row_count else "failed"
            error = None if row_count else "完整指标区间未产生任何非空结果"
            set_factor_materialization(
                selected_provider,
                factor_id,
                definition.definition_hash,
                status,
                start_date=coverage_start,
                end_date=coverage_end,
                row_count=total_row_count,
                error=error,
            )
            if not row_count:
                failures.append(factor_id)
        if failures:
            raise RuntimeError(f"因子未产生有效结果: {', '.join(failures)}")
        return True
    except Exception as exc:
        for factor_id, definition in definitions.items():
            previous = previous_materializations[factor_id]
            set_factor_materialization(
                selected_provider,
                factor_id,
                definition.definition_hash,
                "failed",
                start_date=previous.get("start_date") or effective_start,
                end_date=previous.get("latest_date") or effective_end,
                row_count=int(previous.get("row_count", 0)),
                error=str(exc)[:1000],
            )
        raise


def get_factor_data(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """读取预计算的因子数据

    Args:
        start_date: 起始日期
        end_date: 截止日期
        ts_code: 股票代码, None 返回全市场
        columns: 指定列, None 返回所有因子
    """
    months = storage.get_months_between(start_date, end_date)
    filters = [
        ('trade_date', '>=', start_date),
        ('trade_date', '<=', end_date),
    ]
    if ts_code is not None and not isinstance(ts_code, (list, tuple)):
        filters.append(('ts_code', '==', ts_code))
    elif isinstance(ts_code, (list, tuple)):
        filters.append(('ts_code', 'in', ts_code))
    df = storage.load('daily', 'factors', months, columns, filters=filters)
    if df.empty:
        return df

    df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
    if ts_code is not None:
        if isinstance(ts_code, (list, tuple)):
            df = df[df['ts_code'].isin(ts_code)]
        else:
            df = df[df['ts_code'] == ts_code]

    return df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


def get_indicator_with_factors(
    start_date: str,
    end_date: str,
    ts_code: Optional[str] = None,
) -> pd.DataFrame:
    """获取指标数据 + 预计算因子 (合并后返回)

    这是 quick_filter 的主要数据源，替代原来的在线计算。
    """
    from . import api

    # 加载指标
    indicator = api.get_daily_indicator(start_date, end_date, ts_code)
    if indicator.empty:
        return indicator

    # 加载因子
    factors = get_factor_data(start_date, end_date, ts_code)
    if factors.empty:
        return indicator

    # 合并 (因子列追加到指标，不覆盖已有列)
    factor_cols = [c for c in factors.columns if c not in ('ts_code', 'trade_date')]
    new_cols = [c for c in factor_cols if c not in indicator.columns]
    if not new_cols:
        return indicator

    merged = indicator.merge(
        factors[['ts_code', 'trade_date'] + new_cols],
        on=['ts_code', 'trade_date'],
        how='left',
    )

    return merged


def recalc_all_factors(strategy_dir: Path = None) -> bool:
    """全量重算所有截面因子 (清除旧数据后重算)"""
    # 找到指标数据的完整范围
    partitions = storage.list_partitions('daily', 'indicator')
    if not partitions:
        print("无指标数据")
        return False

    # 清除旧因子数据
    factor_partitions = storage.list_partitions('daily', 'factors')
    for p in factor_partitions:
        storage.delete('daily', 'factors', p)
    print(f"已清除 {len(factor_partitions)} 个旧截面因子分区")

    start_date = partitions[0] + '-01'
    end_date_dt = pd.to_datetime(partitions[-1] + '-01') + pd.offsets.MonthEnd(1)
    end_date = end_date_dt.strftime('%Y-%m-%d')

    return compute_and_store_factors(start_date, end_date, strategy_dir)


# ==================== 时序因子 ====================

_TS_FACTOR_PARTITION = 'latest'


class _CachedApi:
    """预加载全部财报数据到内存, 按 ts_code 查询时无需重复 I/O

    模拟 src.data.api 模块的接口, 但数据从内存字典中读取。
    """

    def __init__(self, data_needed: set):
        """根据因子声明的 data_needed 预加载对应的财报数据"""
        self._cache = {}  # {data_type: {ts_code: DataFrame}}
        _type_map = {
            'income': 'income',
            'balancesheet': 'balancesheet',
            'cashflow': 'cashflow',
            'fina_indicator': 'fina_indicator',
            'dividend': 'dividend',
            'top10_holders': 'top10_holders',
        }
        for need in data_needed:
            sub = _type_map.get(need)
            if sub is None:
                continue
            print(f"  预加载 {sub} ...")
            full_df = storage.load_financial(sub)
            if full_df.empty:
                self._cache[need] = {}
                continue
            grouped = {code: group for code, group in full_df.groupby('ts_code')}
            self._cache[need] = grouped
            print(f"    {sub}: {len(grouped)} 只股票, {len(full_df)} 行")

    def _get(self, data_type: str, ts_code: str) -> pd.DataFrame:
        group = self._cache.get(data_type, {})
        df = group.get(ts_code)
        if df is None:
            return pd.DataFrame()
        return df.sort_values('end_date').reset_index(drop=True)

    def get_income(self, ts_code: str, end_date=None) -> pd.DataFrame:
        df = self._get('income', ts_code)
        if end_date and not df.empty and 'end_date' in df.columns:
            df = df[df['end_date'] <= end_date]
        return df

    def get_balancesheet(self, ts_code: str, end_date=None) -> pd.DataFrame:
        df = self._get('balancesheet', ts_code)
        if end_date and not df.empty and 'end_date' in df.columns:
            df = df[df['end_date'] <= end_date]
        return df

    def get_cashflow(self, ts_code: str, end_date=None) -> pd.DataFrame:
        df = self._get('cashflow', ts_code)
        if end_date and not df.empty and 'end_date' in df.columns:
            df = df[df['end_date'] <= end_date]
        return df

    def get_financial_indicator(self, ts_code: str, end_date=None) -> pd.DataFrame:
        df = self._get('fina_indicator', ts_code)
        if end_date and not df.empty and 'end_date' in df.columns:
            df = df[df['end_date'] <= end_date]
        return df

    def get_dividend(self, ts_code: str) -> pd.DataFrame:
        return self._get('dividend', ts_code)

    def get_top10_holders(self, ts_code: str, end_date=None) -> pd.DataFrame:
        df = self._get('top10_holders', ts_code)
        if end_date and not df.empty and 'end_date' in df.columns:
            df = df[df['end_date'] <= end_date]
        return df


def compute_and_store_ts_factors(
    ts_codes: List[str] = None,
    strategy_dir: Path = None,
    incremental: bool = True,
) -> bool:
    """计算时序因子并存储

    Args:
        ts_codes: 股票代码列表, None 则全部活跃股票
        strategy_dir: 策略目录
        incremental: True 增量 (只算缺失的股票), False 全量
    """
    from src.engine.factors import FactorRegistry
    from src.data import api

    registry = FactorRegistry(strategy_dir=strategy_dir)
    ts_factors = registry.list_timeseries()
    if not ts_factors:
        print("  无时序因子，跳过")
        return True

    factor_ids = [f.id for f in ts_factors]
    print(f"时序因子: {', '.join(factor_ids)}")

    # 确定要计算的股票列表
    if ts_codes is None:
        ts_codes = api.get_stock_codes(only_active=True)
    if not ts_codes:
        print("  无股票数据")
        return False

    # 增量: 加载已有结果，跳过已计算的股票
    existing_df = get_ts_factor_data()
    computed_codes = set()
    if incremental and not existing_df.empty:
        # 只跳过所有因子列都有值的股票
        has_all = existing_df[factor_ids].notna().all(axis=1)
        computed_codes = set(existing_df.loc[has_all, 'ts_code'].tolist())

    todo_codes = [c for c in ts_codes if c not in computed_codes]
    if not todo_codes:
        print(f"时序因子已是最新 ({len(ts_codes)} 只股票)")
        return True

    print(f"  待计算: {len(todo_codes)} 只 (已有: {len(computed_codes)})")

    # 收集所有因子需要的数据类型，一次性预加载
    all_data_needed = set()
    for f in ts_factors:
        all_data_needed.update(f.data_needed)
    print(f"  预加载财报数据: {', '.join(sorted(all_data_needed))}")
    cached_api = _CachedApi(all_data_needed)

    # 逐股票计算 (数据已在内存, 无 I/O)
    results = []
    total = len(todo_codes)
    for i, ts_code in enumerate(todo_codes, 1):
        if i % 500 == 0 or i == total:
            print(f"  [{i}/{total}] {ts_code}")

        row = {'ts_code': ts_code}
        for factor in ts_factors:
            try:
                row[factor.id] = factor.compute_fn(ts_code, cached_api)
            except Exception as e:
                logger.debug(f"时序因子 {factor.id} ({ts_code}) 计算失败: {e}")
                row[factor.id] = None
        results.append(row)

    new_df = pd.DataFrame(results)

    # 合并旧数据
    if not existing_df.empty:
        # 删除待更新的股票旧数据
        existing_df = existing_df[~existing_df['ts_code'].isin(set(todo_codes))]
        new_df = pd.concat([existing_df, new_df], ignore_index=True)

    new_df = new_df.sort_values('ts_code').reset_index(drop=True)

    # 存储
    storage.save(new_df, 'daily', 'ts_factors', _TS_FACTOR_PARTITION)
    n_valid = new_df[factor_ids].notna().any(axis=1).sum()
    print(f"时序因子完成: {len(new_df)} 只股票, {n_valid} 只有有效值")
    return True


def get_ts_factor_data(
    ts_code: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """读取时序因子数据

    Returns:
        DataFrame: ts_code, factor1, factor2, ... (每股票一行)
    """
    df = storage.load_one('daily', 'ts_factors', _TS_FACTOR_PARTITION, columns)
    if df.empty:
        return df
    if ts_code is not None:
        if isinstance(ts_code, (list, tuple)):
            df = df[df['ts_code'].isin(ts_code)]
        else:
            df = df[df['ts_code'] == ts_code]
    return df.reset_index(drop=True)


def recalc_all_ts_factors(strategy_dir: Path = None) -> bool:
    """全量重算所有时序因子"""
    # 清除旧数据
    if storage.delete('daily', 'ts_factors', _TS_FACTOR_PARTITION):
        print("已清除旧时序因子数据")
    return compute_and_store_ts_factors(strategy_dir=strategy_dir, incremental=False)
