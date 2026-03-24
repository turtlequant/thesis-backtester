"""
Analysis service — wraps run_blind_analysis with task management.

Manages concurrent analyses, captures progress events,
and stores results.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.runtime import run_blind_analysis
from src.data.snapshot import StockSnapshot
from src.engine.config import StrategyConfig

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PREPARING_DATA = "preparing_data"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ProgressEvent:
    """A single progress event from an analysis task."""
    event: str
    chapter_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class AnalysisTask:
    """Tracks the state of a single analysis run."""
    task_id: str
    ts_code: str
    strategy_name: str
    strategy_path: str
    status: TaskStatus = TaskStatus.PENDING
    progress_events: List[ProgressEvent] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    # Subscribers waiting for progress updates
    _subscribers: List[asyncio.Queue] = field(default_factory=list)

    def add_subscriber(self) -> asyncio.Queue:
        """Add a WebSocket subscriber for progress events."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        # Send all existing events to new subscriber
        for event in self.progress_events:
            queue.put_nowait(event)
        return queue

    def remove_subscriber(self, queue: asyncio.Queue):
        """Remove a WebSocket subscriber."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def _emit(self, event: ProgressEvent):
        """Emit a progress event to all subscribers."""
        self.progress_events.append(event)
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is slow


class AnalysisManager:
    """Manages concurrent analysis tasks."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.tasks: Dict[str, AnalysisTask] = {}

    def _get_settings(self) -> dict:
        """Load settings from config.json."""
        config_path = self.project_root / "desktop" / "config.json"
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
        return {}

    def _apply_llm_settings(self, settings: dict):
        """Apply LLM settings to environment variables."""
        if settings.get("llm_api_key"):
            os.environ["LLM_API_KEY"] = settings["llm_api_key"]
        if settings.get("llm_base_url"):
            os.environ["LLM_BASE_URL"] = settings["llm_base_url"]
        if settings.get("llm_model"):
            os.environ["LLM_MODEL"] = settings["llm_model"]
        if settings.get("temperature") is not None:
            os.environ["LLM_TEMPERATURE"] = str(settings["temperature"])

    def create_task(self, ts_code: str, strategy_name: str, strategy_path: str) -> AnalysisTask:
        """Create a new analysis task."""
        task_id = str(uuid.uuid4())[:8]
        task = AnalysisTask(
            task_id=task_id,
            ts_code=ts_code,
            strategy_name=strategy_name,
            strategy_path=strategy_path,
        )
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[AnalysisTask]:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    async def run_analysis(
        self,
        task: AnalysisTask,
        snapshot: StockSnapshot,
    ):
        """
        Run the analysis in the background.

        This is the core method that drives run_blind_analysis
        and captures progress via callback.
        """
        settings = self._get_settings()
        self._apply_llm_settings(settings)

        config = StrategyConfig.from_yaml(task.strategy_path)

        # Progress callback that feeds into the task's event system
        def on_progress(event: str, ch_id: str = None, data: dict = None):
            progress = ProgressEvent(event=event, chapter_id=ch_id, data=data or {})
            task._emit(progress)

        task.status = TaskStatus.RUNNING
        task._emit(ProgressEvent(event="analysis_start", data={
            "ts_code": task.ts_code,
            "strategy": task.strategy_name,
            "stock_name": snapshot.stock_name,
        }))

        try:
            # Determine output directory: live/<ts_code>_<date>/
            today = time.strftime("%Y-%m-%d")
            live_dir = Path(task.strategy_path).parent / "live"
            task_dir = live_dir / f"{task.ts_code}_{today}"
            task_dir.mkdir(parents=True, exist_ok=True)

            # Raw data already cached by data_service.create_snapshot_for_analysis()
            # Just save snapshot preview here (needs to happen after data is ready)
            from src.desktop.api.services.data_service import _get_cache_dir
            cache_dir = _get_cache_dir(task.ts_code)
            try:
                from src.data.snapshot import snapshot_to_markdown
                snap_md = snapshot_to_markdown(snapshot, blind_mode=False)
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / "snapshot_preview.md").write_text(snap_md, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to save snapshot preview: {e}")

            result = await run_blind_analysis(
                ts_code=task.ts_code,
                cutoff_date=snapshot.cutoff_date,
                config=config,
                blind_mode=False,  # Non-blind for live analysis
                output_dir=task_dir,
                on_progress=on_progress,
                snapshot=snapshot,
            )

            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()

            task._emit(ProgressEvent(event="analysis_complete", data={
                "elapsed_seconds": result.get("metadata", {}).get("elapsed_seconds", 0),
                "chapters_completed": result.get("metadata", {}).get("chapters_completed", 0),
            }))

        except Exception as e:
            logger.exception(f"Analysis failed for task {task.task_id}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            task._emit(ProgressEvent(event="error", data={"message": str(e)}))

    def get_all_reports(self) -> List[dict]:
        """
        List all saved reports from all strategies' live/ directories.
        """
        reports = []
        strategies_dir = self.project_root / "strategies"
        if not strategies_dir.exists():
            return reports

        for strategy_dir in strategies_dir.iterdir():
            if not strategy_dir.is_dir():
                continue
            live_dir = strategy_dir / "live"
            if not live_dir.exists():
                continue

            # Find all structured JSON files (both in subdirs and root)
            for json_file in sorted(live_dir.glob("**/*_structured.json"), reverse=True):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    metadata = data.get("metadata", {})
                    synthesis = data.get("synthesis", {})

                    report_md = json_file.with_name(
                        json_file.name.replace("_structured.json", "_report.md")
                    )

                    reports.append({
                        "id": f"{strategy_dir.name}__{json_file.stem}",
                        "file_path": str(json_file),
                        "report_path": str(report_md) if report_md.exists() else None,
                        "strategy": strategy_dir.name,
                        "ts_code": metadata.get("ts_code", ""),
                        "cutoff_date": metadata.get("cutoff_date", ""),
                        "model": metadata.get("model", ""),
                        "elapsed_seconds": metadata.get("elapsed_seconds", 0),
                        "score": synthesis.get("综合评分", synthesis.get("score", "")),
                        "recommendation": synthesis.get("最终建议", synthesis.get("recommendation", "")),
                        "created_at": datetime.fromtimestamp(
                            json_file.stat().st_mtime
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse report {json_file}: {e}")

        return sorted(reports, key=lambda r: r["created_at"], reverse=True)

    def get_report(self, report_id: str) -> Optional[dict]:
        """Get a specific report by ID."""
        for report in self.get_all_reports():
            if report["id"] == report_id:
                # Load full content
                json_path = Path(report["file_path"])
                data = json.loads(json_path.read_text(encoding="utf-8"))

                # Load markdown report if available
                report_text = ""
                if report.get("report_path"):
                    report_path = Path(report["report_path"])
                    if report_path.exists():
                        report_text = report_path.read_text(encoding="utf-8")

                return {
                    **report,
                    "full_data": data,
                    "report_text": report_text,
                }
        return None

    def delete_report(self, report_id: str) -> bool:
        """Delete a report by ID."""
        for report in self.get_all_reports():
            if report["id"] == report_id:
                try:
                    json_path = Path(report["file_path"])
                    if json_path.exists():
                        json_path.unlink()
                    if report.get("report_path"):
                        report_path = Path(report["report_path"])
                        if report_path.exists():
                            report_path.unlink()
                    return True
                except Exception as e:
                    logger.error(f"Failed to delete report {report_id}: {e}")
                    return False
        return False
