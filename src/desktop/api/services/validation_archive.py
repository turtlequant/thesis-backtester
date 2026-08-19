"""Read-only adapter for historical framework-validation artifacts.

Legacy batch backtests predate the desktop job schema.  They remain useful
research evidence, but must not be presented as runs of the current form or
current screening-strategy definition.  This module converts their summaries
to the current result contract while keeping the provenance explicit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.data.settings import STRATEGIES_ROOT


FRAMEWORKS_ROOT = STRATEGIES_ROOT


def _timestamp(payload: Dict[str, Any], path: Path) -> str:
    value = str(payload.get("generated_at") or "").strip()
    if value:
        return value
    return path.stat().st_mtime_ns.__str__()


def _archive_id(path: Path) -> str:
    return "historical-" + hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _slice_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    scores = item.get("agent_scores") if isinstance(item.get("agent_scores"), dict) else {}
    buy_count = sum(
        1
        for value in scores.values()
        if isinstance(value, dict) and "买入" in str(value.get("recommendation") or "")
    )
    return {
        "cutoff_date": str(item.get("cutoff_date") or ""),
        "screen_count": int(item.get("screen_count") or 0),
        "agent_count": int(item.get("agent_count") or len(scores)),
        "agent_completed": len(scores),
        "agent_buy_count": buy_count,
    }


def _group_key(framework_id: str, payload: Dict[str, Any]) -> Tuple[str, str, str, str]:
    dates = [str(value) for value in payload.get("dates", []) if value]
    return (
        framework_id,
        dates[0] if dates else "",
        dates[-1] if dates else "",
        str(payload.get("interval") or ""),
    )


def _convert(path: Path, frameworks_root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    framework_id = path.parent.parent.name
    dates = [str(value) for value in payload.get("dates", []) if value]
    slices = [_slice_summary(item) for item in payload.get("slices", []) if isinstance(item, dict)]
    total = sum(item["agent_count"] for item in slices)
    completed = sum(item["agent_completed"] for item in slices)
    report_path = path.with_name(path.name.replace("backtest_summary_", "backtest_report_")).with_suffix(".md")
    relative_summary = path.relative_to(frameworks_root.parent)
    relative_report = report_path.relative_to(frameworks_root.parent) if report_path.exists() else None
    generated_at = str(payload.get("generated_at") or "")
    top_n = max((item["agent_count"] for item in slices), default=0)
    outcome_schema_version = int(payload.get("outcome_schema_version") or 1)
    return_basis = str(payload.get("return_basis") or "legacy_unspecified")

    return {
        "id": _archive_id(path),
        "kind": "framework_validation",
        "status": "completed",
        "stage": "completed",
        "message": "历史批量回测已转换为只读验证档案",
        "imported": True,
        "read_only": True,
        "is_current": False,
        "created_at": generated_at,
        "finished_at": generated_at,
        "params": {
            "framework_id": framework_id,
            "framework_name": str(payload.get("strategy") or framework_id),
            "framework_version": str(payload.get("version") or ""),
            "screening_strategy_name": str(
                payload.get("screening_strategy_name") or "历史内嵌筛选配置"
            ),
            "start_date": dates[0] if dates else "",
            "end_date": dates[-1] if dates else "",
            "interval": str(payload.get("interval") or ""),
            "top_n": top_n,
            "provider": str(payload.get("provider") or "未记录"),
        },
        "progress": {"total": total, "completed": completed, "failed": max(0, total - completed)},
        "rows": [],
        "result": {
            "outcome_schema_version": outcome_schema_version,
            "evaluation_semantics": str(payload.get("evaluation_semantics") or "legacy"),
            "return_basis": return_basis,
            "dates": dates,
            "interval": str(payload.get("interval") or ""),
            "slices": slices,
            "performance": payload.get("performance") if isinstance(payload.get("performance"), dict) else {},
            "analysis_total": total,
            "analysis_completed": completed,
            "analysis_failed": max(0, total - completed),
            "report_path": str(relative_report).replace("\\", "/") if relative_report else "",
            "summary_path": str(relative_summary).replace("\\", "/"),
        },
        "provenance": {
            "type": "legacy_backtest_artifact",
            "label": "历史批量回测",
            "source_file": str(relative_summary).replace("\\", "/"),
            "provider_recorded": bool(payload.get("provider")),
            "outcome_recomputed": (
                outcome_schema_version >= 3 and return_basis == "hfq_adjusted_close"
            ),
        },
    }


def list_validation_archive(frameworks_root: Path = FRAMEWORKS_ROOT) -> List[Dict[str, Any]]:
    """Return the newest artifact for each framework/date/frequency combination.

    Old reruns often wrote several timestamped summaries for the same final
    parameters.  Only the newest one is exposed so users never compare a stale
    result with an identical-looking current definition.
    """
    frameworks_root = Path(frameworks_root)
    selected: Dict[Tuple[str, str, str, str], Tuple[str, Path, Dict[str, Any]]] = {}
    if not frameworks_root.exists():
        return []

    for path in frameworks_root.glob("*/backtest/backtest_summary_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            key = _group_key(path.parent.parent.name, payload)
            candidate = (_timestamp(payload, path), path, payload)
            if key not in selected or candidate[0] > selected[key][0]:
                selected[key] = candidate
        except (OSError, ValueError, TypeError):
            continue

    archives = [_convert(path, frameworks_root, payload) for _, path, payload in selected.values()]
    archives.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return archives
