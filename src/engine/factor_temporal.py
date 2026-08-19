"""Point-in-time materialization for report-backed Polars DSL factors.

The expression is evaluated on annual report rows ordered by security and
report period.  Each result becomes visible on the latest announcement date
required by its inputs, then is joined backward onto the daily trading
calendar.  A report can therefore never affect a trading date before it was
publicly available.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import pandas as pd
import polars as pl

from src.data import storage
from src.data.field_catalog import SourceField, SourceFieldCatalog
from src.engine.factor_dsl import compile_expression


KEY_COLUMNS = ["ts_code", "end_date"]


def is_point_in_time_definition(definition: object) -> bool:
    return getattr(definition, "execution_mode", "row") == "point_in_time"


def required_input_datasets(
    definition: object,
    provider: str,
    fields: SourceFieldCatalog | None = None,
) -> List[Tuple[str, str]]:
    catalog = fields or SourceFieldCatalog()
    datasets = []
    for semantic_id in getattr(definition, "inputs", {}).values():
        source = catalog.require(semantic_id)
        binding = source.binding_for(provider)
        if binding and binding.compatibility == "exact" and "/" in binding.dataset:
            datasets.append((binding.dataset, binding.field))
    return list(dict.fromkeys(datasets))


def _availability_date(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    # f_ann_date is the actual announcement date when Tushare supplies it.
    for column in ("f_ann_date", "ann_date"):
        if column in frame.columns:
            values = frame[column].astype("string")
            result = result.fillna(values)
    # A conservative filing-deadline fallback keeps providers without an
    # announcement field usable without leaking the report period itself.
    missing = result.isna()
    if missing.any():
        fallback = pd.to_datetime(frame.loc[missing, "end_date"], errors="coerce")
        result.loc[missing] = (fallback + pd.Timedelta(days=120)).dt.strftime("%Y-%m-%d")
    return result


def _prepare_source_input(
    frame: pd.DataFrame,
    source: SourceField,
    field: str,
) -> pd.DataFrame:
    frame = frame.dropna(subset=["ts_code", "end_date"]).copy()
    if source.semantic_id.startswith("financial.dividend.") and "div_proc" in frame.columns:
        implemented = frame["div_proc"].astype("string").str.contains("实施", na=False)
        frame = frame[implemented].copy()
    frame["ts_code"] = frame["ts_code"].astype(str)
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    frame = frame[frame["end_date"].str.endswith("12-31", na=False)].copy()
    frame["__available"] = _availability_date(frame)
    frame["__input"] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(subset=["end_date", "__available"])
    if source.aggregation == "sum":
        frame = frame.groupby(KEY_COLUMNS, as_index=False).agg(
            {"__input": "sum", "__available": "max"}
        )
    else:
        frame = (
            frame.sort_values([*KEY_COLUMNS, "__available"])
            .drop_duplicates(KEY_COLUMNS, keep="last")
        )
    return frame[[*KEY_COLUMNS, "__available", "__input"]].reset_index(drop=True)


def build_temporal_input_cache(
    definitions: Iterable[object],
    provider: str,
    fields: SourceFieldCatalog | None = None,
) -> Dict[str, pd.DataFrame]:
    """Load each financial dataset once for a batch of temporal definitions."""
    source_fields = fields or SourceFieldCatalog()
    grouped: Dict[str, Dict[str, SourceField]] = {}
    for definition in definitions:
        for semantic_id in getattr(definition, "inputs", {}).values():
            source = source_fields.require(semantic_id)
            binding = source.binding_for(provider)
            if binding is None or binding.compatibility != "exact":
                continue
            grouped.setdefault(binding.dataset, {})[semantic_id] = source

    cache: Dict[str, pd.DataFrame] = {}
    for dataset, sources in grouped.items():
        if "/" not in dataset:
            continue
        category, sub = dataset.split("/", 1)
        table = f"dataset_{category}_{sub}".lower()
        with storage.connect(provider) as connection:
            existing = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            if not existing:
                continue
            bindings = {
                semantic_id: source.binding_for(provider)
                for semantic_id, source in sources.items()
            }
            value_fields = {
                binding.field
                for binding in bindings.values()
                if binding is not None and binding.field in existing
            }
            columns = [
                column
                for column in [
                    "ts_code",
                    "end_date",
                    "ann_date",
                    "f_ann_date",
                    "div_proc" if dataset == "financial/dividend" else "",
                    *sorted(value_fields),
                ]
                if column and column in existing
            ]
            select_columns = ", ".join(f'"{column}"' for column in columns)
            raw = pd.read_sql_query(
                f'SELECT {select_columns} FROM "{table}"',
                connection,
            )
        for semantic_id, source in sources.items():
            binding = bindings[semantic_id]
            if binding is None or binding.field not in raw.columns:
                continue
            if raw[binding.field].isna().all():
                continue
            cache[semantic_id] = _prepare_source_input(
                raw[[column for column in raw.columns if column in {
                    "ts_code", "end_date", "ann_date", "f_ann_date", "div_proc", binding.field
                }]],
                source,
                binding.field,
            )
    return cache


def _load_input(
    alias: str,
    source: SourceField,
    provider: str,
    input_cache: Dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if input_cache is not None and source.semantic_id in input_cache:
        cached = input_cache[source.semantic_id].copy()
        return cached.rename(
            columns={
                "__available": f"__available_{alias}",
                "__input": f"__input_{alias}",
            }
        )
    binding = source.binding_for(provider)
    if binding is None or binding.compatibility != "exact":
        raise ValueError(f"{provider} 缺少精确输入字段: {source.semantic_id}")
    if "/" not in binding.dataset:
        raise ValueError(f"财报输入的数据集路径无效: {binding.dataset}")
    category, sub = binding.dataset.split("/", 1)
    requested_columns = [
        "ts_code",
        "end_date",
        "ann_date",
        "f_ann_date",
        "div_proc" if binding.dataset == "financial/dividend" else "",
        binding.field,
    ]
    table = f"dataset_{category}_{sub}".lower()
    with storage.connect(provider) as connection:
        existing = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        if not existing:
            raise ValueError(f"尚未下载输入数据集: {binding.dataset}")
        if binding.field not in existing:
            raise ValueError(f"输入数据集缺少字段: {binding.dataset}.{binding.field}")
        columns = [column for column in requested_columns if column and column in existing]
        select_columns = ", ".join(f'"{column}"' for column in columns)
        frame = pd.read_sql_query(
            f'SELECT {select_columns} FROM "{table}"',
            connection,
        )
    if frame.empty or binding.field not in frame.columns or frame[binding.field].isna().all():
        raise ValueError(f"输入数据集缺少有效字段: {binding.dataset}.{binding.field}")
    prepared = _prepare_source_input(frame, source, binding.field)
    if input_cache is not None:
        input_cache[source.semantic_id] = prepared.copy()
    return prepared.rename(
        columns={
            "__available": f"__available_{alias}",
            "__input": f"__input_{alias}",
        }
    )


def build_point_in_time_events(
    definition: object,
    provider: str,
    fields: SourceFieldCatalog | None = None,
    input_cache: Dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Build factor changes keyed by the first date on which they were knowable."""
    if not is_point_in_time_definition(definition):
        raise ValueError(f"因子不是财报时点定义: {getattr(definition, 'id', '')}")
    source_fields = fields or SourceFieldCatalog()
    optional = set(getattr(definition, "optional_inputs", ()) or ())
    merged: pd.DataFrame | None = None
    runtime_columns: Dict[str, str] = {}
    availability_columns: List[str] = []

    for alias, semantic_id in getattr(definition, "inputs", {}).items():
        source = source_fields.require(semantic_id)
        current = _load_input(alias, source, provider, input_cache=input_cache)
        how = "left" if alias in optional and merged is not None else "inner"
        merged = current if merged is None else merged.merge(current, on=KEY_COLUMNS, how=how)
        runtime_columns[alias] = f"__input_{alias}"
        availability_columns.append(f"__available_{alias}")

    if merged is None or merged.empty:
        return pd.DataFrame(columns=["ts_code", "available_date", definition.id])
    merged["available_date"] = merged[availability_columns].max(axis=1)
    merged = merged.dropna(subset=["available_date"]).sort_values(
        ["ts_code", "end_date", "available_date"]
    )

    expression = compile_expression(
        getattr(definition, "expression"),
        runtime_columns,
        output_name=getattr(definition, "id"),
        output_dtype=getattr(definition, "output_dtype", "float64"),
        window_by=("ts_code",),
    )
    polars_frame = pl.from_pandas(merged, include_index=False, nan_to_null=True)
    result = (
        polars_frame.lazy()
        .sort(["ts_code", "end_date", "available_date"])
        .with_columns(expression)
        .select(["ts_code", "end_date", "available_date", definition.id])
        .collect()
        .to_pandas()
    )
    result = result.dropna(subset=[definition.id])
    # Several report periods can be announced on one date.  The latest report
    # period is the value visible to the daily cross section after that event.
    result = (
        result.sort_values(["ts_code", "available_date", "end_date"])
        .drop_duplicates(["ts_code", "available_date"], keep="last")
    )
    return result[["ts_code", "available_date", definition.id]].reset_index(drop=True)


