"""External runtime paths and one-time migration for the desktop application."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict

from src.data.settings import DATA_ROOT, PROJECT_ROOT

logger = logging.getLogger(__name__)

DESKTOP_RUNTIME_DIR = DATA_ROOT / "desktop"
DESKTOP_CONFIG_PATH = DESKTOP_RUNTIME_DIR / "config.json"
CHAT_HISTORY_PATH = DESKTOP_RUNTIME_DIR / "chat_history.json"

LEGACY_DESKTOP_DIR = PROJECT_ROOT / "src" / "desktop"
LEGACY_CONFIG_PATH = LEGACY_DESKTOP_DIR / "config.json"
LEGACY_CHAT_HISTORY_PATH = LEGACY_DESKTOP_DIR / "chat_history.json"


def _migrate_file(source: Path, destination: Path) -> bool:
    """Copy one legacy runtime file externally, then remove the verified source."""
    if destination.exists() or not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if destination.read_bytes() != source.read_bytes():
        destination.unlink(missing_ok=True)
        raise OSError(f"运行时文件迁移校验失败: {source}")
    source.unlink()
    logger.info("Migrated desktop runtime file: %s -> %s", source, destination)
    return True


def prepare_runtime_files(
    config_path: Path = DESKTOP_CONFIG_PATH,
    history_path: Path = CHAT_HISTORY_PATH,
    legacy_config_path: Path = LEGACY_CONFIG_PATH,
    legacy_history_path: Path = LEGACY_CHAT_HISTORY_PATH,
) -> Dict[str, bool]:
    """Create the external runtime directory and migrate legacy user files."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "config": _migrate_file(legacy_config_path, config_path),
        "history": _migrate_file(legacy_history_path, history_path),
    }
