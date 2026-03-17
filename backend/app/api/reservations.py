"""
Reservations API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel, field_validator
from typing import List, Optional, Union
from app.db.database import get_db
from app.db.models import Reservation, ReservationStatus, User, ReservationSmsAssignment, RoomAssignment
from app.factory import get_reservation_provider, get_sms_provider
from app.auth.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import room_assignment
from app.services.activity_logger import log_activity
from app.api.shared_schemas import ActionResponse
from datetime import datetime
import logging

router = APIRouter(prefix="/api/reservations", tags=["reservations"])
logger = logging.getLogger(__name__)


class ReservationCreate(BaseModel):
    customer_name: str
    phone: str
    check_in_date: str  # YYYY-MM-DD
    check_in_time: str  # HH:MM
    status: str = "pending"
    notes: Optional[str] = None
    gender: Optional[str] = None
    tags: Optional[Union[str, List[str]]] = None  # Accepts both string and array
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_size: Optional[int] = 1
    party_type: Optional[str] = None
    booking_source: str = "manual"
    naver_room_type: Optional[str] = None  # Original reservation room type

    @field_validator('tags')
    @classmethod
    def convert_tags_to_string(cls, v):
        """Convert tags array to comma-separated string"""
        if v is None:
            return None
        if isinstance(v, list):
            return ",".join(v)
        return v


class ReservationUpdate(BaseModel):
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    check_in_date: Optional[str] = None
    check_in_time: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    gender: Optional[str] = None
    tags: Optional[Union[str, List[str]]] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_size: Optional[int] = None
    party_type: Optional[str] = None
    naver_room_type: Optional[str] = None  # Original reservation room type

    @field_validator('tags')
    @classmethod
    def convert_tags_to_string(cls, v):
        """Convert tags array to comma-separated string"""
        if v is None:
            return None
        if isinstance(v, list):
            return ",".join(v)
        return v


class RoomAssignRequest(BaseModel):
    room_number: Optional[str] = None
    date: Optional[str] = None
    apply_subsequent: bool = True  # Apply to subsequent dates for multi-night stays


class SmsAssignRequest(BaseModel):
    template_key: str
    assigned_by: str = "manual"


class SmsAssignmentResponse(BaseModel):
    template_key: str
    assigned_at: datetime
    sent_at: Optional[datetime] = None
    assigned_by: str = "auto"

    class Config:
        from_attributes = True


class ReservationResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    customer_name: str
    phone: str
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    check_in_date: str
    check_in_time: str
    status: str
    notes: Optional[str] = None
    booking_source: str
    room_number: Optional[str] = None
    room_password: Optional[str] = None
    room_assigned_by: Optional[str] = None
    naver_room_type: Optional[str] = None
    gender: Optional[str] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    tags: Optional[str] = None
    party_size: Optional[int] = None
    party_type: Optional[str] = None
    check_out_date: Optional[str] = None
    biz_item_name: Optional[str] = None
    booking_count: Optional[int] = 1
    booking_options: Optional[str] = None
    special_requests: Optional[str] = None
    total_price: Optional[int] = None
    confirmed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sms_assignments: List[SmsAssignmentResponse] = []

    class Config:
        from_attributes = True


def _to_response(res: Reservation, override_room: Optional[str] = None, override_password: Optional[str] = None, override_assigned_by: Optional[str] = None, db: Session = None) -> ReservationResponse:
    assignments = []
    if db is not None and hasattr(res, 'sms_assignments'):
        assignments = [
            SmsAssignmentResponse(
                template_key=a.template_key,
                assigned_at=a.assigned_at,
                sent_at=a.sent_at,
                assigned_by=a.assigned_by,
            )
            for a in res.sms_assignments
        ]
    return ReservationResponse(
        id=res.id,
        external_id=res.external_id,
        customer_name=res.customer_name,
        phone=res.phone,
        visitor_name=res.visitor_name,
        visitor_phone=res.visitor_phone,
        check_in_date=res.check_in_date,
        check_in_time=res.check_in_time,
        status=res.status.value,
        notes=res.notes,
        booking_source=res.booking_source,
        room_number=override_room if override_room is not None else res.room_number,
        room_password=override_password if override_password is not None else res.room_password,
        room_assigned_by=override_assigned_by,
        naver_room_type=res.naver_room_type,
        gender=res.gender,
        male_count=res.male_count,
        female_count=res.female_count,
        tags=res.tags,
        party_size=res.party_size,
        party_type=res.party_type,
        check_out_date=res.check_out_date,
        biz_item_name=res.biz_item_name,
        booking_count=res.booking_count,
        booking_options=res.booking_options,
        special_requests=res.special_requests,
        total_price=res.total_price,
        confirmed_at=res.confirmed_at,
        cancelled_at=res.cancelled_at,
        created_at=res.created_at,
        updated_at=res.updated_at,
        sms_assignments=assignments,
    )


@router.get("", response_model=List[ReservationResponse])
async def get_reservations(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    date: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get reservations with pagination and filtering"""
    query = db.query(Reservation)

    if status:
        query = query.filter(Reservation.status == status)

    if search:
        query = query.filter(
            or_(
                Reservation.customer_name.contains(search),
                Reservation.phone.contains(search),
            )
        )

    if source:
        query = query.filter(Reservation.booking_source == source)

    if date:
        # check-in <= date < check-out (check_out_date)
        # If check_out_date is null, fall back to exact date match
        query = query.filter(
            or_(
                and_(
                    Reservation.check_in_date <= date,
                    Reservation.check_out_date > date,
                ),
                and_(
                    Reservation.check_in_date == date,
                    Reservation.check_out_date.is_(None),
                ),
            )
        )

    # Order by most recent confirmation or cancellation datetime
    from sqlalchemy.orm import selectinload
    reservations = query.options(
        selectinload(Reservation.sms_assignments)
    ).order_by(
        Reservation.confirmed_at.desc().nullslast(),
    ).offset(skip).limit(limit).all()

    # 항상 RoomAssignment에서 객실 정보 조회 (소스 오브 트루스) — 배치 조회로 N+1 제거
    res_ids = [r.id for r in reservations]
    if res_ids:
        # date 파라미터가 있으면 해당 날짜로 일괄 조회, 없으면 각 예약의 date를 키로 사용
        if date:
            room_assignments = (
                db.query(RoomAssignment)
                .filter(
                    RoomAssignment.reservation_id.in_(res_ids),
                    RoomAssignment.date == date,
                )
                .all()
            )
            room_map = {ra.reservation_id: (ra.room_number, ra.room_password, ra.assigned_by) for ra in room_assignments}
        else:
            # date 없음: 각 예약의 check-in date 기준으로 조회
            # (reservation_id, date) 쌍을 한 번에 가져온 뒤 매핑
            res_date_map = {r.id: r.check_in_date for r in reservations}
            room_assignments = (
                db.query(RoomAssignment)
                .filter(RoomAssignment.reservation_id.in_(res_ids))
                .all()
            )
            room_map = {}
            for ra in room_assignments:
                lookup = res_date_map.get(ra.reservation_id)
                if ra.date == lookup:
                    room_map[ra.reservation_id] = (ra.room_number, ra.room_password, ra.assigned_by)
    else:
        room_map = {}

    results = []
    for res in reservations:
        override_room, override_password, override_assigned_by = room_map.get(res.id, (None, None, None))
        results.append(_to_response(res, override_room=override_room, override_password=override_password, override_assigned_by=override_assigned_by, db=db))
    return results


