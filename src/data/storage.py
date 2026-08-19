"""Provider-isolated SQLite storage with the legacy data API surface.

Each configured provider owns one database at ``workspace/data/providers/<name>/market.db``.
Datasets keep their logical monthly/stock partitions in a ``_partition`` column,
so existing query, factor and snapshot code can continue to use ``save``/``load``
without knowing the physical storage format.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from .config import get_active_provider_name, get_provider_db_path

_IDENTIFIER_RE = re.compile(r"[^0-9A-Za-z_]+")


def _provider_name(provider: Optional[str] = None) -> str:
    return (provider or get_active_provider_name()).lower()


def get_database_path(provider: Optional[str] = None) -> Path:
    return get_provider_db_path(_provider_name(provider))


@contextmanager
def connect(provider: Optional[str] = None):
    """Open a configured SQLite connection with safe concurrent read settings."""
    path = get_database_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS _datasets (
            table_name TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            sub TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            partition_count INTEGER NOT NULL DEFAULT 0,
            latest_date TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS _ingestion_commits (
            dataset TEXT NOT NULL,
            commit_key TEXT NOT NULL,
            row_counts TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            PRIMARY KEY (dataset, commit_key)
        )
        """
    )
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_name(category: str, sub: str) -> str:
    raw = f"dataset_{category}_{sub or 'root'}"
    return _IDENTIFIER_RE.sub("_", raw).strip("_").lower()


def get_path(
    category: str,
    sub: str,
    partition: str,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> Path:
    """Return the physical database path (kept for legacy diagnostics)."""
    if base_dir is not None:
        return Path(base_dir) / f"{_provider_name(provider)}.db"
    return get_database_path(provider)


def get_financial_path(sub: str, partition: str, provider: Optional[str] = None) -> Path:
    """Return the physical provider database path for legacy callers."""
    return get_database_path(provider)


def get_month(value: str) -> str:
    return str(value)[:7]


def get_months_between(start_date: str, end_date: str) -> List[str]:
    months = pd.date_range(start_date, end_date, freq="MS").strftime("%Y-%m").tolist()
    months.extend([start_date[:7], end_date[:7]])
    return sorted(set(months))


def _sqlite_type(series: pd.Series, column: str = "") -> str:
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_numeric_dtype(series):
        return "REAL"
    if not series.notna().any():
        lowered = column.lower()
        text_hints = (
            "date", "code", "name", "type", "status", "industry", "area",
            "market", "exchange", "currency", "flag", "id",
        )
        return "TEXT" if any(hint in lowered for hint in text_hints) else "REAL"
    return "TEXT"


def _to_sql_value(value):
    if value is None or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool):
        return int(value)
    return value


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result = result.loc[:, ~result.columns.duplicated(keep="last")]
    if "_partition" in result.columns:
        result = result.drop(columns=["_partition"])
    for column in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            result[column] = result[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    return result


def _existing_columns(connection: sqlite3.Connection, table: str) -> Dict[str, str]:
    rows = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return {str(row[1]): str(row[2]) for row in rows}


def _ensure_table(
    connection: sqlite3.Connection,
    table: str,
    frame: pd.DataFrame,
) -> None:
    existing = _existing_columns(connection, table)
    if not existing:
        definitions = [f'{_quote("_partition")} TEXT NOT NULL']
        definitions.extend(
            f"{_quote(column)} {_sqlite_type(frame[column], column)}" for column in frame.columns
        )
        connection.execute(f"CREATE TABLE {_quote(table)} ({', '.join(definitions)})")
        connection.execute(
            f"CREATE INDEX {_quote('idx_' + table + '_partition')} "
            f"ON {_quote(table)} ({_quote('_partition')})"
        )
        if "ts_code" in frame.columns:
            connection.execute(
                f"CREATE INDEX {_quote('idx_' + table + '_stock')} "
                f"ON {_quote(table)} ({_quote('_partition')}, {_quote('ts_code')})"
            )
        return

    for column in frame.columns:
        if column not in existing:
            connection.execute(
                f"ALTER TABLE {_quote(table)} ADD COLUMN {_quote(column)} "
                f"{_sqlite_type(frame[column], column)}"
            )


def _ensure_merge_index(
    connection: sqlite3.Connection,
    table: str,
    merge_on: Sequence[str],
) -> bool:
    if not merge_on:
        return False
    suffix = "_".join(_IDENTIFIER_RE.sub("_", key).lower() for key in merge_on)
    index_name = f"uidx_{table}_merge_{suffix}"[:120]
    columns = ["_partition", *merge_on]
    existing_indexes = connection.execute(f"PRAGMA index_list({_quote(table)})").fetchall()
    if any(str(row[1]) == index_name and int(row[2]) == 1 for row in existing_indexes):
        return False

    # Older databases used a non-unique performance index.  Keep the last row
    # for each logical key before installing the database-level constraint.
    grouped = ", ".join(_quote(column) for column in columns)
    connection.execute(
        f"DELETE FROM {_quote(table)} WHERE rowid NOT IN "
        f"(SELECT MAX(rowid) FROM {_quote(table)} GROUP BY {grouped})"
    )
    connection.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_quote(index_name)} ON {_quote(table)} "
        f"({', '.join(_quote(column) for column in columns)})"
    )
    return True


