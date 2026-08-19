import asyncio
import json

import pytest
from fastapi import HTTPException

from src.desktop.api.routers import guide, settings


def test_product_guide_is_file_backed_and_seen_state_is_external(tmp_path):
    config_path = tmp_path / "desktop" / "config.json"
    settings.set_config_path(config_path)

    initial = asyncio.run(guide.get_guide())
    assert initial["version"] == guide.GUIDE_VERSION
    assert initial["seen"] is False
    assert "算子 + 层级编排" in initial["intro"]
    assert "最新批量研判" in initial["intro"]
    assert "框架验证" in initial["content"]
    assert "当前新闻、当前资金流" in initial["content"]
    assert "源码" not in initial["content"]

    marked = asyncio.run(
        guide.mark_guide_seen(guide.GuideSeenRequest(version=guide.GUIDE_VERSION))
    )
    assert marked["seen"] is True
    assert asyncio.run(guide.get_guide())["seen"] is True
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["guide_seen_version"] == guide.GUIDE_VERSION


def test_product_guide_rejects_stale_seen_version(tmp_path):
    settings.set_config_path(tmp_path / "config.json")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(guide.mark_guide_seen(guide.GuideSeenRequest(version="old")))

    assert exc_info.value.status_code == 409
