"""Persistent background download jobs and lightweight automatic scheduling."""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .config import SUPPORTED_PROVIDERS, load_data_config
from .provider import clear_provider_cache, get_provider_capabilities
from .settings import DATA_ROOT
from .updater import DataUpdater, UpdateCancelled

CONTROL_DB_PATH = DATA_ROOT / "control.db"

_RETRYABLE_FACTOR_FAILURE_MARKERS = (
    "interpreter shutdown",
    "应用退出",
    "任务已取消",
    "计算中断",
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_retryable_factor_failure(materialization: Dict[str, object]) -> bool:
    if materialization.get("status") != "failed":
        return False
    error = str(materialization.get("error") or "").lower()
    return any(marker.lower() in error for marker in _RETRYABLE_FACTOR_FAILURE_MARKERS)


class JobManagerClosed(RuntimeError):
    """Raised when new work is submitted while the application is closing."""


class DataJobManager:
    """Run one provider download at a time and persist observable progress."""

    def __init__(self, path: Path = CONTROL_DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="data-update")
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._closing = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_jobs (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    parent_job_id TEXT,
                    status TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    codes_json TEXT NOT NULL DEFAULT '[]',
                    stage TEXT,
                    message TEXT,
                    current INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    percent REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(data_jobs)").fetchall()
            }
            if "parent_job_id" not in columns:
                connection.execute("ALTER TABLE data_jobs ADD COLUMN parent_job_id TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_jobs_parent ON data_jobs(parent_job_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            interrupted_incremental = connection.execute(
                "SELECT DISTINCT provider FROM data_jobs "
                "WHERE job_type='incremental' AND status IN ('queued', 'running')"
            ).fetchall()
            interrupted_factors = connection.execute(
                "SELECT provider, codes_json FROM data_jobs "
                "WHERE job_type='factors' AND status IN ('queued', 'running')"
            ).fetchall()
            connection.execute(
                "UPDATE data_jobs SET status='interrupted', finished_at=?, "
                "message='应用上次退出时任务仍在运行' WHERE status IN ('queued', 'running')",
                (_now(),),
            )
            for row in interrupted_incremental:
                for prefix in ("auto_update_last_run", "auto_update_last_attempt"):
                    connection.execute(
                        "DELETE FROM scheduler_state WHERE key=?",
                        (f"{prefix}:{row[0]}",),
                    )
        if interrupted_factors:
            from .factor_materialization import interrupt_factor_materializations

            for provider, codes_json in interrupted_factors:
                interrupt_factor_materializations(
                    str(provider),
                    json.loads(codes_json or "[]"),
                    "应用退出导致因子计算中断",
                )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, object]:
        result = dict(row)
        result["codes"] = json.loads(result.pop("codes_json") or "[]")
        return result

    def start_job(
        self,
        provider: str,
        job_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        codes: Optional[List[str]] = None,
        parent_job_id: Optional[str] = None,
    ) -> Dict[str, object]:
        with self._lock:
            if self._closing:
                raise JobManagerClosed("后台任务调度器正在关闭，请重新启动应用后再试")
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的数据源: {provider}")
        selected = str(load_data_config()["provider"])
        if provider != selected:
            raise ValueError(f"请先将当前数据口径切换为 {provider}，再创建下载任务")
        allowed_job_types = {"basic", "market", "financials", "full", "incremental", "factors"}
        if job_type not in allowed_job_types:
            raise ValueError(f"不支持的任务类型: {job_type}")
        if parent_job_id:
            if job_type != "factors":
                raise ValueError("只有自动因子同步任务可以关联上游任务")
            try:
                parent_job = self.get_job(parent_job_id)
            except KeyError as exc:
                raise ValueError("上游数据任务不存在") from exc
            if parent_job["provider"] != provider:
                raise ValueError("因子同步任务与上游任务的数据源不一致")
        if job_type != "factors" and self.has_active_job(provider):
            raise ValueError(f"{provider} 已有下载任务正在排队或运行")
        capabilities = get_provider_capabilities(provider)
        if job_type != "factors" and not capabilities.supports_download:
            raise ValueError(f"{capabilities.label} 是即时分析源，不支持本地历史下载")
        if job_type == "factors" and not capabilities.supports_history:
            raise ValueError(f"{capabilities.label} 不支持历史因子物化")
        for value in (start_date, end_date):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("下载日期必须为 YYYY-MM-DD") from exc
        if start_date and end_date and start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if job_type == "factors":
            normalized_codes = [str(code).strip() for code in (codes or [])]
            invalid_codes = [
                code for code in normalized_codes if not re.fullmatch(r"[a-z][a-z0-9_]*", code)
            ]
            if not normalized_codes:
                raise ValueError("因子计算任务至少需要一个因子 ID")
            if invalid_codes:
                raise ValueError(f"因子 ID 无效: {invalid_codes[0]}")
        else:
            normalized_codes = [str(code).strip().upper() for code in (codes or [])]
            invalid_codes = [
                code
                for code in normalized_codes
                if not re.fullmatch(r"\d{6}\.(SH|SZ)", code)
            ]
            if invalid_codes:
                raise ValueError(f"股票代码格式错误: {invalid_codes[0]}（应为 601288.SH）")

        job_id = uuid.uuid4().hex[:16]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO data_jobs
                    (id, provider, job_type, parent_job_id, status, start_date, end_date,
                     codes_json, message, created_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, '等待执行', ?)
                """,
                (
                    job_id,
                    provider,
                    job_type,
                    parent_job_id,
                    start_date,
                    end_date,
                    json.dumps(normalized_codes),
                    _now(),
                ),
            )
        event = threading.Event()
        with self._lock:
            if self._closing:
                self._update(
                    job_id,
                    status="interrupted",
                    message="应用正在退出，任务未启动",
                    finished_at=_now(),
                )
                raise JobManagerClosed("后台任务调度器正在关闭，请重新启动应用后再试")
            self._cancel_events[job_id] = event
            try:
                self._executor.submit(self._run_job, job_id, event)
            except RuntimeError as exc:
                self._cancel_events.pop(job_id, None)
                self._update(
                    job_id,
                    status="interrupted",
                    message="应用正在退出，任务未启动",
                    finished_at=_now(),
                    error=None,
                )
                raise JobManagerClosed(
                    "后台任务调度器正在关闭，请重新启动应用后再试"
                ) from exc
        return self.get_job(job_id)

    def reconcile_factor_definitions(
        self,
        provider: Optional[str] = None,
        parent_job_id: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        """Queue DSL definitions that are new, stale, or behind daily history."""
        from .config import get_active_provider_name
        from .factor_materialization import set_factor_materialization
        from src.engine.factor_catalog import FactorCatalog

        with self._lock:
            if self._closing:
                return None
        selected_provider = (provider or get_active_provider_name()).lower()
        catalog = FactorCatalog(provider=selected_provider)
        active_factor_ids = {
            factor_id
            for job in self.list_jobs(limit=200)
            if job.get("job_type") == "factors"
            and job.get("status") in {"queued", "running"}
            for factor_id in job.get("codes", [])
        }
        indicator_latest = catalog.snapshot.datasets.get("daily/indicator", {}).get(
            "latest_date"
        )
        candidates = []
        for asset in catalog.list_assets():
            materialization = asset["materialization"]
            missing_coverage = bool(
                materialization.get("usable")
                and indicator_latest
                and (
                    not materialization.get("latest_date")
                    or materialization["latest_date"] < indicator_latest
                )
            )
            if (
                asset["asset_kind"] == "derived"
                and asset["engine"] == "polars"
                and asset["editable"]
                and asset["provider"]["compatibility"] == "exact"
                and not asset.get("materialization_blockers")
                and (
                    materialization["status"] in {"not_materialized", "stale"}
                    or _is_retryable_factor_failure(materialization)
                    or missing_coverage
                )
                and asset["id"] not in active_factor_ids
            ):
                candidates.append(asset)
        if not candidates:
            return None

        new_or_stale = any(
            asset["materialization"]["status"] in {"not_materialized", "stale"}
            or _is_retryable_factor_failure(asset["materialization"])
            for asset in candidates
        )
        start_date = None
        if not new_or_stale:
            previous_ends = [
                asset["materialization"].get("latest_date") for asset in candidates
            ]
            previous_ends = [value for value in previous_ends if value]
            if previous_ends:
                start_date = (date.fromisoformat(min(previous_ends)) + timedelta(days=1)).isoformat()

        for asset in candidates:
            set_factor_materialization(
                selected_provider,
                asset["id"],
                asset["definition_hash"],
                "pending",
                start_date=asset["materialization"].get("start_date"),
                end_date=asset["materialization"].get("latest_date"),
                row_count=int(asset["materialization"].get("row_count", 0)),
            )
        try:
            return self.start_job(
                selected_provider,
                "factors",
                start_date=start_date,
                codes=[asset["id"] for asset in candidates],
                parent_job_id=parent_job_id,
            )
        except JobManagerClosed:
            for asset in candidates:
                previous = asset["materialization"]
                restore_status = (
                    "ready"
                    if previous.get("status") in {"ready", "ready_unverified"}
                    else "stale"
                )
                set_factor_materialization(
                    selected_provider,
                    asset["id"],
                    asset["definition_hash"],
                    restore_status,
                    start_date=previous.get("start_date"),
                    end_date=previous.get("latest_date"),
                    row_count=int(previous.get("row_count", 0)),
                )
            return None
        except ValueError as exc:
            for asset in candidates:
                set_factor_materialization(
                    selected_provider,
                    asset["id"],
                    asset["definition_hash"],
                    "failed",
                    start_date=asset["materialization"].get("start_date"),
                    end_date=asset["materialization"].get("latest_date"),
                    row_count=int(asset["materialization"].get("row_count", 0)),
                    error=str(exc),
                )
            return None

    def _update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE data_jobs SET {assignments} WHERE id=?",
                [*fields.values(), job_id],
            )

    def _run_job(self, job_id: str, cancel_event: threading.Event) -> None:
        job = self.get_job(job_id)
        self._update(job_id, status="running", started_at=_now(), message="任务已开始")

        def progress(payload: Dict[str, object]) -> None:
            if cancel_event.is_set():
                raise UpdateCancelled("因子计算任务已取消")
            self._update(
                job_id,
                stage=payload.get("stage"),
                message=payload.get("message"),
                current=int(payload.get("current", 0)),
                total=int(payload.get("total", 0)),
                percent=float(payload.get("percent", 0)),
            )

        updater = None
        try:
            codes = list(job.get("codes") or [])
            start_date = job.get("start_date")
            end_date = job.get("end_date")
            job_type = job["job_type"]

            if job_type == "factors":
                from .factor_store import materialize_factor_definitions

                if not materialize_factor_definitions(
                    codes,
                    provider=str(job["provider"]),
                    start_date=start_date,
                    end_date=end_date,
                    progress=progress,
                ):
                    raise RuntimeError("因子物化失败")
            else:
                updater = DataUpdater(
                    str(job["provider"]), progress=progress, cancel_event=cancel_event
                )

            if job_type == "basic":
                if not updater.init_basic():
                    raise RuntimeError("基础数据初始化失败")
            elif job_type == "market":
                if not updater.update_stock_list() or not updater.update_trade_calendar():
                    raise RuntimeError("股票列表或交易日历更新失败")
                if not updater.update_daily(start_date, end_date, codes):
                    raise RuntimeError("指定范围未下载到行情数据")
                if not updater.update_daily_indicator(start_date, end_date):
                    raise RuntimeError("每日指标下载失败")
            elif job_type == "financials":
                if not updater.update_stock_list():
                    raise RuntimeError("股票列表更新失败")
                if codes or updater.provider_name == "baostock":
                    if not updater.update_financials(codes or None, skip_existing=False):
                        raise RuntimeError("部分股票财务数据下载失败")
                else:
                    if not updater.update_financials_by_period(start_date):
                        raise RuntimeError("财务报告期截面下载失败")
                    if not updater.update_disclosure_date():
                        raise RuntimeError("财报披露日期下载失败")
                    if not updater.update_dividends(skip_existing=True):
                        raise RuntimeError("分红历史基线下载失败")
            elif job_type == "full":
                if not updater.init_basic():
                    raise RuntimeError("基础数据初始化失败")
                if not updater.update_daily(start_date, end_date, codes):
                    raise RuntimeError("指定范围未下载到行情数据")
                if not updater.update_daily_indicator(start_date, end_date):
                    raise RuntimeError("每日指标下载失败")
                if codes or updater.provider_name == "baostock":
                    if not updater.update_financials(codes or None):
                        raise RuntimeError("部分股票财务数据下载失败")
                else:
                    if not updater.update_financials_by_period(start_date):
                        raise RuntimeError("财务报告期截面下载失败")
                    if not updater.update_disclosure_date():
                        raise RuntimeError("财报披露日期下载失败")
                    if not updater.update_dividends(skip_existing=True):
                        raise RuntimeError("分红历史基线下载失败")
                if not updater.update_factors(start_date, end_date):
                    raise RuntimeError("截面因子计算失败")
                if codes and not updater.update_ts_factors(codes):
                    raise RuntimeError("时序因子计算失败")
            elif job_type == "incremental":
                include_financials = bool(load_data_config().get("auto_update_financials", True))
                if not updater.daily_update(include_financials=include_financials):
                    raise RuntimeError("增量更新未完整完成")

            if job_type in {"financials", "full"}:
                from .factor_materialization import set_factor_materialization
                from src.engine.factor_catalog import FactorCatalog

                catalog = FactorCatalog(provider=str(job["provider"]))
                for asset in catalog.list_assets():
                    if (
                        asset.get("execution_mode") == "point_in_time"
                        and asset["engine"] == "polars"
                        and asset["materialization"].get("usable")
                    ):
                        materialization = asset["materialization"]
                        set_factor_materialization(
                            str(job["provider"]),
                            asset["id"],
                            asset["definition_hash"],
                            "stale",
                            start_date=materialization.get("start_date"),
                            end_date=materialization.get("latest_date"),
                            row_count=int(materialization.get("row_count", 0)),
                        )
            follow_up = None
            if job_type != "factors":
                follow_up = self.reconcile_factor_definitions(
                    str(job["provider"]),
                    parent_job_id=job_id,
                )
            if job_type == "incremental" and not follow_up:
                self.set_scheduler_value(
                    f"auto_update_last_run:{job['provider']}",
                    datetime.now().strftime("%Y-%m-%d"),
                )
            elif job_type == "factors" and job.get("parent_job_id"):
                parent_job = self.get_job(str(job["parent_job_id"]))
                if parent_job.get("job_type") == "incremental":
                    self.set_scheduler_value(
                        f"auto_update_last_run:{job['provider']}",
                        datetime.now().strftime("%Y-%m-%d"),
                    )
            if job_type == "factors":
                completion_message = f"因子同步完成（{len(codes)} 个）"
            elif follow_up:
                completion_message = (
                    f"基础数据已完成，正在同步 {len(follow_up.get('codes') or [])} 个因子"
                )
            else:
                completion_message = "任务完成"
            self._update(
                job_id,
                status="completed",
                percent=100,
                message=completion_message,
                finished_at=_now(),
            )
        except UpdateCancelled as exc:
            if job.get("job_type") == "factors":
                from .factor_materialization import interrupt_factor_materializations

                interrupt_factor_materializations(
                    str(job["provider"]), job.get("codes") or [], str(exc)
                )
            self._update(job_id, status="cancelled", message=str(exc), finished_at=_now())
        except Exception as exc:
            if job.get("job_type") != "factors":
                clear_provider_cache(str(job["provider"]))
            else:
                from .factor_materialization import fail_factor_materializations

                fail_factor_materializations(
                    str(job["provider"]), job.get("codes") or [], str(exc)
                )
            self._update(
                job_id,
                status="failed",
                message="任务失败",
                error=str(exc)[:1000],
                finished_at=_now(),
            )
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)

    def get_job(self, job_id: str) -> Dict[str, object]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM data_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._row_to_dict(row)

    def list_jobs(self, limit: int = 30) -> List[Dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM data_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def cancel_job(self, job_id: str) -> Dict[str, object]:
        job = self.get_job(job_id)
        if job["status"] not in {"queued", "running"}:
            return job
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event:
                event.set()
        self._update(job_id, message="正在取消")
        return self.get_job(job_id)

    def has_active_job(self, provider: Optional[str] = None) -> bool:
        query = "SELECT COUNT(*) FROM data_jobs WHERE status IN ('queued', 'running')"
        params: tuple = ()
        if provider:
            query += " AND provider=?"
            params = (provider,)
        with self._connect() as connection:
            return connection.execute(query, params).fetchone()[0] > 0

    def cancel_all(self) -> None:
        for job in self.list_jobs(limit=200):
            if job["status"] in {"queued", "running"}:
                self.cancel_job(str(job["id"]))

    def get_scheduler_value(self, key: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM scheduler_state WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def set_scheduler_value(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO scheduler_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=wait, cancel_futures=False)


job_manager = DataJobManager()


async def auto_update_loop() -> None:
    """Check persisted automatic-update settings without an extra dependency."""
    while True:
        try:
            config = load_data_config()
            if config.get("auto_update_enabled"):
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                scheduled = str(config.get("auto_update_time", "18:30"))
                provider = str(config.get("provider", "baostock"))
                if not get_provider_capabilities(provider).supports_download:
                    await asyncio.sleep(30)
                    continue
                key = f"auto_update_last_run:{provider}"
                attempt_key = f"auto_update_last_attempt:{provider}"
                last_attempt = job_manager.get_scheduler_value(attempt_key)
                retry_due = True
                if last_attempt:
                    try:
                        retry_due = now - datetime.fromisoformat(last_attempt) >= timedelta(minutes=15)
                    except ValueError:
                        retry_due = True
                if (
                    now.strftime("%H:%M") >= scheduled
                    and job_manager.get_scheduler_value(key) != today
                    and retry_due
                ):
                    if not job_manager.has_active_job(provider):
                        job_manager.set_scheduler_value(attempt_key, now.isoformat(timespec="seconds"))
                        job_manager.start_job(provider, "incremental")
        except Exception:
            # The scheduler must never take down the desktop API.
            pass
        await asyncio.sleep(30)
