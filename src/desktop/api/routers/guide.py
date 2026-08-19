"""Product guide content and first-run state."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.settings import PROJECT_ROOT

from . import settings

router = APIRouter(prefix="/api/guide", tags=["guide"])

GUIDE_VERSION = "1.1"
GUIDE_PATH = PROJECT_ROOT / "docs" / "PRODUCT_GUIDE.md"
_INTRO_START = "<!-- guide:intro:start -->"
_INTRO_END = "<!-- guide:intro:end -->"


class GuideSeenRequest(BaseModel):
    version: str


def _load_guide(path: Optional[Path] = None) -> tuple[str, str]:
    path = path or GUIDE_PATH
    if not path.exists():
        raise HTTPException(status_code=500, detail="产品指引文件不存在")
    content = path.read_text(encoding="utf-8")
    if _INTRO_START not in content or _INTRO_END not in content:
        raise HTTPException(status_code=500, detail="产品指引缺少首次介绍区段")
    intro = content.split(_INTRO_START, 1)[1].split(_INTRO_END, 1)[0].strip()
    return content, intro


@router.get("")
async def get_guide():
    content, intro = _load_guide()
    runtime_settings = settings.load_runtime_settings()
    seen_version = str(runtime_settings.get("guide_seen_version", ""))
    return {
        "version": GUIDE_VERSION,
        "seen": seen_version == GUIDE_VERSION,
        "seen_version": seen_version,
        "content": content,
        "intro": intro,
    }


@router.put("/seen")
async def mark_guide_seen(request: GuideSeenRequest):
    if request.version != GUIDE_VERSION:
        raise HTTPException(status_code=409, detail="产品指引版本已经更新")
    settings.update_runtime_settings({"guide_seen_version": GUIDE_VERSION})
    return {"version": GUIDE_VERSION, "seen": True}
