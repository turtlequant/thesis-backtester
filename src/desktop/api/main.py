"""
FastAPI application — desktop backend entry point.

Serves the API endpoints and static frontend files.
"""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.desktop.api.routers import (  # noqa: E402
    analysis,
    chat,
    datasources,
    factors,
    frameworks,
    guide,
    network,
    operators,
    qualitative,
    research,
    reports,
    settings,
    strategies,
)
from src.desktop.api.services.analyzer import AnalysisManager  # noqa: E402
from src.desktop.api.services.research_jobs import research_job_manager  # noqa: E402
from src.desktop.api.services.qualitative_jobs import qualitative_job_manager  # noqa: E402
from src.desktop.runtime import (  # noqa: E402
    CHAT_HISTORY_PATH,
    DESKTOP_CONFIG_PATH,
    prepare_runtime_files,
)
from src.desktop.network_access import NetworkAccessMiddleware  # noqa: E402
from src.version import __version__  # noqa: E402
from src.data.jobs import auto_update_loop, job_manager  # noqa: E402
from src.data.settings import PROJECT_ROOT, WORKSPACE_ROOT, prepare_workspace  # noqa: E402

logger = logging.getLogger(__name__)

DESKTOP_DIR = PROJECT_ROOT / "src" / "desktop"
CONFIG_PATH = DESKTOP_CONFIG_PATH
FRONTEND_DIR = DESKTOP_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — setup and teardown."""
    logger.info("Starting desktop API server...")
    prepare_workspace()
    prepare_runtime_files()

    # Initialize analysis manager
    manager = AnalysisManager(project_root=WORKSPACE_ROOT, config_path=CONFIG_PATH)

    # Wire up shared manager to routers
    analysis.manager = manager
    reports.manager = manager

    # Configure settings module
    settings.set_config_path(CONFIG_PATH)
    chat.set_config(CONFIG_PATH, WORKSPACE_ROOT, CHAT_HISTORY_PATH)

    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Workspace root: {WORKSPACE_ROOT}")
    logger.info(f"Config path: {CONFIG_PATH}")
    logger.info(f"Chat history path: {CHAT_HISTORY_PATH}")
    logger.info(f"Frontend dir: {FRONTEND_DIR}")

    # Preload stock list for fast search
    analysis.preload_stock_list()

    # Reconcile built-in/migrated factor definitions with local provider data.
    # The work runs in the existing single data queue and never blocks startup.
    factors.schedule_catalog_materializations()

    auto_update_task = asyncio.create_task(auto_update_loop())

    yield

    # Cleanup
    auto_update_task.cancel()
    with suppress(asyncio.CancelledError):
        await auto_update_task
    job_manager.cancel_all()
    # Wait for the cooperative cancellation to leave the data worker before
    # Python begins interpreter shutdown. Otherwise a running factor job can
    # fail with "cannot schedule new futures after interpreter shutdown".
    job_manager.shutdown(wait=True)
    research_job_manager.shutdown()
    qualitative_job_manager.shutdown()
    logger.info("Shutting down desktop API server...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Thesis Backtester API",
        description="Structured investment research and validation engine",
        version=__version__,
        lifespan=lifespan,
    )

    # The frontend is served from the same origin. Remote API and WebSocket
    # calls are protected when opt-in LAN access is active.
    app.add_middleware(NetworkAccessMiddleware)

    # Register API routers
    app.include_router(analysis.router)
    app.include_router(strategies.router)
    app.include_router(reports.router)
    app.include_router(settings.router)
    app.include_router(operators.router)
    app.include_router(frameworks.router)
    app.include_router(datasources.router)
    app.include_router(factors.router)
    app.include_router(research.router)
    app.include_router(qualitative.router)
    app.include_router(chat.router)
    app.include_router(guide.router)
    app.include_router(network.router)

    # Serve frontend static files
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
