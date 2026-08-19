"""Shared application, resource, and runtime-data paths."""
from __future__ import annotations

import os
import shutil
import sys
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def resolve_project_root(
    module_file: Path = Path(__file__),
    executable: Path = Path(sys.executable),
    compiled: bool | None = None,
) -> Path:
    """Resolve the repository root in source mode and the EXE directory in builds."""
    if compiled is None:
        compiled = "__compiled__" in globals() or bool(getattr(sys, "frozen", False))
    if compiled:
        return Path(executable).resolve().parent
    return Path(module_file).resolve().parents[2]


PROJECT_ROOT = resolve_project_root()


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE settings without overriding the process environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file(PROJECT_ROOT / ".env")


def resolve_workspace_root(value: str | None = None) -> Path:
    """Return the complete, portable research-workspace directory."""
    configured = str(value if value is not None else os.environ.get(
        "THESIS_BACKTESTER_WORKSPACE_DIR", ""
    )).strip()
    if not configured:
        return PROJECT_ROOT / "workspace"
    path = Path(configured).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


WORKSPACE_ROOT = resolve_workspace_root()
WORKSPACE_SEED_ROOT = PROJECT_ROOT / "resources" / "workspace_seed"
_load_env_file(WORKSPACE_ROOT / ".env")


def resolve_data_root(value: str | None = None) -> Path:
    """Return workspace data, with an optional storage-volume override."""
    configured = str(value if value is not None else os.environ.get(
        "THESIS_BACKTESTER_DATA_DIR", ""
    )).strip()
    if not configured:
        return WORKSPACE_ROOT / "data"
    path = Path(configured).expanduser()
    return path.resolve() if path.is_absolute() else (WORKSPACE_ROOT / path).resolve()


DATA_ROOT = resolve_data_root()
STRATEGIES_ROOT = WORKSPACE_ROOT / "strategies"
OPERATORS_ROOT = WORKSPACE_ROOT / "operators"
FACTORS_ROOT = WORKSPACE_ROOT / "factors"
SCREENING_STRATEGIES_ROOT = WORKSPACE_ROOT / "screening_strategies"


def _copy_seed_missing(source: Path, destination: Path) -> None:
    """Copy immutable release defaults without overwriting workspace edits."""
    if not source.exists():
        return
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def prepare_workspace() -> dict[str, str]:
    """Migrate the legacy five-root layout and seed missing built-in assets."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    migrated: dict[str, str] = {}
    roots = {
        "data": DATA_ROOT,
        "strategies": STRATEGIES_ROOT,
        "operators": OPERATORS_ROOT,
        "factors": FACTORS_ROOT,
        "screening_strategies": SCREENING_STRATEGIES_ROOT,
    }
    for name, destination in roots.items():
        legacy = PROJECT_ROOT / name
        if destination.exists() or not legacy.exists() or legacy == destination:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(destination)
        migrated[name] = str(destination)
        logger.info("Migrated legacy workspace directory: %s -> %s", legacy, destination)

    _copy_seed_missing(WORKSPACE_SEED_ROOT, WORKSPACE_ROOT)
    for destination in roots.values():
        destination.mkdir(parents=True, exist_ok=True)
    return migrated

SNAPSHOT_DIR = DATA_ROOT / "snapshots"
ANALYSIS_DB_PATH = DATA_ROOT / "analysis_results" / "results.db"
