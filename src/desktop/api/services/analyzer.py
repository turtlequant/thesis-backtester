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
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def __init__(self, project_root: Path, config_path: Optional[Path] = None):
        self.project_root = project_root
        self.config_path = config_path
        self.tasks: Dict[str, AnalysisTask] = {}

    def _get_settings(self) -> dict:
        """Load settings from config.json."""
        config_path = self.config_path
        if config_path is None:
            from src.desktop.runtime import DESKTOP_CONFIG_PATH

            config_path = DESKTOP_CONFIG_PATH
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
        if settings.get("max_tokens") is not None:
            os.environ["LLM_MAX_TOKENS"] = str(settings["max_tokens"])

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

            # Agent/OpenAI dependencies are only needed after the user starts an
            # analysis. Keeping this import off the desktop startup path avoids
            # paying their import cost before the first window is visible.
            from src.agent.runtime import run_blind_analysis

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
        """List indexed reports while reconciling new or changed artifacts."""
        from src.desktop.api.services import report_index

        return report_index.list_reports(self.project_root)

    def get_reports_page(self, **params) -> dict:
        """Query one filtered report-index page without loading report bodies."""
        from src.desktop.api.services import report_index

        return report_index.search_reports(self.project_root, **params)

    def get_report(self, report_id: str) -> Optional[dict]:
        """Load one indexed report and its readable/evidence artifacts."""
        from src.desktop.api.services import report_index

        return report_index.get_report(report_id, self.project_root)

    def delete_report(self, report_id: str) -> bool:
        """Delete the two report artifacts and remove their index row."""
        from src.desktop.api.services import report_index

        return report_index.delete_report(report_id, self.project_root)
