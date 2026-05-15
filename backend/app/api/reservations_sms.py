"""
Reservations API — SMS template assignment & sending endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone

from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.db.models import Reservation, User, Tenant, ReservationSmsAssignment
from app.factory import get_sms_provider_for_tenant
from app.auth.dependencies import get_current_user
from app.rate_limit import limiter
from app.diag_logger import diag


router = APIRouter(prefix="/api/reservations", tags=["reservations"])


class SmsAssignRequest(BaseModel):
    template_key: str
    assigned_by: str = "manual"
    date: str = ''


@router.post("/{reservation_id}/sms-assign")
async def assign_sms_template(
    reservation_id: int,
    request: SmsAssignRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Assign an SMS template to a reservation"""
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # Check if already assigned
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == request.template_key,
        ReservationSmsAssignment.date == (request.date or ''),
    ).first()
    if existing:
        diag("sms_assignment.duplicate", level="critical",
             reservation_id=reservation_id,
             template_key=request.template_key,
             date=request.date or '',
             existing_sent=(existing.sent_at is not None))
        raise HTTPException(status_code=409, detail="이미 배정된 템플릿입니다")

    from app.services.chip_store import ensure_chip
    assignment = ensure_chip(
        db,
        reservation_id=reservation_id,
        template_key=request.template_key,
        date=request.date or '',
        assigned_by=request.assigned_by,
    )
    db.commit()
    return {"success": True, "template_key": request.template_key}


@router.delete("/{reservation_id}/sms-assign/{template_key}")
async def unassign_sms_template(
    reservation_id: int,
    template_key: str,
    date: str = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an SMS template assignment from a reservation"""
    query = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    )
    if date:
        query = query.filter(ReservationSmsAssignment.date == date)
    assignment = query.first()
    if not assignment:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다")

    # 삭제 대신 excluded로 표시 — sync_sms_tags가 재생성하지 않도록
    assignment.assigned_by = 'excluded'
    assignment.sent_at = None
    assignment.send_status = None
    assignment.send_error = None
    db.commit()
    return {"success": True}


@router.patch("/{reservation_id}/sms-toggle/{template_key}")
async def toggle_sms_sent(
    reservation_id: int,
    template_key: str,
    skip_send: bool = False,
    date: str = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Toggle the sent status of an SMS assignment.

    Args:
        skip_send: If True, mark as sent without actually sending SMS.
        date: Target date (YYYY-MM-DD) for date-specific assignment lookup.
    """
    query = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    )
    if date:
        query = query.filter(ReservationSmsAssignment.date == date)
    assignment = query.first()
    if not assignment:
        # Upsert: 레코드가 없으면 생성 (UI에서 태그가 보이는데 DB에 없는 타이밍 이슈 대응).
        # chip_store.ensure_chip 위임 (PR8 이주).
        from app.services.chip_store import ensure_chip
        assignment = ensure_chip(
            db,
            reservation_id=reservation_id,
            template_key=template_key,
            date=date or '',
            assigned_by='manual',
        )

    if assignment.sent_at:
        assignment.sent_at = None  # Mark as unsent
        assignment.send_status = None
        assignment.send_error = None
        db.commit()
        return {"success": True, "sent_at": None}
    elif skip_send:
        # 발송 없이 상태만 변경
        assignment.sent_at = datetime.now(timezone.utc)
        assignment.send_status = 'sent'
        assignment.send_error = None
        db.commit()
        return {"success": True, "sent_at": assignment.sent_at}
    else:
        # 실제 SMS 발송
        reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
        if not reservation or not reservation.phone:
            raise HTTPException(status_code=400, detail="전화번호가 없습니다")

        from app.services.sms_sender import send_single_sms

        sms_provider = get_sms_provider_for_tenant(tenant)
        try:
            # Look up template buffer for participant_count
            from app.db.models import MessageTemplate
            tpl = db.query(MessageTemplate).filter(MessageTemplate.template_key == template_key).first()
            custom_vars = tpl.get_buffer_vars() if tpl else None

            result = await send_single_sms(
                db=db,
                sms_provider=sms_provider,
                reservation=reservation,
                template_key=template_key,
                created_by=current_user.username,
                date=date,
                custom_vars=custom_vars,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SMS 발송 실패: {e}")

        if result.get("success"):
            assignment.sent_at = datetime.now(timezone.utc)
            assignment.send_status = 'sent'
            assignment.send_error = None
            db.commit()
            return {"success": True, "sent_at": assignment.sent_at}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "SMS 발송 실패"))


class SmsSendByTagRequest(BaseModel):
    template_key: str
    date: str


@router.post("/sms-send-by-tag")
@limiter.limit("10/minute")
async def send_sms_by_tag(
    request: Request,
    sms_data: SmsSendByTagRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Send SMS to all reservations with unsent assignment for a given template_key and date"""
    from app.services.sms_sender import SmsSender

    sms_provider = get_sms_provider_for_tenant(tenant)
    manager = SmsSender(db, sms_provider)
    try:
        result = await manager.send_by_assignment(
            template_key=sms_data.template_key,
            date=sms_data.date,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if result["target_count"] == 0:
        return {"success": True, "sent_count": 0, "message": "No unsent targets found"}

    db.commit()

    return {"success": True, **result}
