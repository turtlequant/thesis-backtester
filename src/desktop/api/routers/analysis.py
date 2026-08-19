"""
Analysis endpoints — start, monitor, and retrieve analysis results.
"""
import asyncio
import logging
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.desktop.api.services.analyzer import AnalysisManager, TaskStatus, ProgressEvent
from src.desktop.api.services.data_service import (
    create_snapshot_for_analysis,
    validate_stock_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# Will be set by main.py at startup
manager: Optional[AnalysisManager] = None


class AnalysisRequest(BaseModel):
    ts_code: str
    strategy: str
    auto_confirm: bool = True  # False = pause after data fetch for user review


# ==================== Stock Search ====================

# Provider-aware stock search caches: provider -> (database version, rows).
_stock_list_caches = {}
_stock_list_loading = set()
_stock_list_lock = threading.Lock()


def _stock_list_version(provider: str):
    """Return a lightweight version key that changes after a local DB write."""
    if provider == "akshare":
        return "instant"
    from src.data.config import get_provider_db_path

    path = get_provider_db_path(provider)
    candidates = (path, path.with_name(path.name + "-wal"))
    return tuple(
        (candidate.stat().st_mtime_ns, candidate.stat().st_size)
        if candidate.exists()
        else None
        for candidate in candidates
    )


def _load_stock_list(provider: str):
    """Load a stock list strictly from the selected provider's own boundary."""
    if provider == "akshare":
        import akshare as ak

        frame = ak.stock_info_a_code_name()
        return [
            {"code": str(row["code"]), "name": str(row["name"])}
            for _, row in frame.iterrows()
        ]

    from src.data import storage

    frame = storage.load_one("basic", "", "stock_list", provider=provider)
    if frame.empty:
        return []
    if "list_status" in frame.columns:
        frame = frame[frame["list_status"] == "L"]
    return [
        {"code": str(row["ts_code"]), "name": str(row["name"])}
        for _, row in frame.iterrows()
    ]


def preload_stock_list(provider_name: str = None):
    """Preload one provider's stock list without cross-provider fallback."""
    from src.data.config import get_active_provider_name

    provider = (provider_name or get_active_provider_name()).lower()
    version = _stock_list_version(provider)
    with _stock_list_lock:
        cached = _stock_list_caches.get(provider)
        if (cached and cached[0] == version) or provider in _stock_list_loading:
            return
        _stock_list_loading.add(provider)

    def _load():
        try:
            rows = _load_stock_list(provider)
            final_version = _stock_list_version(provider)
            with _stock_list_lock:
                _stock_list_caches[provider] = (final_version, rows)
            if rows:
                logger.info("Preloaded %s stocks from %s", len(rows), provider)
            elif provider != "akshare":
                logger.info("%s 本地股票列表为空，请先初始化基础数据", provider)
        except Exception as exc:
            logger.error("Failed to preload stock list from %s: %s", provider, exc)
        finally:
            with _stock_list_lock:
                _stock_list_loading.discard(provider)

    threading.Thread(target=_load, daemon=True).start()


@router.get("/stocks/search")
async def search_stocks(q: str = "", limit: int = 10):
    """Search stocks by code or name prefix."""
    if not q or len(q) < 1:
        return []

    from src.data.config import get_active_provider_name

    provider = get_active_provider_name()
    version = _stock_list_version(provider)
    preload_stock_list(provider)
    with _stock_list_lock:
        cached = _stock_list_caches.get(provider)
        stock_list = cached[1] if cached and cached[0] == version else None
    if stock_list is None:
        return []

    q_lower = q.lower()
    results = []
    for s in stock_list:
        if q_lower in s["code"].lower() or q_lower in s["name"].lower():
            # Normalize code format: 601288 → 601288.SH
            code = s["code"]
            if "." not in code:
                suffix = ".SH" if code.startswith(("6", "5")) else ".SZ"
                code = code + suffix
            results.append({"code": code, "name": s["name"]})
            if len(results) >= limit:
                break

    return results


# ==================== Test Data Fetch ====================

@router.get("/test-data")
async def test_data_fetch(ts_code: str):
    """Test data fetching for a stock — returns availability of each data source."""
    import time
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    start = time.time()
    sources = []

    def _fetch():
        try:
            snapshot, _, errors, _ = create_snapshot_for_analysis(ts_code)
            tests = [
                ("日线行情", snapshot.price_history),
                ("每日指标", snapshot.daily_indicators),
                ("资产负债表/指标", snapshot.balancesheet),
                ("利润表/指标", snapshot.income),
                ("现金流量表/指标", snapshot.cashflow),
                ("财务指标", snapshot.fina_indicator),
                ("分红历史", snapshot.dividend),
                ("十大股东", snapshot.top10_holders),
                ("近期新闻", snapshot.news),
                ("资金流向", snapshot.fund_flow),
                ("大盘指数", snapshot.index_daily),
            ]
            for name, frame in tests:
                sources.append({"name": name, "ok": not frame.empty, "rows": len(frame)})
            if errors:
                return "; ".join(errors)
        except Exception as e:
            return str(e)
        return None

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        error = await loop.run_in_executor(pool, _fetch)

    elapsed = round(time.time() - start, 1)

    if error:
        return {"error": error, "sources": sources, "elapsed": elapsed}
    return {"error": None, "sources": sources, "elapsed": elapsed}


# ==================== Industry Route Preview ====================

@router.get("/industry-route")
async def preview_industry_route(ts_code: str, strategy: str):
    """Preview how industry routing affects operators for a given stock + strategy."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    # Get industry
    industry = ""
    try:
        loop = asyncio.get_event_loop()
        def _get_industry():
            try:
                import akshare as ak
                df = ak.stock_individual_info_em(symbol=ts_code.replace('.SH','').replace('.SZ',''))
                if not df.empty:
                    row = df[df['item'] == '行业']
                    if not row.empty:
                        return str(row.iloc[0]['value']).replace('Ⅱ','').replace('Ⅲ','').strip()
            except Exception:
                pass
            # Fallback: check local stock list
            try:
                from src.data import api as data_api
                sl = data_api.get_stock_list()
                match = sl[sl['ts_code'] == ts_code]
                if not match.empty:
                    return match.iloc[0].get('industry', '')
            except Exception:
                pass
            return ""

        with ThreadPoolExecutor() as pool:
            industry = await loop.run_in_executor(pool, _get_industry)
    except Exception:
        pass

    if not industry:
        return {"industry": "", "routed": False, "chapters": []}

    # Load strategy and compute routing
    from src.data.settings import STRATEGIES_ROOT
    from src.engine.config import StrategyConfig

    strategy_path = STRATEGIES_ROOT / strategy / "strategy.yaml"
    if not strategy_path.exists():
        return {"industry": industry, "routed": False, "chapters": []}

    config = StrategyConfig.from_yaml(strategy_path)
    registry = config.get_operator_registry()
    chapter_defs = config.get_chapter_defs()

    chapters = []
    has_changes = False
    for ch in chapter_defs:
        op_ids = ch.get('operators', [])
        original = registry.resolve(op_ids)
        routed = registry.resolve(op_ids, industry=industry)

        original_ids = {o.id for o in original}
        routed_ids = {o.id for o in routed}
        skipped = original_ids - routed_ids
        added = routed_ids - original_ids

        if skipped or added:
            has_changes = True

        chapters.append({
            "id": ch["id"],
            "chapter": ch.get("chapter", 0),
            "title": ch.get("title", ""),
            "operators": [{"id": o.id, "name": o.name} for o in routed],
            "skipped": [{"id": oid, "name": registry.get(oid).name if registry.get(oid) else oid} for oid in skipped],
            "added": [{"id": o.id, "name": o.name} for o in routed if o.id in added],
        })

    return {
        "industry": industry,
        "routed": has_changes,
        "chapters": chapters,
    }


# ==================== Confirm & Continue ====================

@router.post("/{task_id}/confirm")
async def confirm_analysis(task_id: str):
    """Confirm data review and continue with analysis."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Analysis manager not initialized")

    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    snapshot = getattr(task, '_snapshot', None)
    if not snapshot:
        raise HTTPException(status_code=400, detail="No pending snapshot to confirm")

    # Start analysis
    asyncio.create_task(manager.run_analysis(task, snapshot))
    task._snapshot = None  # Clear

    return {"status": "confirmed", "message": "分析已开始"}