@router.post("", response_model=ReservationResponse)
async def create_reservation(reservation: ReservationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a new reservation"""
    # Convert status string to enum
    try:
        status_enum = ReservationStatus(reservation.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")

    db_reservation = Reservation(
        customer_name=reservation.customer_name,
        phone=reservation.phone,
        check_in_date=reservation.check_in_date,
        check_in_time=reservation.check_in_time,
        status=status_enum,
        notes=reservation.notes,
        booking_source=reservation.booking_source,
        gender=reservation.gender,
        male_count=reservation.male_count,
        female_count=reservation.female_count,
        tags=reservation.tags,  # Already converted by validator
        party_size=reservation.party_size,
        party_type=reservation.party_type,
        naver_room_type=reservation.naver_room_type,  # Original reservation room type
    )
    db.add(db_reservation)
    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.put("/{reservation_id}", response_model=ReservationResponse)
async def update_reservation(
    reservation_id: int, reservation: ReservationUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Update a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    update_data = reservation.dict(exclude_unset=True)

    # Convert status string to enum if provided
    if "status" in update_data:
        try:
            update_data["status"] = ReservationStatus(update_data["status"])
        except ValueError:
            raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")

    for field, value in update_data.items():
        setattr(db_reservation, field, value)

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.delete("/{reservation_id}", response_model=ActionResponse)
async def delete_reservation(reservation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    db.delete(db_reservation)
    db.commit()
    return {"success": True, "message": "예약이 삭제되었습니다"}


@router.put("/{reservation_id}/room", response_model=ReservationResponse)
async def assign_room(
    reservation_id: int, request: RoomAssignRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Assign or unassign a room to a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    room_number = request.room_number
    req_date = request.date
    apply_subsequent = request.apply_subsequent

    if room_number is None:
        # Unassign room
        end_date = db_reservation.check_out_date if (req_date and apply_subsequent) else None
        room_assignment.unassign_room(
            db,
            reservation_id,
            req_date,
            end_date,
        )
    else:
        # Manual assignment from UI
        from_date = req_date or db_reservation.check_in_date
        end_date = db_reservation.check_out_date if apply_subsequent else None
        room_assignment.assign_room(
            db,
            reservation_id,
            room_number,
            from_date,
            end_date,
            assigned_by="manual",
        )

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.post("/sync/naver")
@limiter.limit("5/minute")
async def sync_from_naver(request: Request, from_date: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Sync reservations from Naver Smart Place API.

    Args:
        from_date: Optional start date (YYYY-MM-DD) for historical sync.
    """
    from app.api.reservations_sync import sync_naver_to_db

    reservation_provider = get_reservation_provider()
    result = await sync_naver_to_db(reservation_provider, db, from_date=from_date)

    log_activity(
        db,
        type="naver_sync",
        title="네이버 예약 동기화",
        detail=result,
        target_count=result.get("total", 0),
        success_count=result.get("synced", 0),
        created_by=current_user.username,
    )
    db.commit()

    return result



@router.post("/{reservation_id}/sms-assign")
async def assign_sms_template(
    reservation_id: int,
    request: SmsAssignRequest,
    db: Session = Depends(get_db),
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
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 배정된 템플릿입니다")

    assignment = ReservationSmsAssignment(
        reservation_id=reservation_id,
        template_key=request.template_key,
        assigned_by=request.assigned_by,
    )
    db.add(assignment)
    db.commit()
    return {"success": True, "template_key": request.template_key}


@router.delete("/{reservation_id}/sms-assign/{template_key}")
async def unassign_sms_template(
    reservation_id: int,
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an SMS template assignment from a reservation"""
    assignment = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다")

    db.delete(assignment)
    db.commit()
    return {"success": True}


@router.patch("/{reservation_id}/sms-toggle/{template_key}")
async def toggle_sms_sent(
    reservation_id: int,
    template_key: str,
    skip_send: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle the sent status of an SMS assignment.

    Args:
        skip_send: If True, mark as sent without actually sending SMS.
    """
    assignment = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다")

    if assignment.sent_at:
        assignment.sent_at = None  # Mark as unsent
        db.commit()
        return {"success": True, "sent_at": None}
    elif skip_send:
        # 발송 없이 상태만 변경
        assignment.sent_at = datetime.now()
        db.commit()
        return {"success": True, "sent_at": assignment.sent_at}
    else:
        # 실제 SMS 발송
        reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
        if not reservation or not reservation.phone:
            raise HTTPException(status_code=400, detail="전화번호가 없습니다")

        from app.services.sms_sender import send_single_sms

        sms_provider = get_sms_provider()
        try:
            result = await send_single_sms(
                db=db,
                sms_provider=sms_provider,
                reservation=reservation,
                template_key=template_key,
                created_by=current_user.username,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"SMS 발송 실패: {e}")

        if result.get("success"):
            assignment.sent_at = datetime.now()
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send SMS to all reservations with unsent assignment for a given template_key and date"""
    from app.services.sms_sender import SmsSender

    sms_provider = get_sms_provider()
    manager = SmsSender(db, sms_provider)
    try:
        result = await manager.send_by_assignment(
            template_key=sms_data.template_key,
            date=sms_data.date,
            sms_provider=sms_provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if result["target_count"] == 0:
        return {"success": True, "sent_count": 0, "message": "No unsent targets found"}

    log_activity(
        db,
        type="sms_manual",
        title=f"수동 SMS 발송 ({sms_data.template_key})",
        target_count=result["target_count"],
        success_count=result.get("sent_count", 0),
        failed_count=result.get("failed_count", 0),
        created_by=current_user.username,
    )
    db.commit()

    return {"success": True, **result}
