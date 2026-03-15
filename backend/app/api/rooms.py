"""
Rooms API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.db.database import get_db
from app.db.models import Room, NaverBizItem, User, RoomAssignment
from app.factory import get_reservation_provider
from app.auth.dependencies import get_current_user
from datetime import datetime
import logging

from app.scheduler.room_reassign import auto_assign_rooms

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
logger = logging.getLogger(__name__)


class RoomCreate(BaseModel):
    room_number: str
    room_type: str
    base_capacity: int = 2
    max_capacity: int = 4
    is_active: bool = True
    sort_order: int = 0
    naver_biz_item_id: Optional[str] = None
    is_dormitory: bool = False
    dormitory_beds: int = 1
    default_password: Optional[str] = None


class RoomUpdate(BaseModel):
    room_number: Optional[str] = None
    room_type: Optional[str] = None
    base_capacity: Optional[int] = None
    max_capacity: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    naver_biz_item_id: Optional[str] = None
    is_dormitory: Optional[bool] = None
    dormitory_beds: Optional[int] = None
    default_password: Optional[str] = None


class RoomResponse(BaseModel):
    id: int
    room_number: str
    room_type: str
    base_capacity: int
    max_capacity: int
    is_active: bool
    sort_order: int
    naver_biz_item_id: Optional[str] = None
    is_dormitory: bool = False
    dormitory_beds: int = 1
    default_password: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NaverBizItemResponse(BaseModel):
    id: int
    biz_item_id: str
    name: str
    biz_item_type: Optional[str] = None
    is_exposed: bool = True
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[RoomResponse])
async def get_rooms(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all rooms"""
    query = db.query(Room)

    if not include_inactive:
        query = query.filter(Room.is_active == True)

    rooms = query.order_by(Room.sort_order).all()
    return rooms


@router.get("/naver/biz-items", response_model=List[NaverBizItemResponse])
async def get_naver_biz_items(db: Session = Depends(get_db)):
    """Get stored Naver biz items"""
    items = db.query(NaverBizItem).filter(NaverBizItem.is_active == True).order_by(NaverBizItem.name).all()
    return items


@router.post("/naver/biz-items/sync")
async def sync_naver_biz_items(db: Session = Depends(get_db)):
    """Sync biz items from Naver Smart Place API"""
    provider = get_reservation_provider()
    items = await provider.fetch_biz_items()

    added = 0
    updated = 0
    for item_data in items:
        existing = db.query(NaverBizItem).filter(
            NaverBizItem.biz_item_id == item_data['biz_item_id']
        ).first()

        if existing:
            existing.name = item_data['name']
            existing.biz_item_type = item_data.get('biz_item_type')
            existing.is_exposed = item_data.get('is_exposed', True)
            existing.updated_at = datetime.utcnow()
            updated += 1
        else:
            new_item = NaverBizItem(
                biz_item_id=item_data['biz_item_id'],
                name=item_data['name'],
                biz_item_type=item_data.get('biz_item_type'),
                is_exposed=item_data.get('is_exposed', True),
            )
            db.add(new_item)
            added += 1

    db.commit()
    return {"status": "success", "added": added, "updated": updated}


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a single room by ID"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.post("", response_model=RoomResponse)
async def create_room(room: RoomCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a new room (duplicates allowed)"""
    db_room = Room(
        room_number=room.room_number,
        room_type=room.room_type,
        base_capacity=room.base_capacity,
        max_capacity=room.max_capacity,
        is_active=room.is_active,
        sort_order=room.sort_order,
        naver_biz_item_id=room.naver_biz_item_id,
        is_dormitory=room.is_dormitory,
        dormitory_beds=room.dormitory_beds,
        default_password=room.default_password,
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
async def delete_room(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a room"""
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if room is currently assigned to any reservations
    assigned_count = db.query(RoomAssignment).filter(
        RoomAssignment.room_number == db_room.room_number
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


@router.post("/auto-assign")
async def trigger_auto_assign(
    date: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    수동 트리거: 객실 자동 배정.
    수동 배정(assigned_by='manual')은 유지하고,
    자동 배정된 객실만 초기화 후 재배정.
    """
    from datetime import datetime as dt, timedelta

    if not date:
        date = dt.now().strftime("%Y-%m-%d")

    today = date
    tomorrow = (dt.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # 기존 자동 배정만 삭제 (수동 배정 유지)
    for target_date in [today, tomorrow]:
        db.query(RoomAssignment).filter(
            RoomAssignment.date == target_date,
            RoomAssignment.assigned_by == "auto",
        ).delete(synchronize_session="fetch")
    db.commit()

    # 재배정
    result_today = auto_assign_rooms(db, today)
    result_tomorrow = auto_assign_rooms(db, tomorrow)

    return {
        "status": "success",
        "today": result_today,
        "tomorrow": result_tomorrow,
    }
