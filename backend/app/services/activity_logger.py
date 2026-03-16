"""활동 로그 기록 헬퍼"""
import json
from sqlalchemy.orm import Session
from app.db.models import ActivityLog


def log_activity(
    db: Session,
    type: str,
    title: str,
    detail: dict = None,
    status: str = "success",
    target_count: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    created_by: str = "system",
) -> ActivityLog:
    log = ActivityLog(
        activity_type=type,
        title=title,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
        status=status,
        target_count=target_count,
        success_count=success_count,
        failed_count=failed_count,
        created_by=created_by,
    )
    db.add(log)
    db.flush()
    return log
