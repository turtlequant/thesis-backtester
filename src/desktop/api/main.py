"""
FastAPI application — desktop backend entry point.

Serves the API endpoints and static frontend files.
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure project root is on sys.path for src.* imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # api -> desktop -> src -> project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.desktop.api.routers import analysis, strategies, reports, settings, operators, frameworks, datasources, chat
from src.desktop.api.services.analyzer import AnalysisManager

logger = logging.getLogger(__name__)

DESKTOP_DIR = Path(__file__).parent.parent
CONFIG_PATH = DESKTOP_DIR / "config.json"
FRONTEND_DIR = DESKTOP_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — setup and teardown."""
    logger.info("Starting desktop API server...")

    # Initialize analysis manager
    manager = AnalysisManager(project_root=PROJECT_ROOT)

    # Wire up shared manager to routers
    analysis.manager = manager
    reports.manager = manager

    # Configure settings module
    settings.set_config_path(CONFIG_PATH)
    chat.set_config(CONFIG_PATH, PROJECT_ROOT)

    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Config path: {CONFIG_PATH}")
    logger.info(f"Frontend dir: {FRONTEND_DIR}")

    # Preload stock list for fast search
    analysis.preload_stock_list()

    yield

    # Cleanup
    logger.info("Shutting down desktop API server...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="投研分析工具",
        description="AI-driven investment analysis desktop tool",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS for local development (browser access)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routers
    app.include_router(analysis.router)
    app.include_router(strategies.router)
    app.include_router(reports.router)
    app.include_router(settings.router)
    app.include_router(operators.router)
    app.include_router(frameworks.router)
    app.include_router(datasources.router)
    app.include_router(chat.router)

    # Serve frontend static files
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
