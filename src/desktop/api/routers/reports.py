"""
Report management endpoints.
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.desktop.api.services.analyzer import AnalysisManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Will be set by main.py at startup
manager: Optional[AnalysisManager] = None


@router.get("")
async def list_reports(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query: str = "",
    framework: str = "",
    recommendation: str = "",
    origin: str = "",
    start_date: str = "",
    end_date: str = "",
    refresh: bool = False,
):
    """List reports through the reconciled SQLite artifact index."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Manager not initialized")
    return await asyncio.to_thread(
        manager.get_reports_page,
        page=page,
        page_size=page_size,
        query=query,
        framework=framework,
        recommendation=recommendation,
        origin=origin,
        start_date=start_date,
        end_date=end_date,
        refresh=refresh,
    )


@router.get("/{report_id}")
async def get_report(report_id: str):
    """Get a report, readable Markdown and structured chapter evidence."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Manager not initialized")

    report = manager.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    return report


@router.delete("/{report_id}")
async def delete_report(report_id: str):
    """Delete a report by ID."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Manager not initialized")

    success = manager.delete_report(report_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Report not found or delete failed: {report_id}")
    return {"message": "Report deleted", "id": report_id}
