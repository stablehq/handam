"""
Rooms API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.db.database import get_db
from app.db.models import Room
from datetime import datetime
import logging

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
logger = logging.getLogger(__name__)


class RoomCreate(BaseModel):
    room_number: str
    room_type: str
    base_capacity: int = 2
    max_capacity: int = 4
    is_active: bool = True
    sort_order: int = 0


class RoomUpdate(BaseModel):
    room_number: Optional[str] = None
    room_type: Optional[str] = None
    base_capacity: Optional[int] = None
    max_capacity: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class RoomResponse(BaseModel):
    id: int
    room_number: str
    room_type: str
    base_capacity: int
    max_capacity: int
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[RoomResponse])
async def get_rooms(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    """Get all rooms"""
    query = db.query(Room)

    if not include_inactive:
        query = query.filter(Room.is_active == True)

    rooms = query.order_by(Room.sort_order).all()
    return rooms


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, db: Session = Depends(get_db)):
    """Get a single room by ID"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.post("", response_model=RoomResponse)
async def create_room(room: RoomCreate, db: Session = Depends(get_db)):
    """Create a new room (duplicates allowed)"""
    db_room = Room(
        room_number=room.room_number,
        room_type=room.room_type,
        base_capacity=room.base_capacity,
        max_capacity=room.max_capacity,
        is_active=room.is_active,
        sort_order=room.sort_order,
    )
    db.add(db_room)
    db.commit()
    db.refresh(db_room)

    logger.info(f"Created room: {room.room_number} - {room.room_type}")
    return db_room


@router.put("/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: int,
    room: RoomUpdate,
    db: Session = Depends(get_db)
):
    """Update a room"""
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Room not found")

    update_data = room.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(db_room, field, value)

    db.commit()
    db.refresh(db_room)

    logger.info(f"Updated room {room_id}: {db_room.room_number} - {db_room.room_type}")
    return db_room


@router.delete("/{room_id}")
async def delete_room(room_id: int, db: Session = Depends(get_db)):
    """Delete a room"""
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if room is currently assigned to any reservations
    from app.db.models import Reservation
    assigned_count = db.query(Reservation).filter(
        Reservation.room_number == db_room.room_number
    ).count()

    if assigned_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"객실 '{db_room.room_number}'이(가) 현재 {assigned_count}건의 예약에 배정되어 있습니다. 배정을 먼저 해제해주세요."
        )

    room_number = db_room.room_number
    db.delete(db_room)
    db.commit()

    logger.info(f"Deleted room: {room_number}")
    return {"status": "success", "message": f"객실 '{room_number}'이(가) 삭제되었습니다."}
