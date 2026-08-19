"""Definition-versioned materialization state stored beside provider data."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from . import storage
from .config import SUPPORTED_PROVIDERS


_STATUSES = {"pending", "computing", "ready", "stale", "failed"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS _factor_materializations (
            factor_id TEXT PRIMARY KEY,
            definition_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            row_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            error TEXT
        )
        """
    )


def list_factor_materializations(provider: str) -> Dict[str, Dict[str, Any]]:
    """Read all factor states without creating a missing provider database."""
    if not storage.get_database_path(provider).exists():
        return {}
    try:
        with storage.connect(provider) as connection:
            _ensure_table(connection)
            rows = connection.execute(
                "SELECT factor_id, definition_hash, status, start_date, end_date, "
                "row_count, updated_at, error FROM _factor_materializations"
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        str(row[0]): {
            "factor_id": str(row[0]),
            "definition_hash": str(row[1]),
            "status": str(row[2]),
            "start_date": row[3],
            "end_date": row[4],
            "row_count": int(row[5] or 0),
            "updated_at": row[6],
            "error": row[7],
        }
        for row in rows
    }


def set_factor_materialization(
    provider: str,
    factor_id: str,
    definition_hash: str,
    status: str,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    row_count: int = 0,
    error: Optional[str] = None,
) -> None:
    if status not in _STATUSES:
        raise ValueError(f"不支持的因子物化状态: {status}")
    with storage.connect(provider) as connection:
        _ensure_table(connection)
        connection.execute(
            """
            INSERT INTO _factor_materializations
                (factor_id, definition_hash, status, start_date, end_date,
                 row_count, updated_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(factor_id) DO UPDATE SET
                definition_hash=excluded.definition_hash,
                status=excluded.status,
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                row_count=excluded.row_count,
                updated_at=excluded.updated_at,
                error=excluded.error
            """,
            (
                factor_id,
                definition_hash,
                status,
                start_date,
                end_date,
                int(row_count),
                _now(),
                error,
            ),
        )


def invalidate_factor_materializations(
    factor_id: str,
    definition_hash: str,
    providers: Optional[Iterable[str]] = None,
) -> None:
    """Mark existing provider materializations stale after a definition edit."""
    for provider in providers or SUPPORTED_PROVIDERS:
        if not storage.get_database_path(provider).exists():
            continue
        existing = list_factor_materializations(provider)
        column_exists = False
        try:
            with storage.connect(provider) as connection:
                columns = connection.execute(
                    'PRAGMA table_info("dataset_daily_factors")'
                ).fetchall()
                column_exists = factor_id in {str(column[1]) for column in columns}
        except sqlite3.Error:
            column_exists = False
        if factor_id not in existing and not column_exists:
            continue
        set_factor_materialization(
            provider,
            factor_id,
            definition_hash,
            "stale",
        )


def fail_factor_materializations(
    provider: str,
    factor_ids: Iterable[str],
    error: str,
) -> None:
    existing = list_factor_materializations(provider)
    for factor_id in factor_ids:
        record = existing.get(str(factor_id))
        if not record:
            continue
        set_factor_materialization(
            provider,
            str(factor_id),
            str(record["definition_hash"]),
            "failed",
            start_date=record.get("start_date"),
            end_date=record.get("end_date"),
            row_count=int(record.get("row_count", 0)),
            error=error[:1000],
        )


def interrupt_factor_materializations(
    provider: str,
    factor_ids: Iterable[str],
    reason: str,
) -> None:
    """Keep interrupted work retryable instead of presenting it as a formula failure."""
    existing = list_factor_materializations(provider)
    for factor_id in factor_ids:
        record = existing.get(str(factor_id))
        if not record:
            continue
        set_factor_materialization(
            provider,
            str(factor_id),
            str(record["definition_hash"]),
            "stale",
            start_date=record.get("start_date"),
            end_date=record.get("end_date"),
            row_count=int(record.get("row_count", 0)),
            error=reason[:1000],
        )
