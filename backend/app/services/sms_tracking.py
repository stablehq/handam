"""
SMS 발송 추적 공통 헬퍼
ReservationSmsAssignment upsert를 한 곳에서 관리
"""
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.db.models import Reservation, ReservationSmsAssignment
from app.diag_logger import diag
import logging

logger = logging.getLogger(__name__)


def _resolve_reservation_tenant(db: Session, reservation_id: int) -> int:
    """Lookup reservation.tenant_id without trusting the implicit before_compile
    filter — necessary because callers may run under a leaked bypass context.

    옵션 C 강화 (Phase 6):
        - 임시 bypass 를 위해 별도 session_bypass() 사용 (트랜잭션 무관 — read-only).
        - session.info['tenant_id'] 와 실제 reservation.tenant_id 가 다르면
          critical diag 발화 — silent cross-tenant 시도 즉시 가시화.

    Returns the tenant_id; raises if the reservation does not exist.
    """
    from app.db.database import session_bypass
    from app.diag_logger import diag

    bypass_db = session_bypass()
    try:
        tid = (
            bypass_db.query(Reservation.tenant_id)
            .filter(Reservation.id == reservation_id)
            .scalar()
        )
    finally:
        bypass_db.close()
    if tid is None:
        raise RuntimeError(f"reservation {reservation_id} not found for sms tracking")

    # 옵션 C: session.info 의 tenant 와 reservation 의 실제 tenant 비교
    session_tid = db.info.get('tenant_id')
    if session_tid is not None and session_tid != tid:
        diag(
            "sms_tracking.cross_tenant_reservation",
            level="critical",
            session_tid=session_tid,
            reservation_id=reservation_id,
            reservation_tid=tid,
        )

    return tid


def record_sms_sent(
    db: Session,
    reservation_id: int,
    template_key: str,
    sms_type_label: str,
    assigned_by: str = "auto",
    date: str = "",
) -> None:
    """
    SMS 발송 성공 기록을 ReservationSmsAssignment에 upsert.
    """
    diag(
        "sms.sent_recorded",
        level="verbose",
        res_id=reservation_id,
        template_key=template_key,
        date=date,
        assigned_by=assigned_by,
    )
    res_tid = _resolve_reservation_tenant(db, reservation_id)
    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.tenant_id == res_tid,
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )

    if existing:
        existing.sent_at = datetime.now(timezone.utc)
        existing.send_status = 'sent'
        existing.send_error = None
    else:
        db.add(ReservationSmsAssignment(
            tenant_id=res_tid,
            reservation_id=reservation_id,
            template_key=template_key,
            assigned_by=assigned_by,
            sent_at=datetime.now(timezone.utc),
            send_status='sent',
            date=date,
        ))


def record_sms_failed(
    db: Session,
    reservation_id: int,
    template_key: str,
    error: str,
    date: str = "",
) -> None:
    """
    SMS 발송 실패 기록. 칩에 send_status='failed'와 에러 메시지를 기록.
    다음 스케줄 실행 시 재시도하지 않음.
    """
    diag(
        "sms.failed_recorded",
        level="critical",
        res_id=reservation_id,
        template_key=template_key,
        date=date,
        error=(error or "")[:100],
    )
    res_tid = _resolve_reservation_tenant(db, reservation_id)
    existing = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.tenant_id == res_tid,
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
        )
        .first()
    )

    if existing:
        existing.send_status = 'failed'
        existing.send_error = (error or 'unknown')[:500]
    else:
        db.add(ReservationSmsAssignment(
            tenant_id=res_tid,
            reservation_id=reservation_id,
            template_key=template_key,
            assigned_by='auto',
            send_status='failed',
            send_error=(error or 'unknown')[:500],
            date=date,
        ))
