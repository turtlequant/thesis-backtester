"""Background jobs for deterministic desktop research workflows.

The desktop UI should not shell out to the CLI.  This module reuses the same
screening and evaluation functions directly, gives each run an isolated output
directory, and exposes a small observable job record to the API.
"""
from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.data.settings import DATA_ROOT

from . import screening_strategies


RESEARCH_RUNS_ROOT = DATA_ROOT / "research_runs"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ResearchJobManager:
    """Run one deterministic research task at a time and persist its result."""

    def __init__(self, root: Path = RESEARCH_RUNS_ROOT):
        self.root = Path(root)
        self._jobs: Dict[str, Dict[str, object]] = {}
        self._lock = threading.RLock()
        self._active_id: Optional[str] = None

    def start_cross_section(self, params: Dict[str, object]) -> Dict[str, object]:
        with self._lock:
            if self._active_id:
                active = self._jobs.get(self._active_id)
                if active and active.get("status") in {"queued", "running"}:
                    raise ValueError("已有研究任务正在运行")
        job_id = uuid.uuid4().hex[:16]
        job: Dict[str, object] = {
            "id": job_id,
            "kind": "cross_section",
            "status": "queued",
            "stage": "queued",
            "message": "等待执行",
            "params": dict(params),
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "result": None,
            "progress": {
                "phase": "queued",
                "message": "等待执行",
                "current": 0,
                "total": 0,
                "percent": 0,
                "overall_percent": 0,
            },
        }
        with self._lock:
            self._jobs[job_id] = job
            self._active_id = job_id
            self._persist(job)
        threading.Thread(
            target=self._run_cross_section,
            args=(job_id,),
            name=f"research-run-{job_id[:6]}",
            daemon=True,
        ).start()
        return self.get_job(job_id)

    def _run_cross_section(self, job_id: str) -> None:
        try:
            self._update(
                job_id,
                status="running",
                stage="screening",
                message="正在生成历史截面并执行选股",
                started_at=_now(),
                progress={
                    "phase": "screening",
                    "message": "正在准备历史截面",
                    "current": 0,
                    "total": 0,
                    "percent": 0,
                    "overall_percent": 0,
                },
            )
            job = self.get_job(job_id)
            params = dict(job["params"])
            run_dir = (self.root / job_id).resolve()
            strategy = dict(params["screening_strategy_snapshot"])
            config = screening_strategies.build_config(
                strategy,
                start_date=str(params["start_date"]),
                end_date=str(params["end_date"]),
                interval=str(params["interval"]),
                top_n=int(params["top_n"]),
                run_dir=run_dir,
            )

            from src.backtest.pipeline import step_eval, step_screen

            dates = step_screen(
                config,
                progress=self._progress_callback(
                    job_id,
                    stage="screening",
                    base_percent=0,
                    span_percent=35,
                ),
            )
            self._update(
                job_id,
                stage="evaluation",
                message="正在采集后复权前向收益并与市场基准比较",
                progress={
                    "phase": "loading",
                    "message": "正在准备收益评估",
                    "current": 0,
                    "total": len(dates),
                    "percent": 0,
                    "overall_percent": 35,
                },
            )
            report_path = step_eval(
                config,
                numeric_only=True,
                progress=self._progress_callback(
                    job_id,
                    stage="evaluation",
                    base_percent=35,
                    span_percent=65,
                ),
            )

            summaries = sorted(run_dir.glob("backtest_summary_*.json"))
            if not summaries:
                raise RuntimeError("回测完成，但没有生成结构化结果")
            summary_path = summaries[-1]
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            performance = summary.get("performance", {})
            selected_performance = {
                key: {
                    "label": performance.get(key, {}).get("label", key),
                    "desc": performance.get(key, {}).get("desc", ""),
                    "stats": performance.get(key, {}).get("stats", {}),
                    "slices": performance.get(key, {}).get("slices", []),
                }
                for key in ("market", "screen_all", "screen_top")
                if key in performance
            }
            result = {
                "outcome_schema_version": summary.get("outcome_schema_version", 1),
                "evaluation_semantics": summary.get("evaluation_semantics", "legacy"),
                "strategy": summary.get("strategy", config.name),
                "screening_strategy_id": strategy["id"],
                "screening_strategy_name": strategy["name"],
                "screening_strategy_snapshot": strategy,
                "version": summary.get("version", config.version),
                "dates": summary.get("dates", dates),
                "interval": summary.get("interval", params["interval"]),
                "slices": [
                    {
                        "cutoff_date": item.get("cutoff_date"),
                        "screen_count": item.get("screen_count", 0),
                    }
                    for item in summary.get("slices", [])
                ],
                "performance": selected_performance,
                "report_path": str(report_path),
                "summary_path": str(summary_path),
            }
            self._update(
                job_id,
                status="completed",
                stage="completed",
                message="截面回测完成",
                result=result,
                finished_at=_now(),
                progress={
                    "phase": "completed",
                    "message": "历史验证结果已生成",
                    "current": len(dates),
                    "total": len(dates),
                    "percent": 100,
                    "overall_percent": 100,
                },
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="failed",
                message="截面回测失败",
                error=str(exc)[:2000],
                finished_at=_now(),
            )
        finally:
            with self._lock:
                if self._active_id == job_id:
                    self._active_id = None

    def _progress_callback(
        self,
        job_id: str,
        *,
        stage: str,
        base_percent: float,
        span_percent: float,
    ) -> Callable[[Dict[str, object]], None]:
        """Map one pipeline phase's real counters onto the persisted workflow."""

        def update(payload: Dict[str, object]) -> None:
            detail = dict(payload)
            local_percent = max(0.0, min(100.0, float(detail.get("percent", 0))))
            detail["percent"] = round(local_percent, 1)
            detail["overall_percent"] = round(
                base_percent + local_percent * span_percent / 100,
                1,
            )
            self._update(
                job_id,
                stage=stage,
                message=str(detail.get("message") or "正在执行"),
                progress=detail,
            )

        return update

    def _persist(self, job: Dict[str, object]) -> None:
        run_dir = self.root / str(job["id"])
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "run.json"
        temporary = run_dir / "run.json.tmp"
        temporary.write_text(
            json.dumps(job, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(target)

    def _update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            self._persist(job)

    def get_job(self, job_id: str) -> Dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return copy.deepcopy(job)

        path = self.root / job_id / "run.json"
        if not path.exists():
            raise KeyError(job_id)
        job = json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            self._jobs[job_id] = job
        return copy.deepcopy(job)

    def list_jobs(self, kind: str = "cross_section", limit: int = 20) -> List[Dict[str, object]]:
        jobs: Dict[str, Dict[str, object]] = {}
        if self.root.exists():
            paths = sorted(
                self.root.glob("*/run.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in paths[: max(limit * 2, 20)]:
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    if (
                        item.get("status") in {"queued", "running"}
                        and str(item.get("id")) not in self._jobs
                    ):
                        item.update(
                            status="interrupted",
                            stage="interrupted",
                            message="应用上次退出时任务仍在运行",
                            finished_at=item.get("finished_at") or _now(),
                        )
                        self._persist(item)
                    jobs[str(item["id"])] = item
                except (OSError, ValueError, KeyError):
                    continue
        with self._lock:
            for item in self._jobs.values():
                jobs[str(item["id"])] = copy.deepcopy(item)
        selected = [item for item in jobs.values() if item.get("kind") == kind]
        selected.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return selected[: max(1, min(limit, 100))]

    def shutdown(self) -> None:
        # Research workers are daemon threads so closing the desktop app is
        # never blocked by a long historical evaluation.
        return None


research_job_manager = ResearchJobManager()