@router.post("/{task_id}/cancel")
async def cancel_analysis(task_id: str):
    """Cancel a pending analysis."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Analysis manager not initialized")

    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    task.status = TaskStatus.FAILED
    task.error = "用户取消"
    task._emit(ProgressEvent(event="error", data={"message": "用户取消分析"}))
    task._snapshot = None

    return {"status": "cancelled"}


# ==================== Snapshot Preview ====================

@router.get("/snapshot-preview")
async def get_snapshot_preview(ts_code: str):
    """Get the latest snapshot preview markdown for a stock (from today's cache)."""
    from src.desktop.api.services.data_service import _get_cache_dir

    cache_dir = _get_cache_dir(ts_code)
    preview_path = cache_dir / "snapshot_preview.md"

    if preview_path.exists():
        return {"content": preview_path.read_text(encoding="utf-8"), "source": "cache"}

    return {"content": "", "source": "none"}


class AnalysisResponse(BaseModel):
    task_id: str
    status: str
    message: str


@router.post("/start", response_model=AnalysisResponse)
async def start_analysis(request: AnalysisRequest):
    """Start a new analysis task."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Analysis manager not initialized")

    # Validate stock code
    valid, error_msg = validate_stock_code(request.ts_code)
    if not valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Resolve strategy path
    from src.data.settings import STRATEGIES_ROOT
    strategy_path = STRATEGIES_ROOT / request.strategy / "strategy.yaml"
    if not strategy_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Strategy not found: {request.strategy}"
        )

    # Create task
    task = manager.create_task(
        ts_code=request.ts_code,
        strategy_name=request.strategy,
        strategy_path=str(strategy_path),
    )

    # Prepare data (snapshot) in background, then run analysis
    async def _run():
        try:
            task.status = TaskStatus.PREPARING_DATA
            task._emit(ProgressEvent(event="preparing_data", data={
                "ts_code": request.ts_code,
            }))

            # Create snapshot (blocking I/O, run in thread)
            loop = asyncio.get_event_loop()
            snapshot, is_valid, errors, warnings = await loop.run_in_executor(
                None, create_snapshot_for_analysis, request.ts_code, str(strategy_path)
            )

            if not is_valid:
                task.status = TaskStatus.FAILED
                task.error = f"Data validation failed: {'; '.join(errors)}"
                task._emit(ProgressEvent(event="error", data={
                    "message": task.error,
                    "errors": errors,
                }))
                return

            if warnings:
                task._emit(ProgressEvent(event="data_warnings", data={
                    "warnings": warnings,
                }))

            task._emit(ProgressEvent(event="data_ready", data={
                "stock_name": snapshot.stock_name,
                "industry": snapshot.industry,
                "data_sources": snapshot.data_sources,
                "cutoff_date": snapshot.cutoff_date,
            }))

            # Save snapshot preview immediately (before analysis starts)
            try:
                from src.data.snapshot import snapshot_to_markdown
                from src.desktop.api.services.data_service import _get_cache_dir
                cache_dir = _get_cache_dir(request.ts_code)
                cache_dir.mkdir(parents=True, exist_ok=True)
                snap_md = snapshot_to_markdown(snapshot, blind_mode=False)
                (cache_dir / "snapshot_preview.md").write_text(snap_md, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to save snapshot preview: {e}")

            # If not auto_confirm, pause and wait for user to confirm
            if not request.auto_confirm:
                task._emit(ProgressEvent(event="waiting_confirm", data={
                    "message": "数据已就绪，请检查后点击「继续分析」",
                }))
                task._snapshot = snapshot  # Store for later
                return  # Don't start analysis yet

            # Run the actual analysis
            await manager.run_analysis(task, snapshot)

        except Exception as e:
            logger.exception(f"Task {task.task_id} failed")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task._emit(ProgressEvent(event="error", data={"message": str(e)}))

    asyncio.create_task(_run())

    return AnalysisResponse(
        task_id=task.task_id,
        status=task.status.value,
        message="Analysis started",
    )


@router.get("/{task_id}/status")
async def get_status(task_id: str):
    """Get current task status and progress summary."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Analysis manager not initialized")

    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    # Build progress summary
    chapters_done = set()
    chapters_running = set()
    stock_name = ""
    industry = ""
    synthesis_status = "pending"

    for event in task.progress_events:
        if event.event == "chapter_done" and event.chapter_id:
            chapters_done.add(event.chapter_id)
            chapters_running.discard(event.chapter_id)
        elif event.event == "chapter_start" and event.chapter_id:
            if event.chapter_id not in chapters_done:
                chapters_running.add(event.chapter_id)
        elif event.event == "data_ready" and event.data:
            stock_name = event.data.get("stock_name", "")
            industry = event.data.get("industry", "")
        elif event.event == "analysis_start" and event.data:
            stock_name = event.data.get("stock_name", stock_name)
        elif event.event == "synthesis_start":
            synthesis_status = "running"
        elif event.event == "synthesis_done":
            synthesis_status = "complete"

    # Build per-chapter status list
    chapters = []
    try:
        from src.engine.config import StrategyConfig
        from src.data.settings import STRATEGIES_ROOT
        config = StrategyConfig.from_yaml(
            STRATEGIES_ROOT / task.strategy_name / "strategy.yaml"
        )
        for ch in config.get_chapter_defs():
            ch_id = ch["id"]
            if ch_id in chapters_done:
                st = "complete"
            elif ch_id in chapters_running:
                st = "running"
            else:
                st = "pending"
            chapters.append({"id": ch_id, "status": st})
    except Exception:
        pass

    return {
        "task_id": task.task_id,
        "ts_code": task.ts_code,
        "strategy": task.strategy_name,
        "status": task.status.value,
        "error": task.error,
        "stock_name": stock_name,
        "industry": industry,
        "chapters": chapters,
        "synthesis_status": synthesis_status,
        "event_count": len(task.progress_events),
        "created_at": task.created_at,
        "completed_at": task.completed_at,
    }