def align_events_to_daily(
    daily: pd.DataFrame,
    events: pd.DataFrame,
    factor_id: str,
) -> pd.Series:
    """Backward-asof join one event stream to a daily security calendar."""
    aligned = align_event_matrix_to_daily(daily, events, [factor_id])
    if factor_id not in aligned.columns:
        return pd.Series(pd.NA, index=daily.index, dtype="Float64")
    return aligned[factor_id]


def combine_event_streams(events_by_factor: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine factor-specific changes into one forward-filled event timeline."""
    indexed = []
    factor_ids = []
    for factor_id, events in events_by_factor.items():
        factor_ids.append(factor_id)
        if events.empty:
            continue
        indexed.append(
            events[["ts_code", "available_date", factor_id]].set_index(
                ["ts_code", "available_date"]
            )
        )
    if not indexed:
        return pd.DataFrame(columns=["ts_code", "available_date", *factor_ids])
    combined = pd.concat(indexed, axis=1, join="outer").reset_index()
    combined = combined.sort_values(["ts_code", "available_date"])
    combined[factor_ids] = combined.groupby("ts_code", sort=False)[factor_ids].ffill()
    return combined.reset_index(drop=True)


def align_event_matrix_to_daily(
    daily: pd.DataFrame,
    events: pd.DataFrame,
    factor_ids: List[str],
) -> pd.DataFrame:
    """Backward-asof join a wide event timeline to a daily security calendar."""
    if daily.empty or events.empty:
        return pd.DataFrame(
            {factor_id: pd.Series(pd.NA, index=daily.index, dtype="Float64") for factor_id in factor_ids},
            index=daily.index,
        )
    left = daily[["ts_code", "trade_date"]].copy()
    left["__row_id"] = range(len(left))
    available_factors = [factor_id for factor_id in factor_ids if factor_id in events.columns]
    right = events[["ts_code", "available_date", *available_factors]].copy()
    left_pl = pl.from_pandas(left, include_index=False).with_columns(
        pl.col("trade_date").str.to_date(strict=False)
    )
    right_pl = pl.from_pandas(right, include_index=False, nan_to_null=True).with_columns(
        pl.col("available_date").str.to_date(strict=False)
    )
    joined = (
        left_pl.sort(["ts_code", "trade_date"])
        .join_asof(
            right_pl.sort(["ts_code", "available_date"]),
            left_on="trade_date",
            right_on="available_date",
            by="ts_code",
            strategy="backward",
            check_sortedness=False,
        )
        .sort("__row_id")
    )
    result = pd.DataFrame(index=daily.index)
    for factor_id in factor_ids:
        values = (
            joined.get_column(factor_id).to_list()
            if factor_id in joined.columns
            else [pd.NA] * len(daily)
        )
        result[factor_id] = pd.Series(values, index=daily.index, dtype="Float64")
    return result
