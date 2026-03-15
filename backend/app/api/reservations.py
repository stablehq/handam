"""
Reservations API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel, field_validator
from typing import List, Optional, Union
from app.db.database import get_db
from app.db.models import Reservation, ReservationStatus, User, ReservationSmsAssignment
from app.factory import get_reservation_provider, get_sms_provider
from app.auth.dependencies import get_current_user
from app.templates.renderer import TemplateRenderer
from app.services import room_assignment
from datetime import datetime
import logging

router = APIRouter(prefix="/api/reservations", tags=["reservations"])
logger = logging.getLogger(__name__)


class ReservationCreate(BaseModel):
    customer_name: str
    phone: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    status: str = "pending"
    notes: Optional[str] = None
    gender: Optional[str] = None
    tags: Optional[Union[str, List[str]]] = None  # Accepts both string and array
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_participants: Optional[int] = 1
    party_type: Optional[str] = None
    source: str = "manual"
    room_info: Optional[str] = None  # Original reservation room type

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
    date: Optional[str] = None
    time: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    gender: Optional[str] = None
    tags: Optional[Union[str, List[str]]] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    party_participants: Optional[int] = None
    party_type: Optional[str] = None
    room_info: Optional[str] = None  # Original reservation room type
    sent_sms_types: Optional[str] = None  # "객후,파티안내,객실안내"

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
    date: str
    time: str
    status: str
    notes: Optional[str] = None
    source: str
    room_number: Optional[str] = None
    room_password: Optional[str] = None
    room_info: Optional[str] = None
    gender: Optional[str] = None
    male_count: Optional[int] = None
    female_count: Optional[int] = None
    tags: Optional[str] = None
    party_participants: Optional[int] = None
    party_type: Optional[str] = None
    room_sms_sent: bool = False
    party_sms_sent: bool = False
    sent_sms_types: Optional[str] = None  # "객후,파티안내,객실안내"
    end_date: Optional[str] = None
    biz_item_name: Optional[str] = None
    booking_count: Optional[int] = 1
    booking_options: Optional[str] = None
    custom_form_input: Optional[str] = None
    total_price: Optional[int] = None
    confirmed_datetime: Optional[str] = None
    cancelled_datetime: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sms_assignments: List[SmsAssignmentResponse] = []

    class Config:
        from_attributes = True


def _to_response(res: Reservation, override_room: Optional[str] = None, override_password: Optional[str] = None, db: Session = None) -> ReservationResponse:
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
        date=res.date,
        time=res.time,
        status=res.status.value,
        notes=res.notes,
        source=res.source,
        room_number=override_room if override_room is not None else res.room_number,
        room_password=override_password if override_password is not None else res.room_password,
        room_info=res.room_info,
        gender=res.gender,
        male_count=res.male_count,
        female_count=res.female_count,
        tags=res.tags,
        party_participants=res.party_participants,
        party_type=res.party_type,
        room_sms_sent=res.room_sms_sent or False,
        party_sms_sent=res.party_sms_sent or False,
        sent_sms_types=res.sent_sms_types,
        end_date=res.end_date,
        biz_item_name=res.biz_item_name,
        booking_count=res.booking_count,
        booking_options=res.booking_options,
        custom_form_input=res.custom_form_input,
        total_price=res.total_price,
        confirmed_datetime=res.confirmed_datetime,
        cancelled_datetime=res.cancelled_datetime,
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get reservations with pagination and filtering"""
    query = db.query(Reservation)

    if status:
        query = query.filter(Reservation.status == status)

    if date:
        # check-in <= date < check-out (end_date)
        # If end_date is null, fall back to exact date match
        query = query.filter(
            or_(
                and_(
                    Reservation.date <= date,
                    Reservation.end_date > date,
                ),
                and_(
                    Reservation.date == date,
                    Reservation.end_date.is_(None),
                ),
            )
        )

    # Order by most recent confirmation or cancellation datetime
    from sqlalchemy.orm import selectinload
    reservations = query.options(
        selectinload(Reservation.sms_assignments)
    ).order_by(
        Reservation.confirmed_datetime.desc().nullslast(),
    ).offset(skip).limit(limit).all()

    # 항상 RoomAssignment에서 객실 정보 조회 (소스 오브 트루스)
    results = []
    for res in reservations:
        lookup_date = date or res.date
        override_room, override_password = room_assignment.get_room_for_date(db, res.id, lookup_date)
        results.append(_to_response(res, override_room=override_room, override_password=override_password, db=db))
    return results


