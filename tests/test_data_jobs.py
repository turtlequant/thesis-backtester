import time
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.data import jobs


class _FakeUpdater:
    def __init__(self, provider_name, progress=None, cancel_event=None):
        self.provider_name = provider_name
        self.progress = progress

    def init_basic(self):
        self.progress(
            {
                "stage": "stock_list",
                "message": "基础数据完成",
                "current": 1,
                "total": 1,
                "percent": 100,
            }
        )
        return True

    def close(self):
        pass

    def daily_update(self, include_financials=False):
        return True


def test_interpreter_shutdown_factor_failure_is_retryable():
    assert jobs._is_retryable_factor_failure(
        {
            "status": "failed",
            "error": "cannot schedule new futures after interpreter shutdown",
        }
    )
    assert not jobs._is_retryable_factor_failure(
        {"status": "failed", "error": "完整指标区间未产生任何非空结果"}
    )


def test_closed_job_manager_rejects_new_work_without_creating_a_job(tmp_path):
    manager = jobs.DataJobManager(tmp_path / "control.db")
    manager.shutdown()

    with pytest.raises(jobs.JobManagerClosed):
        manager.start_job("tushare", "factors", codes=["roe_avg_3y"])

    assert manager.list_jobs() == []


def test_reconcile_requeues_only_transient_factor_failures(tmp_path, monkeypatch):
    from src.data import factor_materialization
    from src.engine import factor_catalog

    transient = {
        "status": "failed",
        "error": "cannot schedule new futures after interpreter shutdown",
        "usable": False,
        "start_date": None,
        "latest_date": "2026-08-17",
        "row_count": 0,
    }
    permanent = {
        **transient,
        "error": "完整指标区间未产生任何非空结果",
    }

    class Catalog:
        def __init__(self, provider):
            self.snapshot = SimpleNamespace(
                datasets={"daily/indicator": {"latest_date": "2026-08-17"}}
            )

        def list_assets(self):
            def asset(factor_id, materialization):
                return {
                    "id": factor_id,
                    "asset_kind": "derived",
                    "engine": "polars",
                    "editable": True,
                    "provider": {"compatibility": "exact"},
                    "materialization_blockers": [],
                    "definition_hash": f"hash-{factor_id}",
                    "materialization": materialization,
                }

            return [
                asset("retry_me", transient),
                asset("leave_failed", permanent),
            ]

    states = []
    queued = []
    monkeypatch.setattr(factor_catalog, "FactorCatalog", Catalog)
    monkeypatch.setattr(
        factor_materialization,
        "set_factor_materialization",
        lambda provider, factor_id, definition_hash, status, **kwargs: states.append(
            (factor_id, status)
        ),
    )
    manager = jobs.DataJobManager(tmp_path / "control.db")
    monkeypatch.setattr(
        manager,
        "start_job",
        lambda provider, job_type, **kwargs: queued.append(
            (provider, job_type, kwargs)
        )
        or {"status": "queued"},
    )
    try:
        manager.reconcile_factor_definitions("tushare")
    finally:
        manager.shutdown()

    assert states == [("retry_me", "pending")]
    assert queued[0][2]["codes"] == ["retry_me"]


def test_shutdown_cancels_and_waits_for_running_factor_job(tmp_path, monkeypatch):
    from src.data import factor_store

    entered = threading.Event()

    def keep_running(factor_ids, *, progress, **kwargs):
        entered.set()
        while True:
            progress(
                {
                    "stage": "factors",
                    "message": "计算中",
                    "current": 1,
                    "total": 2,
                    "percent": 50,
                }
            )
            time.sleep(0.005)

    monkeypatch.setattr(
        jobs,
        "load_data_config",
        lambda: {"provider": "baostock", "auto_update_financials": False},
    )
    monkeypatch.setattr(factor_store, "materialize_factor_definitions", keep_running)
    manager = jobs.DataJobManager(tmp_path / "control.db")
    created = manager.start_job("baostock", "factors", codes=["ep"])
    assert entered.wait(1)

    manager.shutdown(wait=True)

    assert manager.get_job(created["id"])["status"] == "cancelled"


def test_background_job_persists_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DataUpdater", _FakeUpdater)
    monkeypatch.setattr(
        jobs,
        "load_data_config",
        lambda: {"provider": "baostock", "auto_update_financials": False},
    )
    manager = jobs.DataJobManager(tmp_path / "control.db")
    try:
        created = manager.start_job("baostock", "basic")
        deadline = time.time() + 3
        current = created
        while current["status"] in {"queued", "running"} and time.time() < deadline:
            time.sleep(0.01)
            current = manager.get_job(created["id"])

        assert current["status"] == "completed"
        assert current["percent"] == 100
        assert current["stage"] == "stock_list"
        assert manager.list_jobs()[0]["id"] == created["id"]
    finally:
        manager.shutdown()


