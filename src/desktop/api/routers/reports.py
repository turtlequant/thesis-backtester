"""
Report management endpoints.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.desktop.api.services.analyzer import AnalysisManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Will be set by main.py at startup
manager: Optional[AnalysisManager] = None


@router.get("")
async def list_reports():
    """List all saved reports from all strategies' live/ directories."""
    if manager is None:
        raise HTTPException(status_code=500, detail="Manager not initialized")
    return manager.get_all_reports()


@router.get("/{report_id}")
async def get_report(report_id: str):
    """Get a specific report by ID."""
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
