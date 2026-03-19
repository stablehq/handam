"""
Activity Logs API endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

from app.api.deps import get_tenant_scoped_db
from app.db.models import ActivityLog, User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/activity-logs", tags=["activity-logs"])


@router.get("")
def get_activity_logs(
    type: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get activity logs with filtering and pagination"""
    query = db.query(ActivityLog)

    if type:
        query = query.filter(ActivityLog.activity_type == type)
    if status:
        query = query.filter(ActivityLog.status == status)
    if date:
        # Filter by date (YYYY-MM-DD)
        start = datetime.strptime(date, "%Y-%m-%d")
        end = start + timedelta(days=1)
        query = query.filter(ActivityLog.created_at >= start, ActivityLog.created_at < end)

    logs = query.order_by(ActivityLog.created_at.desc()).offset(skip).limit(limit).all()

    return [
        {
            "id": log.id,
            "type": log.activity_type,
            "title": log.title,
            "detail": log.detail,
            "status": log.status,
            "target_count": log.target_count,
            "success_count": log.success_count,
            "failed_count": log.failed_count,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "created_by": log.created_by,
        }
        for log in logs
    ]


@router.get("/stats")
def get_activity_stats(
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get today's activity statistics by type"""
    today_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    rows = (
        db.query(
            ActivityLog.activity_type,
            func.count(ActivityLog.id).label("count"),
            func.sum(ActivityLog.target_count).label("total_targets"),
            func.sum(ActivityLog.success_count).label("total_success"),
            func.sum(ActivityLog.failed_count).label("total_failed"),
        )
        .filter(ActivityLog.created_at >= today_start, ActivityLog.created_at < today_end)
        .group_by(ActivityLog.activity_type)
        .all()
    )

    stats = {}
    for row in rows:
        stats[row.activity_type] = {
            "count": row.count,
            "total_targets": row.total_targets or 0,
            "total_success": row.total_success or 0,
            "total_failed": row.total_failed or 0,
        }

    return {
        "date": today_start.strftime("%Y-%m-%d"),
        "stats": stats,
        "total_activities": sum(s["count"] for s in stats.values()),
    }