def test_incremental_job_marks_scheduler_only_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DataUpdater", _FakeUpdater)
    monkeypatch.setattr(
        jobs,
        "load_data_config",
        lambda: {"provider": "baostock", "auto_update_financials": False},
    )
    manager = jobs.DataJobManager(tmp_path / "control.db")
    try:
        created = manager.start_job("baostock", "incremental")
        deadline = time.time() + 3
        current = created
        while current["status"] in {"queued", "running"} and time.time() < deadline:
            time.sleep(0.01)
            current = manager.get_job(created["id"])

        assert current["status"] == "completed"
        assert manager.get_scheduler_value("auto_update_last_run:baostock") == (
            datetime.now().strftime("%Y-%m-%d")
        )
    finally:
        manager.shutdown()


def test_incremental_job_links_automatic_factor_follow_up(tmp_path, monkeypatch):
    from src.data import factor_materialization, factor_store
    from src.engine import factor_catalog

    class Catalog:
        def __init__(self, provider):
            self.snapshot = SimpleNamespace(
                datasets={"daily/indicator": {"latest_date": "2026-08-18"}}
            )

        def list_assets(self):
            return [
                {
                    "id": "roe_avg_3y",
                    "asset_kind": "derived",
                    "engine": "polars",
                    "editable": True,
                    "provider": {"compatibility": "exact"},
                    "materialization_blockers": [],
                    "definition_hash": "hash-roe",
                    "materialization": {
                        "status": "not_materialized",
                        "usable": False,
                        "start_date": None,
                        "latest_date": None,
                        "row_count": 0,
                        "error": None,
                    },
                }
            ]

    monkeypatch.setattr(jobs, "DataUpdater", _FakeUpdater)
    monkeypatch.setattr(
        jobs,
        "load_data_config",
        lambda: {"provider": "baostock", "auto_update_financials": False},
    )
    monkeypatch.setattr(factor_catalog, "FactorCatalog", Catalog)
    monkeypatch.setattr(
        factor_materialization,
        "set_factor_materialization",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        factor_store,
        "materialize_factor_definitions",
        lambda factor_ids, **kwargs: True,
    )

    manager = jobs.DataJobManager(tmp_path / "control.db")
    try:
        parent = manager.start_job("baostock", "incremental")
        deadline = time.time() + 3
        current_jobs = manager.list_jobs()
        while (
            any(job["status"] in {"queued", "running"} for job in current_jobs)
            and time.time() < deadline
        ):
            time.sleep(0.01)
            current_jobs = manager.list_jobs()

        follow_up = next(job for job in current_jobs if job["job_type"] == "factors")
        completed_parent = manager.get_job(parent["id"])
        assert follow_up["parent_job_id"] == parent["id"]
        assert follow_up["codes"] == ["roe_avg_3y"]
        assert follow_up["status"] == "completed"
        assert "正在同步 1 个因子" in completed_parent["message"]
        assert follow_up["message"] == "因子同步完成（1 个）"
        assert manager.get_scheduler_value("auto_update_last_run:baostock") == (
            datetime.now().strftime("%Y-%m-%d")
        )
    finally:
        manager.shutdown()


def test_factor_job_uses_local_definition_materializer(tmp_path, monkeypatch):
    from src.data import factor_store

    calls = []
    monkeypatch.setattr(
        jobs,
        "load_data_config",
        lambda: {"provider": "baostock", "auto_update_financials": False},
    )
    monkeypatch.setattr(
        factor_store,
        "materialize_factor_definitions",
        lambda factor_ids, **kwargs: calls.append((factor_ids, kwargs)) or True,
    )
    manager = jobs.DataJobManager(tmp_path / "control.db")
    try:
        created = manager.start_job("baostock", "factors", codes=["ep"])
        deadline = time.time() + 3
        current = created
        while current["status"] in {"queued", "running"} and time.time() < deadline:
            time.sleep(0.01)
            current = manager.get_job(created["id"])

        assert current["status"] == "completed"
        assert calls[0][0] == ["ep"]
        assert calls[0][1]["provider"] == "baostock"
    finally:
        manager.shutdown()


def test_interrupted_incremental_job_clears_premature_scheduler_mark(tmp_path):
    path = tmp_path / "control.db"
    manager = jobs.DataJobManager(path)
    try:
        manager.set_scheduler_value("auto_update_last_run:baostock", "2024-01-02")
        manager.set_scheduler_value("auto_update_last_attempt:baostock", "2024-01-02 18:30:00")
        with manager._connect() as connection:
            connection.execute(
                """
                INSERT INTO data_jobs
                    (id, provider, job_type, status, codes_json, created_at)
                VALUES ('interrupted-job', 'baostock', 'incremental', 'running', '[]', ?)
                """,
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
            )
    finally:
        manager.shutdown()

    resumed = jobs.DataJobManager(path)
    try:
        assert resumed.get_job("interrupted-job")["status"] == "interrupted"
        assert resumed.get_scheduler_value("auto_update_last_run:baostock") is None
        assert resumed.get_scheduler_value("auto_update_last_attempt:baostock") is None
    finally:
        resumed.shutdown()
