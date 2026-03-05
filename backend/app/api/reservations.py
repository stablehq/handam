"""
Reservations API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import List, Optional, Union
from app.db.database import get_db
from app.db.models import Reservation, ReservationStatus, User
from app.factory import get_reservation_provider, get_storage_provider
from app.auth.dependencies import get_current_user
from app.templates.renderer import TemplateRenderer
from datetime import datetime
import logging

router = APIRouter(prefix="/api/reservations", tags=["reservations"])
logger = logging.getLogger(__name__)

ROOM_INFO_MAP = {
    "A101": "더블룸", "A102": "트윈룸", "A103": "패밀리룸",
    "A104": "디럭스룸", "A105": "스탠다드룸",
    "B201": "더블룸", "B202": "트윈룸", "B203": "패밀리룸",
    "B204": "디럭스룸", "B205": "스탠다드룸",
}


class ReservationCreate(BaseModel):
    customer_name: str
    phone: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    status: str = "pending"
    notes: Optional[str] = None
    gender: Optional[str] = None
    tags: Optional[Union[str, List[str]]] = None  # Accepts both string and array
    party_participants: Optional[int] = 1
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
    party_participants: Optional[int] = None
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


class ReservationResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    customer_name: str
    phone: str
    date: str
    time: str
    status: str
    notes: Optional[str] = None
    source: str
    room_number: Optional[str] = None
    room_password: Optional[str] = None
    room_info: Optional[str] = None
    gender: Optional[str] = None
    tags: Optional[str] = None
    party_participants: Optional[int] = None
    room_sms_sent: bool = False
    party_sms_sent: bool = False
    sent_sms_types: Optional[str] = None  # "객후,파티안내,객실안내"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _to_response(res: Reservation) -> ReservationResponse:
    return ReservationResponse(
        id=res.id,
        external_id=res.external_id,
        customer_name=res.customer_name,
        phone=res.phone,
        date=res.date,
        time=res.time,
        status=res.status.value,
        notes=res.notes,
        source=res.source,
        room_number=res.room_number,
        room_password=res.room_password,
        room_info=res.room_info,
        gender=res.gender,
        tags=res.tags,
        party_participants=res.party_participants,
        room_sms_sent=res.room_sms_sent or False,
        party_sms_sent=res.party_sms_sent or False,
        sent_sms_types=res.sent_sms_types,
        created_at=res.created_at,
        updated_at=res.updated_at,
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
        query = query.filter(Reservation.date == date)

    reservations = query.order_by(Reservation.created_at.desc()).offset(skip).limit(limit).all()

    return [_to_response(res) for res in reservations]


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
        tags=reservation.tags,  # Already converted by validator
        party_participants=reservation.party_participants,
        room_info=reservation.room_info,  # Original reservation room type
    )
    db.add(db_reservation)
    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation)


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

    return _to_response(db_reservation)


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

    if room_number is None:
        # Unassign room (keep room_info to preserve original reservation)
        db_reservation.room_number = None
        db_reservation.room_password = None
    else:
        # Check for duplicate assignment on the same date
        conflict = (
            db.query(Reservation)
            .filter(
                Reservation.date == db_reservation.date,
                Reservation.room_number == room_number,
                Reservation.id != reservation_id,
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"객실 {room_number}은(는) 이미 {conflict.customer_name}에게 배정되어 있습니다.",
            )

        db_reservation.room_number = room_number
        db_reservation.room_password = TemplateRenderer.generate_room_password(room_number)
        # Don't update room_info here - it should preserve the original reservation

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation)


@router.post("/sync/naver")
async def sync_from_naver(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Sync reservations from Naver (mock: reads from JSON file)"""
    logger.info("Starting Naver reservation sync...")

    reservation_provider = get_reservation_provider()
    reservations = await reservation_provider.sync_reservations()

    added_count = 0
    for res_data in reservations:
        # Check if reservation already exists
        existing = (
            db.query(Reservation)
            .filter(Reservation.external_id == res_data.get("external_id"))
            .first()
        )

        if not existing:
            # Convert status string to enum
            try:
                status_enum = ReservationStatus(res_data.get("status", "pending"))
            except ValueError:
                status_enum = ReservationStatus.PENDING

            new_res = Reservation(
                external_id=res_data.get("external_id"),
                customer_name=res_data.get("customer_name"),
                phone=res_data.get("phone"),
                date=res_data.get("date"),
                time=res_data.get("time"),
                status=status_enum,
                notes=res_data.get("notes"),
                source="naver",
            )
            db.add(new_res)
            added_count += 1

    db.commit()
    logger.info(f"Naver sync completed: {added_count} new reservations added")

    return {
        "status": "success",
        "synced": len(reservations),
        "added": added_count,
        "message": f"Synced {len(reservations)} reservations from Naver (mock mode)",
    }


@router.post("/sync/sheets")
async def sync_to_google_sheets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Export reservations to Google Sheets (mock: writes to CSV file)"""
    logger.info("Starting Google Sheets sync...")

    # Get all reservations
    reservations = db.query(Reservation).all()

    # Convert to dict format
    data = [
        {
            "id": res.id,
            "external_id": res.external_id or "",
            "customer_name": res.customer_name,
            "phone": res.phone,
            "date": res.date,
            "time": res.time,
            "status": res.status.value,
            "notes": res.notes or "",
            "source": res.source,
            "created_at": res.created_at.isoformat(),
            "updated_at": res.updated_at.isoformat(),
        }
        for res in reservations
    ]

    storage_provider = get_storage_provider()
    success = await storage_provider.sync_to_storage(data, "reservations")

    if success:
        return {
            "status": "success",
            "exported": len(data),
            "message": f"Exported {len(data)} reservations to Google Sheets (mock mode)",
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to sync to Google Sheets")