@router.get("/{task_id}/result")
async def get_result(task_id: str):
    """Get the final analysis result."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Analysis manager not initialized")

    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    if task.status == TaskStatus.FAILED:
        raise HTTPException(status_code=500, detail=task.error or "Analysis failed")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=202, detail="Analysis still in progress")

    return {
        "task_id": task.task_id,
        "ts_code": task.ts_code,
        "strategy": task.strategy_name,
        "result": task.result,
    }


@router.websocket("/{task_id}/ws")
async def websocket_progress(websocket: WebSocket, task_id: str):
    """
    Real-time progress stream via WebSocket.

    Sends JSON messages:
    {
        "event": "chapter_start|chapter_done|synthesis_start|synthesis_done|error|...",
        "data": {...},
        "chapter_id": "ch01_screening" (optional),
        "timestamp": 1234567890.123
    }
    """
    if manager is None:
        await websocket.close(code=1011, reason="Manager not initialized")
        return

    task = manager.get_task(task_id)
    if not task:
        await websocket.close(code=1008, reason=f"Task not found: {task_id}")
        return

    await websocket.accept()
    queue = task.add_subscriber()

    try:
        while True:
            try:
                # Wait for next event with timeout
                event: ProgressEvent = await asyncio.wait_for(
                    queue.get(), timeout=30.0
                )
                await websocket.send_json({
                    "event": event.event,
                    "chapter_id": event.chapter_id,
                    "data": event.data or {},
                    "timestamp": event.timestamp,
                })

                # Close after terminal events
                if event.event in ("analysis_complete", "error"):
                    # Send final result if available
                    if event.event == "analysis_complete" and task.result:
                        await websocket.send_json({
                            "event": "result",
                            "data": {
                                "synthesis": task.result.get("synthesis", {}),
                                "metadata": task.result.get("metadata", {}),
                                "chapter_texts": task.result.get("chapter_texts", {}),
                                "chapter_outputs": task.result.get("chapter_outputs", {}),
                            },
                            "chapter_id": None,
                            "timestamp": event.timestamp,
                        })
                    break

            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"event": "ping", "data": {}, "chapter_id": None, "timestamp": 0})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for task {task_id}")
    except Exception as e:
        logger.warning(f"WebSocket error for task {task_id}: {e}")
    finally:
        task.remove_subscriber(queue)
        try:
            await websocket.close()
        except Exception:
            pass
