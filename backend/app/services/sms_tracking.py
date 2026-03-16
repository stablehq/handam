"""
SMS 발송 추적 공통 헬퍼
ReservationSmsAssignment upsert를 한 곳에서 관리
"""
from sqlalchemy.orm import Session
from datetime import datetime
from app.db.models import ReservationSmsAssignment
import logging

logger = logging.getLogger(__name__)


def record_sms_sent(
    db: Session,
    reservation_id: int,
    template_key: str,
    sms_type_label: str,
    assigned_by: str = "auto",
) -> None:
    """
    SMS 발송 기록을 ReservationSmsAssignment에 upsert.

    Args:
        db: DB 세션
        reservation_id: 예약 ID
        template_key: 템플릿 키 (예: 'room_guide', 'party_guide')
        sms_type_label: 레거시 파라미터 (무시됨, 호출부 호환용으로 유지)
        assigned_by: 'auto' 또는 'schedule'
    """
    # ReservationSmsAssignment upsert
    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
        )
        .first()
    )

    if existing:
        existing.sent_at = datetime.now()
    else:
        db.add(ReservationSmsAssignment(
            reservation_id=reservation_id,
            template_key=template_key,
            assigned_by=assigned_by,
            sent_at=datetime.now(),
        ))