@router.post("", response_model=ReservationResponse)
async def create_reservation(reservation: ReservationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a new reservation"""
    # Convert status string to enum
    try:
        status_enum = ReservationStatus(reservation.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")

    db_reservation = Reservation(
        customer_name=reservation.customer_name,
        phone=reservation.phone,
        date=reservation.date,
        time=reservation.time,
        status=status_enum,
        notes=reservation.notes,
        source=reservation.source,
        gender=reservation.gender,
        male_count=reservation.male_count,
        female_count=reservation.female_count,
        tags=reservation.tags,  # Already converted by validator
        party_participants=reservation.party_participants,
        party_type=reservation.party_type,
        room_info=reservation.room_info,  # Original reservation room type
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
        raise HTTPException(status_code=404, detail="Reservation not found")

    update_data = reservation.dict(exclude_unset=True)

    # Convert status string to enum if provided
    if "status" in update_data:
        try:
            update_data["status"] = ReservationStatus(update_data["status"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status")

    for field, value in update_data.items():
        setattr(db_reservation, field, value)

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.delete("/{reservation_id}")
async def delete_reservation(reservation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    db.delete(db_reservation)
    db.commit()
    return {"status": "success", "message": "Reservation deleted"}


@router.put("/{reservation_id}/room", response_model=ReservationResponse)
async def assign_room(
    reservation_id: int, request: RoomAssignRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Assign or unassign a room to a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    room_number = request.room_number
    req_date = request.date
    apply_subsequent = request.apply_subsequent

    if room_number is None:
        # Unassign room
        end_date = db_reservation.end_date if (req_date and apply_subsequent) else None
        room_assignment.unassign_room(
            db,
            reservation_id,
            req_date,
            end_date,
        )
    else:
        # Manual assignment from UI
        from_date = req_date or db_reservation.date
        end_date = db_reservation.end_date if apply_subsequent else None
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
async def sync_from_naver(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Sync reservations from Naver Smart Place API"""
    from app.api.reservations_sync import sync_naver_to_db

    reservation_provider = get_reservation_provider()
    result = await sync_naver_to_db(reservation_provider, db)
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
        raise HTTPException(status_code=404, detail="Reservation not found")

    # Check if already assigned
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == request.template_key,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Template already assigned")

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
        raise HTTPException(status_code=404, detail="Assignment not found")

    db.delete(assignment)
    db.commit()
    return {"success": True}


@router.patch("/{reservation_id}/sms-toggle/{template_key}")
async def toggle_sms_sent(
    reservation_id: int,
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle the sent status of an SMS assignment"""
    assignment = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if assignment.sent_at:
        assignment.sent_at = None  # Mark as unsent
    else:
        assignment.sent_at = datetime.utcnow()  # Mark as sent

    db.commit()
    return {"success": True, "sent_at": assignment.sent_at}


class SmsSendByTagRequest(BaseModel):
    template_key: str
    date: str


@router.post("/sms-send-by-tag")
async def send_sms_by_tag(
    request: SmsSendByTagRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send SMS to all reservations with unsent assignment for a given template_key and date"""
    from app.db.models import MessageTemplate, CampaignLog
    from sqlalchemy.orm import selectinload

    template = db.query(MessageTemplate).filter(
        MessageTemplate.key == request.template_key,
        MessageTemplate.active == True,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Find all reservations for the date with unsent assignments for this template
    assignments = db.query(ReservationSmsAssignment).join(
        Reservation, ReservationSmsAssignment.reservation_id == Reservation.id
    ).filter(
        ReservationSmsAssignment.template_key == request.template_key,
        ReservationSmsAssignment.sent_at.is_(None),
        Reservation.date == request.date,
        Reservation.status == 'confirmed',
    ).all()

    if not assignments:
        return {"success": True, "sent_count": 0, "message": "No unsent targets found"}

    sms_provider = get_sms_provider()
    renderer = TemplateRenderer(db)
    sent_count = 0
    failed_count = 0

    # Campaign log
    campaign_log = CampaignLog(
        campaign_type=f"tag_send_{request.template_key}",
        target_count=len(assignments),
        sent_count=0,
        failed_count=0,
    )
    db.add(campaign_log)
    db.commit()

    for assignment in assignments:
        reservation = db.query(Reservation).filter(Reservation.id == assignment.reservation_id).first()
        if not reservation:
            failed_count += 1
            continue
        try:
            context = {
                "customer_name": reservation.customer_name,
                "phone": reservation.phone,
                "date": reservation.date,
                "time": reservation.time or "",
                "room_number": reservation.room_number or "",
                "room_password": reservation.room_password or "",
                "room_info": reservation.room_info or "",
                "party_type": reservation.party_type or "",
                "notes": reservation.notes or "",
            }
            message_content = renderer.render(request.template_key, context)
            result = await sms_provider.send_sms(
                to=reservation.phone,
                message=message_content,
            )
            if result.get("success"):
                sent_count += 1
                assignment.sent_at = datetime.utcnow()
                db.commit()
            else:
                failed_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to send SMS to reservation #{reservation.id}: {e}")

    campaign_log.sent_count = sent_count
    campaign_log.failed_count = failed_count
    campaign_log.completed_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "target_count": len(assignments),
    }
