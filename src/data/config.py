"""Persistent configuration for the local data layer.

The desktop UI and command line tools share this file.  Provider credentials and
download preferences are runtime data and therefore live below ``workspace/data/`` rather
than in the source tree.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from .settings import DATA_ROOT

DATA_CONFIG_PATH = DATA_ROOT / "data_config.json"
SUPPORTED_PROVIDERS = ("baostock", "tushare", "akshare")

DEFAULT_DATA_CONFIG: Dict[str, Any] = {
    "provider": "baostock",
    "tushare_token": "",
    "data_start_date": "2015-01-01",
    "auto_update_enabled": False,
    "auto_update_time": "18:30",
    "auto_update_financials": True,
}

_lock = RLock()


def load_data_config() -> Dict[str, Any]:
    """Load data configuration, with environment variables taking precedence."""
    with _lock:
        config = dict(DEFAULT_DATA_CONFIG)
        if DATA_CONFIG_PATH.exists():
            try:
                stored = json.loads(DATA_CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    config.update(stored)
            except (OSError, ValueError):
                # A malformed optional config must not prevent the application
                # from starting; the UI can overwrite it with valid settings.
                pass

        if os.environ.get("DATA_PROVIDER"):
            config["provider"] = os.environ["DATA_PROVIDER"].strip().lower()
        if os.environ.get("TUSHARE_TOKEN"):
            config["tushare_token"] = os.environ["TUSHARE_TOKEN"].strip()
        if os.environ.get("DATA_START_DATE"):
            config["data_start_date"] = os.environ["DATA_START_DATE"].strip()

        if config["provider"] not in SUPPORTED_PROVIDERS:
            config["provider"] = DEFAULT_DATA_CONFIG["provider"]
        return config


def save_data_config(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist a partial data configuration update."""
    with _lock:
        current = load_data_config()
        updated = {**current, **changes}
        provider = str(updated.get("provider", "")).lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的数据源: {provider}")
        updated["provider"] = provider
        try:
            date.fromisoformat(str(updated["data_start_date"]))
        except ValueError as exc:
            raise ValueError("数据起始日必须为 YYYY-MM-DD") from exc
        try:
            datetime.strptime(str(updated["auto_update_time"]), "%H:%M")
        except ValueError as exc:
            raise ValueError("自动更新时间必须为 HH:MM") from exc
        updated["auto_update_enabled"] = bool(updated["auto_update_enabled"])
        updated["auto_update_financials"] = bool(updated["auto_update_financials"])

        DATA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_CONFIG_PATH.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return updated


def get_active_provider_name() -> str:
    return str(load_data_config()["provider"])


def get_data_start_date() -> str:
    return str(load_data_config()["data_start_date"])


def get_tushare_token() -> str:
    return str(load_data_config().get("tushare_token", ""))


def get_provider_db_path(provider: Optional[str] = None) -> Path:
    """Return the isolated SQLite database path for a provider."""
    name = (provider or get_active_provider_name()).lower()
    if name not in SUPPORTED_PROVIDERS:
        raise ValueError(f"不支持的数据源: {name}")
    return DATA_ROOT / "providers" / name / "market.db"