def _update_catalog(
    connection: sqlite3.Connection,
    table: str,
    category: str,
    sub: str,
) -> None:
    row_count = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
    partition_count = connection.execute(
        f"SELECT COUNT(DISTINCT {_quote('_partition')}) FROM {_quote(table)}"
    ).fetchone()[0]
    columns = _existing_columns(connection, table)
    latest_date = None
    for candidate in ("trade_date", "end_date", "ann_date", "cal_date"):
        if candidate in columns:
            latest_date = connection.execute(
                f"SELECT MAX({_quote(candidate)}) FROM {_quote(table)}"
            ).fetchone()[0]
            break
    connection.execute(
        """
        INSERT INTO _datasets
            (table_name, category, sub, row_count, partition_count, latest_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            row_count=excluded.row_count,
            partition_count=excluded.partition_count,
            latest_date=excluded.latest_date,
            updated_at=excluded.updated_at
        """,
        (
            table,
            category,
            sub,
            row_count,
            partition_count,
            latest_date,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def _update_catalog_incremental(
    connection: sqlite3.Connection,
    table: str,
    category: str,
    sub: str,
    delta_rows: int,
    new_partition: bool,
    frame: pd.DataFrame,
) -> None:
    existing = connection.execute(
        "SELECT row_count, partition_count, latest_date FROM _datasets WHERE table_name=?",
        (table,),
    ).fetchone()
    row_count = max(0, int(existing[0]) + delta_rows) if existing else max(0, delta_rows)
    partition_count = int(existing[1]) if existing else 0
    if new_partition:
        partition_count += 1
    latest_date = existing[2] if existing else None
    for candidate in ("trade_date", "end_date", "ann_date", "cal_date"):
        if candidate in frame.columns and frame[candidate].notna().any():
            incoming = str(frame[candidate].dropna().max())
            latest_date = max(str(latest_date or ""), incoming) or None
            break
    connection.execute(
        """
        INSERT INTO _datasets
            (table_name, category, sub, row_count, partition_count, latest_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            row_count=excluded.row_count,
            partition_count=excluded.partition_count,
            latest_date=excluded.latest_date,
            updated_at=excluded.updated_at
        """,
        (
            table,
            category,
            sub,
            row_count,
            partition_count,
            latest_date,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def _save_frame(
    connection: sqlite3.Connection,
    df: pd.DataFrame,
    category: str,
    sub: str,
    partition: str,
    mode: str = "overwrite",
    merge_on: List[str] = None,
) -> int:
    """Write one frame using the caller's transaction and return its row count."""
    frame = _prepare_frame(df)
    if mode == "merge" and merge_on:
        usable_keys = [key for key in merge_on if key in frame.columns]
        if usable_keys:
            frame = frame.drop_duplicates(subset=usable_keys, keep="last")
    table = _table_name(category, sub)
    _ensure_table(connection, table, frame)
    partition_rows_before = int(
        connection.execute(
            f"SELECT COUNT(*) FROM {_quote(table)} WHERE {_quote('_partition')}=?",
            (partition,),
        ).fetchone()[0]
    )
    partition_existed = partition_rows_before > 0
    index_migrated = False
    merge_keys: List[str] = []
    if mode == "overwrite":
        connection.execute(
            f"DELETE FROM {_quote(table)} WHERE {_quote('_partition')} = ?",
            (partition,),
        )
    elif mode == "merge" and merge_on:
        merge_keys = [key for key in merge_on if key in frame.columns]
        if merge_keys:
            index_migrated = _ensure_merge_index(connection, table, merge_keys)

    columns = ["_partition", *frame.columns.tolist()]
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = (
        f"INSERT INTO {_quote(table)} "
        f"({', '.join(_quote(column) for column in columns)}) VALUES ({placeholders})"
    )
    if merge_keys:
        conflict_columns = ["_partition", *merge_keys]
        update_columns = [
            column for column in frame.columns if column not in merge_keys
        ]
        conflict_target = ", ".join(_quote(column) for column in conflict_columns)
        if update_columns:
            assignments = ", ".join(
                f"{_quote(column)}=excluded.{_quote(column)}"
                for column in update_columns
            )
            insert_sql += (
                f" ON CONFLICT ({conflict_target}) DO UPDATE SET {assignments}"
            )
        else:
            insert_sql += f" ON CONFLICT ({conflict_target}) DO NOTHING"
    rows = [
        (partition, *(_to_sql_value(value) for value in row))
        for row in frame.itertuples(index=False, name=None)
    ]
    connection.executemany(insert_sql, rows)
    if index_migrated:
        _update_catalog(connection, table, category, sub)
    else:
        if merge_keys:
            partition_rows_after = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote(table)} "
                    f"WHERE {_quote('_partition')}=?",
                    (partition,),
                ).fetchone()[0]
            )
            delta_rows = partition_rows_after - partition_rows_before
        elif mode == "overwrite":
            delta_rows = len(rows) - partition_rows_before
        else:
            delta_rows = len(rows)
        _update_catalog_incremental(
            connection,
            table,
            category,
            sub,
            delta_rows,
            not partition_existed,
            frame,
        )
    return len(rows)


def save(
    df: pd.DataFrame,
    category: str,
    sub: str,
    partition: str,
    mode: str = "overwrite",
    merge_on: List[str] = None,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> bool:
    """Store one logical partition, optionally replacing rows by merge keys."""
    if df is None or df.empty:
        return False
    try:
        with connect(provider) as connection:
            _save_frame(
                connection,
                df,
                category,
                sub,
                partition,
                mode,
                merge_on,
            )
        return True
    except Exception as exc:
        print(f"保存失败 {category}/{sub}/{partition}: {exc}")
        return False


_DAILY_SNAPSHOT_SUBS = ("raw", "adj_factor", "indicator")
_FINANCIAL_CORE_SUBS = ("income", "balancesheet", "cashflow", "fina_indicator")


def _validate_daily_frames(
    frames: Dict[str, pd.DataFrame],
    partition: str,
    commit_date: Optional[str],
) -> None:
    missing = [sub for sub in _DAILY_SNAPSHOT_SUBS if sub not in frames or frames[sub].empty]
    if missing:
        raise ValueError(f"日线事务缺少数据集: {', '.join(missing)}")

    code_sets: Dict[str, set] = {}
    for sub in _DAILY_SNAPSHOT_SUBS:
        frame = frames[sub]
        keys = ["ts_code", "trade_date"]
        absent = [key for key in keys if key not in frame.columns]
        if absent:
            raise ValueError(f"daily/{sub} 缺少键: {', '.join(absent)}")
        if frame[keys].isna().any().any():
            raise ValueError(f"daily/{sub} 的日期或股票代码为空")
        if frame.duplicated(keys).any():
            raise ValueError(f"daily/{sub} 存在重复的日期+股票记录")
        months = set(frame["trade_date"].astype(str).str[:7])
        if months != {partition}:
            raise ValueError(f"daily/{sub} 包含分区 {partition} 之外的数据")
        if commit_date is not None and set(frame["trade_date"].astype(str)) != {commit_date}:
            raise ValueError(f"daily/{sub} 不是 {commit_date} 的单日快照")
        code_sets[sub] = set(frame["ts_code"].astype(str))

    if code_sets["raw"] != code_sets["indicator"]:
        raise ValueError("行情与每日指标的股票集合不一致")
    if not code_sets["raw"].issubset(code_sets["adj_factor"]):
        raise ValueError("部分行情缺少复权因子")


def save_daily_frames_atomic(
    frames: Dict[str, pd.DataFrame],
    partition: str,
    provider: Optional[str] = None,
    commit_date: Optional[str] = None,
) -> bool:
    """Atomically merge raw quotes, factors and indicators in one transaction."""
    try:
        _validate_daily_frames(frames, partition, commit_date)
        row_counts: Dict[str, int] = {}
        with connect(provider) as connection:
            for sub in _DAILY_SNAPSHOT_SUBS:
                row_counts[sub] = _save_frame(
                    connection,
                    frames[sub],
                    "daily",
                    sub,
                    partition,
                    mode="merge",
                    merge_on=["ts_code", "trade_date"],
                )
            if commit_date is not None:
                _record_ingestion_commit(
                    connection,
                    "daily_snapshot",
                    commit_date,
                    row_counts,
                )
        return True
    except Exception as exc:
        print(f"日线原子写入失败 {partition}: {exc}")
        return False


def save_daily_partitions_atomic(
    partitions: Dict[str, Dict[str, pd.DataFrame]],
    provider: Optional[str] = None,
) -> bool:
    """Write a multi-month historical batch with one connection and commit."""
    try:
        for partition, frames in partitions.items():
            _validate_daily_frames(frames, partition, commit_date=None)
        with connect(provider) as connection:
            for partition, frames in sorted(partitions.items()):
                for sub in _DAILY_SNAPSHOT_SUBS:
                    _save_frame(
                        connection,
                        frames[sub],
                        "daily",
                        sub,
                        partition,
                        mode="merge",
                        merge_on=["ts_code", "trade_date"],
                    )
        return True
    except Exception as exc:
        print(f"历史日线批次原子写入失败: {exc}")
        return False


def _record_ingestion_commit(
    connection: sqlite3.Connection,
    dataset: str,
    commit_key: str,
    payload: Dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO _ingestion_commits
            (dataset, commit_key, row_counts, committed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dataset, commit_key) DO UPDATE SET
            row_counts=excluded.row_counts,
            committed_at=excluded.committed_at
        """,
        (
            dataset,
            commit_key,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def list_ingestion_commits(
    dataset: str,
    start_key: Optional[str] = None,
    end_key: Optional[str] = None,
    provider: Optional[str] = None,
) -> List[str]:
    if not get_database_path(provider).exists():
        return []
    clauses = ["dataset=?"]
    parameters: List[object] = [dataset]
    if start_key:
        clauses.append("commit_key >= ?")
        parameters.append(start_key)
    if end_key:
        clauses.append("commit_key <= ?")
        parameters.append(end_key)
    try:
        with connect(provider) as connection:
            rows = connection.execute(
                "SELECT commit_key FROM _ingestion_commits "
                f"WHERE {' AND '.join(clauses)} ORDER BY commit_key",
                parameters,
            ).fetchall()
            return [str(row[0]) for row in rows]
    except sqlite3.Error:
        return []


def get_ingestion_commit(
    dataset: str,
    commit_key: str,
    provider: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    if not get_database_path(provider).exists():
        return None
    try:
        with connect(provider) as connection:
            row = connection.execute(
                "SELECT row_counts, committed_at FROM _ingestion_commits "
                "WHERE dataset=? AND commit_key=?",
                (dataset, commit_key),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        payload["committed_at"] = str(row[1])
        return payload
    except (json.JSONDecodeError, sqlite3.Error):
        return None


def save_ingestion_commit(
    dataset: str,
    commit_key: str,
    payload: Dict[str, object],
    provider: Optional[str] = None,
) -> bool:
    """Persist a metadata-only ingestion checkpoint.

    Some provider queries are valid but have no rows (for example a delisted
    stock outside the configured history window).  Recording that terminal
    result prevents every incremental run from retrying the same empty query.
    """
    try:
        with connect(provider) as connection:
            _record_ingestion_commit(connection, dataset, commit_key, payload)
        return True
    except Exception:
        return False


def _financial_merge_keys(frame: pd.DataFrame) -> List[str]:
    keys = [key for key in ("ts_code", "end_date") if key in frame.columns]
    for optional in ("ann_date", "f_ann_date", "report_type", "update_flag"):
        if optional in frame.columns:
            keys.append(optional)
    return keys


def _save_partitioned_frame(
    connection: sqlite3.Connection,
    frame: pd.DataFrame,
    category: str,
    sub: str,
    partition_column: str,
    merge_on: List[str],
) -> int:
    """Merge a frame whose logical partitions are supplied by one of its columns."""
    prepared = _prepare_frame(frame)
    if partition_column not in prepared.columns:
        raise ValueError(f"{category}/{sub} 缺少分区列 {partition_column}")
    keys = [key for key in merge_on if key in prepared.columns]
    if not keys:
        raise ValueError(f"{category}/{sub} 缺少合并键")
    prepared = prepared.drop_duplicates(subset=keys, keep="last")
    table = _table_name(category, sub)
    _ensure_table(connection, table, prepared)
    _ensure_merge_index(connection, table, keys)

    partitions = prepared[partition_column].astype(str).tolist()
    where = " AND ".join(f"{_quote(key)} IS ?" for key in keys)
    delete_sql = f"DELETE FROM {_quote(table)} WHERE {_quote('_partition')} = ? AND {where}"
    delete_rows = [
        (partition, *(_to_sql_value(value) for value in row))
        for partition, row in zip(
            partitions,
            prepared[keys].itertuples(index=False, name=None),
        )
    ]
    connection.executemany(delete_sql, delete_rows)

    columns = ["_partition", *prepared.columns.tolist()]
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = (
        f"INSERT INTO {_quote(table)} "
        f"({', '.join(_quote(column) for column in columns)}) VALUES ({placeholders})"
    )
    rows = [
        (partition, *(_to_sql_value(value) for value in row))
        for partition, row in zip(
            partitions,
            prepared.itertuples(index=False, name=None),
        )
    ]
    connection.executemany(insert_sql, rows)
    _update_catalog(connection, table, category, sub)
    return len(rows)


def save_financial_period_atomic(
    frames: Dict[str, pd.DataFrame],
    period: str,
    provider: Optional[str] = None,
) -> bool:
    """Persist one complete Tushare core-financial cross-section atomically."""
    try:
        missing = [sub for sub in _FINANCIAL_CORE_SUBS if sub not in frames or frames[sub].empty]
        if missing:
            raise ValueError(f"报告期 {period} 缺少数据集: {', '.join(missing)}")
        row_counts: Dict[str, int] = {}
        with connect(provider) as connection:
            for sub in _FINANCIAL_CORE_SUBS:
                frame = frames[sub]
                if "end_date" not in frame.columns or set(frame["end_date"].dropna()) != {period}:
                    raise ValueError(f"financial/{sub} 包含 {period} 之外的数据")
                row_counts[sub] = _save_partitioned_frame(
                    connection,
                    frame,
                    "financial",
                    sub,
                    "ts_code",
                    _financial_merge_keys(frame),
                )
            _record_ingestion_commit(
                connection,
                "financial_core_period",
                period,
                row_counts,
            )
        return True
    except Exception as exc:
        print(f"报告期财务数据原子写入失败 {period}: {exc}")
        return False


def save_financial_bundle_atomic(
    bundle: Dict[str, pd.DataFrame],
    ts_code: str,
    provider: Optional[str] = None,
    checkpoint_date: Optional[str] = None,
    checkpoint_from_date: Optional[str] = None,
    checkpoint_terminal: bool = False,
) -> bool:
    """Persist one stock's available financial datasets in one transaction."""
    frames = {sub: frame for sub, frame in bundle.items() if frame is not None and not frame.empty}
    if not frames:
        return False
    try:
        row_counts: Dict[str, object] = {}
        with connect(provider) as connection:
            for sub, frame in frames.items():
                keys = _financial_merge_keys(frame)
                merge = bool(keys) and sub in _FINANCIAL_CORE_SUBS
                row_counts[sub] = _save_frame(
                    connection,
                    frame,
                    "financial",
                    sub,
                    ts_code,
                    mode="merge" if merge else "overwrite",
                    merge_on=keys if merge else None,
                )
            if checkpoint_date:
                row_counts["through_date"] = checkpoint_date
                if checkpoint_from_date:
                    row_counts["from_date"] = checkpoint_from_date
                if checkpoint_terminal:
                    row_counts["terminal"] = True
                _record_ingestion_commit(
                    connection,
                    "financial_stock_checkpoint",
                    ts_code,
                    row_counts,
                )
        return True
    except Exception as exc:
        print(f"股票财务数据原子写入失败 {ts_code}: {exc}")
        return False


def save_dividend_batch_atomic(
    frames: Dict[str, pd.DataFrame],
    checkpoint_date: str,
    provider: Optional[str] = None,
) -> bool:
    """Persist fetched stock dividend histories with one SQLite transaction."""
    if not frames:
        return True
    try:
        with connect(provider) as connection:
            for ts_code, frame in frames.items():
                row_count = 0
                if frame is not None and not frame.empty:
                    if "ts_code" not in frame.columns:
                        raise ValueError(f"{ts_code} 分红数据缺少 ts_code")
                    frame_codes = set(frame["ts_code"].dropna().astype(str))
                    if frame_codes != {ts_code}:
                        raise ValueError(
                            f"{ts_code} 分红数据包含其他股票: {sorted(frame_codes)}"
                        )
                    row_count = _save_frame(
                        connection,
                        frame,
                        "financial",
                        "dividend",
                        ts_code,
                        mode="overwrite",
                    )
                _record_ingestion_commit(
                    connection,
                    "dividend_stock_checkpoint",
                    ts_code,
                    {
                        "through_date": checkpoint_date,
                        "status": "ready" if row_count else "no_data",
                        "row_count": row_count,
                    },
                )
        return True
    except Exception as exc:
        print(f"分红历史批次原子写入失败: {exc}")
        return False


def list_daily_snapshot_commits(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    provider: Optional[str] = None,
) -> List[str]:
    """List dates whose three daily datasets committed in one transaction."""
    return list_ingestion_commits(
        "daily_snapshot",
        start_date,
        end_date,
        provider,
    )


def save_financial(
    df: pd.DataFrame,
    sub: str,
    partition: str,
    mode: str = "overwrite",
    merge_on: List[str] = None,
    provider: Optional[str] = None,
) -> bool:
    return save(
        df,
        "financial",
        sub,
        partition,
        mode=mode,
        merge_on=merge_on,
        provider=provider,
    )


def _build_filters(
    filters: Optional[Sequence[Tuple[str, str, object]]],
    existing: Dict[str, str],
) -> Tuple[List[str], List[object]]:
    clauses: List[str] = []
    parameters: List[object] = []
    operators = {"==": "=", "=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<="}
    for column, operator, value in filters or []:
        if column not in existing:
            continue
        if operator == "in" and isinstance(value, (list, tuple, set)):
            values = list(value)
            if not values:
                clauses.append("1 = 0")
                continue
            clauses.append(f"{_quote(column)} IN ({', '.join('?' for _ in values)})")
            parameters.extend(values)
        elif operator in operators:
            clauses.append(f"{_quote(column)} {operators[operator]} ?")
            parameters.append(value)
    return clauses, parameters


def load(
    category: str,
    sub: str,
    partitions: List[str],
    columns: List[str] = None,
    base_dir: Path = None,
    filters: list = None,
    provider: Optional[str] = None,
) -> pd.DataFrame:
    """Load one or more logical partitions using SQL predicate pushdown."""
    if not partitions:
        return pd.DataFrame(columns=columns)
    table = _table_name(category, sub)
    if not get_database_path(provider).exists():
        return pd.DataFrame(columns=columns)
    try:
        with connect(provider) as connection:
            existing = _existing_columns(connection, table)
            if not existing:
                return pd.DataFrame(columns=columns)
            requested = columns or [column for column in existing if column != "_partition"]
            selected = [column for column in requested if column in existing and column != "_partition"]
            if not selected:
                return pd.DataFrame(columns=requested)
            clauses = [
                f"{_quote('_partition')} IN ({', '.join('?' for _ in partitions)})"
            ]
            parameters: List[object] = list(partitions)
            filter_clauses, filter_parameters = _build_filters(filters, existing)
            clauses.extend(filter_clauses)
            parameters.extend(filter_parameters)
            query = (
                f"SELECT {', '.join(_quote(column) for column in selected)} "
                f"FROM {_quote(table)} WHERE {' AND '.join(clauses)}"
            )
            frame = pd.read_sql_query(query, connection, params=parameters)
            for missing in [column for column in requested if column not in frame.columns]:
                frame[missing] = pd.NA
            return frame[requested]
    except sqlite3.Error:
        return pd.DataFrame(columns=columns)


def _merge_stock_date_windows(
    windows: Sequence[Tuple[str, str, str]],
) -> List[Tuple[str, str, str]]:
    """Merge overlapping date windows per stock before hitting SQLite."""
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for ts_code, start_date, end_date in windows:
        code = str(ts_code or "").strip()
        start = str(start_date or "")[:10]
        end = str(end_date or "")[:10]
        if not code or not start or not end:
            continue
        if start > end:
            raise ValueError(f"行情窗口起始日不能晚于结束日: {code} {start} ~ {end}")
        grouped.setdefault(code, []).append((start, end))

    merged: List[Tuple[str, str, str]] = []
    for code, ranges in grouped.items():
        current_start = ""
        current_end = ""
        for start, end in sorted(ranges):
            if current_start and start <= current_end:
                current_end = max(current_end, end)
                continue
            if current_start:
                merged.append((code, current_start, current_end))
            current_start, current_end = start, end
        if current_start:
            merged.append((code, current_start, current_end))
    return merged


def _preferred_stock_date_index(
    connection: sqlite3.Connection,
    table: str,
) -> Optional[str]:
    indexes = [str(row[1]) for row in connection.execute(
        f"PRAGMA index_list({_quote(table)})"
    ).fetchall()]
    unique_prefix = f"uidx_{table}_merge_ts_code_trade_date"
    if unique_prefix in indexes:
        return unique_prefix
    stock_index = f"idx_{table}_stock"
    return stock_index if stock_index in indexes else None


def load_hfq_close_windows(
    windows: Sequence[Tuple[str, str, str]],
    provider: Optional[str] = None,
) -> pd.DataFrame:
    """Load many stock/date windows in one indexed SQLite pass.

    The temporary request table lets SQLite deduplicate overlapping cross-section
    horizons while keeping the large provider database read-only.  Raw close and
    adjustment factor are joined inside SQLite, so pandas does not materialize and
    sort two independent frames for every cross-section.
    """
    columns = ["ts_code", "trade_date", "close", "raw_close"]
    merged = _merge_stock_date_windows(windows)
    if not merged or not get_database_path(provider).exists():
        return pd.DataFrame(columns=columns)

    request_rows = set()
    for code, start_date, end_date in merged:
        for month in get_months_between(start_date, end_date):
            month_start = f"{month}-01"
            month_end = f"{month}-{pd.Period(month).days_in_month:02d}"
            request_rows.add((
                month,
                code,
                max(start_date, month_start),
                min(end_date, month_end),
            ))

    raw_table = _table_name("daily", "raw")
    adj_table = _table_name("daily", "adj_factor")
    with connect(provider) as connection:
        raw_columns = _existing_columns(connection, raw_table)
        adj_columns = _existing_columns(connection, adj_table)
        if not {"ts_code", "trade_date", "close"}.issubset(raw_columns):
            return pd.DataFrame(columns=columns)
        if not {"ts_code", "trade_date", "adj_factor"}.issubset(adj_columns):
            raise RuntimeError("缺少复权因子，不能计算后复权行情")

        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA cache_size=-131072")
        connection.execute("PRAGMA mmap_size=268435456")
        connection.execute(
            """
            CREATE TEMP TABLE requested_hfq_windows (
                _partition TEXT NOT NULL,
                ts_code TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO requested_hfq_windows VALUES (?, ?, ?, ?)",
            sorted(request_rows),
        )

        raw_index = _preferred_stock_date_index(connection, raw_table)
        adj_index = _preferred_stock_date_index(connection, adj_table)
        raw_index_sql = f" INDEXED BY {_quote(raw_index)}" if raw_index else ""
        adj_index_sql = f" INDEXED BY {_quote(adj_index)}" if adj_index else ""
        query = f"""
            SELECT
                raw.ts_code,
                raw.trade_date,
                raw.close AS raw_close,
                factors.adj_factor
            FROM requested_hfq_windows AS requested
            CROSS JOIN {_quote(raw_table)} AS raw{raw_index_sql}
            LEFT JOIN {_quote(adj_table)} AS factors{adj_index_sql}
              ON factors._partition = raw._partition
             AND factors.ts_code = raw.ts_code
             AND factors.trade_date = raw.trade_date
            WHERE raw._partition = requested._partition
              AND raw.ts_code = requested.ts_code
              AND raw.trade_date >= requested.start_date
              AND raw.trade_date <= requested.end_date
        """
        frame = pd.read_sql_query(query, connection)

    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = frame.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    missing_factors = frame["adj_factor"].isna()
    if missing_factors.any():
        raise RuntimeError(
            "复权因子不完整："
            f"{int(frame.loc[missing_factors, 'ts_code'].nunique())} 只股票、"
            f"{int(missing_factors.sum())} 行行情无法复权"
        )
    frame["raw_close"] = pd.to_numeric(frame["raw_close"], errors="coerce")
    frame["adj_factor"] = pd.to_numeric(frame["adj_factor"], errors="coerce")
    if frame["adj_factor"].isna().any():
        raise RuntimeError("复权因子包含非数值，无法计算复权行情")
    frame["close"] = (frame["raw_close"] * frame["adj_factor"]).round(4)
    return frame[columns].sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def load_one(
    category: str,
    sub: str,
    partition: str,
    columns: List[str] = None,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> pd.DataFrame:
    return load(category, sub, [partition], columns, base_dir, provider=provider)


def load_financial(
    sub: str,
    partitions: List[str] = None,
    columns: List[str] = None,
    provider: Optional[str] = None,
) -> pd.DataFrame:
    if partitions is None:
        partitions = list_financial_partitions(sub, provider=provider)
    return load("financial", sub, partitions, columns, provider=provider)


def list_partitions(
    category: str,
    sub: str,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> List[str]:
    if not get_database_path(provider).exists():
        return []
    table = _table_name(category, sub)
    try:
        with connect(provider) as connection:
            if not _existing_columns(connection, table):
                return []
            rows = connection.execute(
                f"SELECT DISTINCT {_quote('_partition')} FROM {_quote(table)} "
                f"ORDER BY {_quote('_partition')}"
            ).fetchall()
            return [str(row[0]) for row in rows]
    except sqlite3.Error:
        return []


def list_distinct_values(
    category: str,
    sub: str,
    column: str,
    provider: Optional[str] = None,
) -> List[str]:
    """Return distinct non-null values without loading a full dataset into memory."""
    if not get_database_path(provider).exists():
        return []
    table = _table_name(category, sub)
    try:
        with connect(provider) as connection:
            existing = _existing_columns(connection, table)
            if column not in existing:
                return []
            rows = connection.execute(
                f"SELECT DISTINCT {_quote(column)} FROM {_quote(table)} "
                f"WHERE {_quote(column)} IS NOT NULL ORDER BY {_quote(column)}"
            ).fetchall()
            return [str(row[0]) for row in rows]
    except sqlite3.Error:
        return []


def list_financial_partitions(sub: str, provider: Optional[str] = None) -> List[str]:
    return list_partitions("financial", sub, provider=provider)


def exists(
    category: str,
    sub: str,
    partition: str,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> bool:
    return partition in list_partitions(category, sub, base_dir, provider)


def get_latest_partition(
    category: str,
    sub: str,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> Optional[str]:
    partitions = list_partitions(category, sub, base_dir, provider)
    return partitions[-1] if partitions else None


def get_latest_date(category: str, sub: str, provider: Optional[str] = None) -> Optional[str]:
    table = _table_name(category, sub)
    if not get_database_path(provider).exists():
        return None
    try:
        with connect(provider) as connection:
            columns = _existing_columns(connection, table)
            for candidate in ("trade_date", "end_date", "ann_date", "cal_date"):
                if candidate in columns:
                    row = connection.execute(
                        f"SELECT MAX({_quote(candidate)}) FROM {_quote(table)}"
                    ).fetchone()
                    return row[0] if row else None
    except sqlite3.Error:
        return None
    return None


def delete(
    category: str,
    sub: str,
    partition: str,
    base_dir: Path = None,
    provider: Optional[str] = None,
) -> bool:
    table = _table_name(category, sub)
    if not get_database_path(provider).exists():
        return False
    try:
        with connect(provider) as connection:
            if not _existing_columns(connection, table):
                return False
            cursor = connection.execute(
                f"DELETE FROM {_quote(table)} WHERE {_quote('_partition')} = ?",
                (partition,),
            )
            _update_catalog(connection, table, category, sub)
            return cursor.rowcount > 0
    except sqlite3.Error:
        return False


def get_database_status(provider: Optional[str] = None) -> Dict[str, object]:
    """Return database and dataset metadata for the data management UI."""
    name = _provider_name(provider)
    path = get_database_path(name)
    result: Dict[str, object] = {
        "provider": name,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "datasets": [],
    }
    if not path.exists():
        return result
    try:
        with connect(name) as connection:
            rows = connection.execute(
                "SELECT category, sub, row_count, partition_count, latest_date, updated_at "
                "FROM _datasets ORDER BY category, sub"
            ).fetchall()
        result["datasets"] = [
            {
                "category": row[0],
                "sub": row[1],
                "row_count": row[2],
                "partition_count": row[3],
                "latest_date": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]
    except sqlite3.Error:
        pass
    return result
