"""Provider-scoped reusable cache for adjusted forward outcomes."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Mapping

from src.data.settings import DATA_ROOT


CACHE_DB_PATH = DATA_ROOT / "outcomes_cache" / "forward_outcomes.db"


def _connect() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CACHE_DB_PATH, timeout=30.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forward_outcomes (
            provider TEXT NOT NULL,
            cutoff_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (provider, cutoff_date, ts_code)
        )
        """
    )
    return connection


def load_cutoff(provider: str, cutoff_date: str) -> Dict[str, dict]:
    if not CACHE_DB_PATH.exists():
        return {}
    connection = _connect()
    try:
        rows = connection.execute(
            """
            SELECT ts_code, payload
            FROM forward_outcomes
            WHERE provider = ? AND cutoff_date = ?
            """,
            (str(provider), str(cutoff_date)),
        ).fetchall()
    finally:
        connection.close()
    results: Dict[str, dict] = {}
    for ts_code, payload in rows:
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            results[str(ts_code)] = value
    return results


def save_cutoff(
    provider: str,
    cutoff_date: str,
    payloads: Mapping[str, dict],
) -> None:
    rows = [
        (
            str(provider),
            str(cutoff_date),
            str(ts_code),
            json.dumps(payload, ensure_ascii=False, default=str),
            datetime.now().isoformat(timespec="seconds"),
        )
        for ts_code, payload in payloads.items()
        if isinstance(payload, dict)
    ]
    if not rows:
        return
    connection = _connect()
    try:
        connection.executemany(
            """
            INSERT INTO forward_outcomes
                (provider, cutoff_date, ts_code, payload, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, cutoff_date, ts_code) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()
