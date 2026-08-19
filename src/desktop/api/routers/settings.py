"""
Settings endpoints — manage user configuration.
"""
import json
import logging
from datetime import date, datetime
from pathlib import Path
from threading import RLock
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from src.data.config import load_data_config, save_data_config
from src.data.provider import PROVIDER_CAPABILITIES, clear_provider_cache
from src.desktop import network_access
from src.version import app_info

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Config file path — set by main.py
_config_path: Optional[Path] = None
_settings_lock = RLock()

# Default settings
_DEFAULTS = {
    "llm_api_key": "",
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
    "temperature": 0.3,
    "max_tokens": 8192,
    "concurrency": 3,
    network_access.LAN_ENABLED_KEY: False,
}


def set_config_path(path: Path):
    """Set the config file path (called during startup)."""
    global _config_path
    _config_path = path
    network_access.set_config_path(path)


def _load_settings() -> dict:
    """Load settings from config.json."""
    with _settings_lock:
        if _config_path and _config_path.exists():
            try:
                data = json.loads(_config_path.read_text(encoding="utf-8"))
                # Merge with defaults for any missing keys
                result = {**_DEFAULTS, **data}
                return result
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        return dict(_DEFAULTS)


def _save_settings(settings: dict):
    """Save settings to config.json."""
    with _settings_lock:
        if _config_path:
            _config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = _config_path.with_suffix(_config_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(_config_path)


def load_runtime_settings() -> dict:
    """Return the complete local desktop configuration for internal services."""
    return _load_settings()


def update_runtime_settings(changes: dict) -> dict:
    """Atomically merge internal runtime state into the desktop configuration."""
    with _settings_lock:
        current = _load_settings()
        current.update(changes)
        _save_settings(current)
        return current


class SettingsUpdate(BaseModel):
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    concurrency: Optional[int] = None
    data_provider: Optional[str] = None
    tushare_token: Optional[str] = None
    data_start_date: Optional[str] = None
    auto_update_enabled: Optional[bool] = None
    auto_update_time: Optional[str] = None
    auto_update_financials: Optional[bool] = None
    lan_access_enabled: Optional[bool] = None
    reset_lan_access_token: Optional[bool] = None


@router.get("")
async def get_settings():
    """Get current settings (API key is masked)."""
    settings = _load_settings()
    data_settings = load_data_config()
    settings.update(
        {
            "data_provider": data_settings["provider"],
            "data_start_date": data_settings["data_start_date"],
            "auto_update_enabled": data_settings["auto_update_enabled"],
            "auto_update_time": data_settings["auto_update_time"],
            "auto_update_financials": data_settings["auto_update_financials"],
            "data_providers": [item.to_dict() for item in PROVIDER_CAPABILITIES.values()],
        }
    )
    # Mask the API key for display
    masked = dict(settings)
    if masked.get("llm_api_key"):
        key = masked["llm_api_key"]
        if len(key) > 8:
            masked["llm_api_key_masked"] = key[:4] + "*" * (len(key) - 8) + key[-4:]
        else:
            masked["llm_api_key_masked"] = "****"
        masked["llm_api_key_set"] = True
    else:
        masked["llm_api_key_masked"] = ""
        masked["llm_api_key_set"] = False
    # Never send raw key to frontend
    del masked["llm_api_key"]
    masked.pop(network_access.LAN_TOKEN_HASH_KEY, None)

    configured_lan_access = bool(settings.get(network_access.LAN_ENABLED_KEY, False))
    active_lan_access = network_access.is_lan_access_active()
    masked["lan_access_enabled"] = configured_lan_access
    masked["lan_access_active"] = active_lan_access
    masked["lan_access_restart_required"] = configured_lan_access != active_lan_access
    masked["lan_access_token_set"] = bool(
        settings.get(network_access.LAN_TOKEN_HASH_KEY)
    )
    masked["lan_access_urls"] = network_access.lan_access_urls()
    masked.update({f"app_{key}": value for key, value in app_info().items()})

    token = str(data_settings.get("tushare_token", ""))
    masked["tushare_token_set"] = bool(token)
    if token:
        masked["tushare_token_masked"] = (
            token[:4] + "*" * max(4, len(token) - 8) + token[-4:]
            if len(token) > 8
            else "****"
        )
    else:
        masked["tushare_token_masked"] = ""
    return masked


@router.get("/app-info")
async def get_app_info():
    """Return the canonical release identity without loading user settings."""
    return app_info()


@router.put("")
async def update_settings(update: SettingsUpdate):
    """Update settings."""
    current = _load_settings()
    generated_lan_token = ""

    if update.llm_api_key is not None:
        current["llm_api_key"] = update.llm_api_key
    if update.llm_base_url is not None:
        current["llm_base_url"] = update.llm_base_url
    if update.llm_model is not None:
        current["llm_model"] = update.llm_model
    if update.temperature is not None:
        current["temperature"] = max(0.0, min(2.0, update.temperature))
    if update.max_tokens is not None:
        current["max_tokens"] = max(1024, min(65536, update.max_tokens))
    if update.concurrency is not None:
        current["concurrency"] = max(1, min(10, update.concurrency))
    if update.lan_access_enabled is not None:
        current[network_access.LAN_ENABLED_KEY] = bool(update.lan_access_enabled)
        if update.lan_access_enabled and not current.get(network_access.LAN_TOKEN_HASH_KEY):
            generated_lan_token = network_access.generate_access_token()
            current[network_access.LAN_TOKEN_HASH_KEY] = network_access.hash_access_token(
                generated_lan_token
            )
    if update.reset_lan_access_token:
        generated_lan_token = network_access.generate_access_token()
        current[network_access.LAN_TOKEN_HASH_KEY] = network_access.hash_access_token(
            generated_lan_token
        )

    data_changes = {}
    if update.data_provider is not None:
        data_changes["provider"] = update.data_provider.lower()
    if update.tushare_token is not None:
        data_changes["tushare_token"] = update.tushare_token.strip()
    if update.data_start_date is not None:
        try:
            date.fromisoformat(update.data_start_date)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="数据起始日必须为 YYYY-MM-DD") from exc
        data_changes["data_start_date"] = update.data_start_date
    if update.auto_update_enabled is not None:
        data_changes["auto_update_enabled"] = update.auto_update_enabled
    if update.auto_update_time is not None:
        value = update.auto_update_time
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="自动更新时间必须为 HH:MM") from exc
        data_changes["auto_update_time"] = value
    if update.auto_update_financials is not None:
        data_changes["auto_update_financials"] = update.auto_update_financials
    if data_changes:
        previous_data_settings = load_data_config()
        try:
            updated_data_settings = save_data_config(data_changes)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if (
            updated_data_settings.get("tushare_token")
            != previous_data_settings.get("tushare_token")
        ):
            clear_provider_cache("tushare")

    _save_settings(current)

    # Return masked version
    response = await get_settings()
    if generated_lan_token:
        response["lan_access_token"] = generated_lan_token
    return response


@router.get("/test-llm")
async def test_llm_connection():
    """Test LLM API connection with a simple request."""
    import time
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    settings = _load_settings()
    api_key = settings.get("llm_api_key", "")
    base_url = settings.get("llm_base_url", "")
    model = settings.get("llm_model", "deepseek-chat")
    temperature = settings.get("temperature", 0.3)

    if not api_key:
        return {"success": False, "error": "未配置 API Key"}

    start = time.time()

    def _test():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "请用一句话介绍你自己"}],
                max_tokens=50,
                temperature=temperature,
            )
            reply = response.choices[0].message.content.strip()
            return {"success": True, "reply": reply, "model": model}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _test)

    result["elapsed"] = round(time.time() - start, 1)
    return result
