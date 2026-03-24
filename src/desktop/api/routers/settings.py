"""
Settings endpoints — manage user configuration.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Config file path — set by main.py
_config_path: Optional[Path] = None

# Default settings
_DEFAULTS = {
    "llm_api_key": "",
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
    "temperature": 0.3,
    "concurrency": 3,
}


def set_config_path(path: Path):
    """Set the config file path (called during startup)."""
    global _config_path
    _config_path = path


def _load_settings() -> dict:
    """Load settings from config.json."""
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
    if _config_path:
        _config_path.parent.mkdir(parents=True, exist_ok=True)
        _config_path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SettingsUpdate(BaseModel):
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    concurrency: Optional[int] = None


@router.get("")
async def get_settings():
    """Get current settings (API key is masked)."""
    settings = _load_settings()
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
    return masked


@router.put("")
async def update_settings(update: SettingsUpdate):
    """Update settings."""
    current = _load_settings()

    if update.llm_api_key is not None:
        current["llm_api_key"] = update.llm_api_key
    if update.llm_base_url is not None:
        current["llm_base_url"] = update.llm_base_url
    if update.llm_model is not None:
        current["llm_model"] = update.llm_model
    if update.temperature is not None:
        current["temperature"] = max(0.0, min(2.0, update.temperature))
    if update.concurrency is not None:
        current["concurrency"] = max(1, min(10, update.concurrency))

    _save_settings(current)

    # Return masked version
    return await get_settings()


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
