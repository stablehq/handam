"""활동 로그 기록 헬퍼"""
import json
from sqlalchemy.orm import Session
from app.db.models import ActivityLog, Tenant
from app.db.tenant_context import get_session_tenant_id
from app.diag_logger import diag


def _get_tenant_slug(db: Session) -> str | None:
    """현재 테넌트의 slug를 반환 (캐시 없이 간단 조회)."""
    tid = get_session_tenant_id(db)
    if tid is None:
        return None
    tenant = db.get(Tenant, tid)
    return tenant.slug.upper() if tenant else None


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
    # title에 [TENANT] prefix가 없으면 자동 추가
    slug = _get_tenant_slug(db)
    if slug and not title.startswith(f"[{slug}]"):
        title = f"[{slug}] {title}"

    diag(
        "activity_log.created",
        level="verbose",
        type=type,
        target_count=target_count,
        success_count=success_count,
        failed_count=failed_count,
        status=status,
        created_by=created_by,
    )

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
