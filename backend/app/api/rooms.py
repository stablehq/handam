"""
Rooms API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
from typing import List, Optional
from app.db.database import get_db
from app.db.models import Room, NaverBizItem, User, RoomAssignment, RoomBizItemLink, Building
from app.factory import get_reservation_provider
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.rate_limit import limiter
from datetime import datetime, timezone
import logging

from app.scheduler.room_auto_assign import auto_assign_rooms
from app.services.activity_logger import log_activity
from app.api.shared_schemas import ActionResponse

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
logger = logging.getLogger(__name__)


class RoomCreate(BaseModel):
    room_number: str
    room_type: str
    base_capacity: int = 2
    max_capacity: int = 4
    active: bool = True
    sort_order: int = 0
    naver_biz_item_id: Optional[str] = None  # Deprecated: use biz_item_ids
    biz_item_ids: Optional[List[str]] = None
    building_id: Optional[int] = None
    dormitory: bool = False
    bed_capacity: int = 1
    door_password: Optional[str] = None


class RoomUpdate(BaseModel):
    room_number: Optional[str] = None
    room_type: Optional[str] = None
    base_capacity: Optional[int] = None
    max_capacity: Optional[int] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None
    naver_biz_item_id: Optional[str] = None  # Deprecated: use biz_item_ids
    biz_item_ids: Optional[List[str]] = None
    building_id: Optional[int] = None
    dormitory: Optional[bool] = None
    bed_capacity: Optional[int] = None
    door_password: Optional[str] = None


class RoomResponse(BaseModel):
    id: int
    room_number: str
    room_type: str
    base_capacity: int
    max_capacity: int
    active: bool
    sort_order: int
    naver_biz_item_id: Optional[str] = None  # Deprecated: computed from first biz_item_link
    biz_item_ids: List[str] = []
    building_id: Optional[int] = None
    building_name: Optional[str] = None
    dormitory: bool = False
    bed_capacity: int = 1
    door_password: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NaverBizItemResponse(BaseModel):
    id: int
    biz_item_id: str
    name: str
    biz_item_type: Optional[str] = None
    exposed: bool = True
    active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _room_to_response(room: Room) -> dict:
    """Convert Room ORM object to RoomResponse-compatible dict with biz_item_ids."""
    biz_item_ids = [link.biz_item_id for link in room.biz_item_links] if room.biz_item_links else []
    return RoomResponse(
        id=room.id,
        room_number=room.room_number,
        room_type=room.room_type,
        base_capacity=room.base_capacity,
        max_capacity=room.max_capacity,
        active=room.is_active,
        sort_order=room.sort_order,
        naver_biz_item_id=biz_item_ids[0] if biz_item_ids else room.naver_biz_item_id,
        biz_item_ids=biz_item_ids,
        building_id=room.building_id,
        building_name=room.building.name if room.building else None,
        dormitory=room.is_dormitory,
        bed_capacity=room.bed_capacity,
        door_password=room.door_password,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


def _sync_biz_item_links(db: Session, room: Room, biz_item_ids: List[str]):
    """Replace all biz_item_links for a room with the given biz_item_ids."""
    # Delete existing links
    db.query(RoomBizItemLink).filter(RoomBizItemLink.room_id == room.id).delete(synchronize_session="fetch")
    # Create new links
    for biz_id in biz_item_ids:
        db.add(RoomBizItemLink(room_id=room.id, biz_item_id=biz_id))
    # Update deprecated naver_biz_item_id for backward compat
    room.naver_biz_item_id = biz_item_ids[0] if biz_item_ids else None


@router.get("", response_model=List[RoomResponse])
async def get_rooms(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all rooms"""
    query = db.query(Room).options(
        selectinload(Room.biz_item_links),
        selectinload(Room.building),
    )

    if not include_inactive:
        query = query.filter(Room.is_active == True)

    rooms = query.order_by(Room.sort_order).all()
    return [_room_to_response(r) for r in rooms]


def _biz_item_to_response(item: NaverBizItem) -> NaverBizItemResponse:
    """Convert NaverBizItem ORM object to NaverBizItemResponse."""
    return NaverBizItemResponse(
        id=item.id,
        biz_item_id=item.biz_item_id,
        name=item.name,
        biz_item_type=item.biz_item_type,
        exposed=item.is_exposed,
        active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/naver/biz-items", response_model=List[NaverBizItemResponse])
async def get_naver_biz_items(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get stored Naver biz items"""
    items = db.query(NaverBizItem).filter(NaverBizItem.is_active == True).order_by(NaverBizItem.name).all()
    return [_biz_item_to_response(i) for i in items]


@router.post("/naver/biz-items/sync")
@limiter.limit("5/minute")
async def sync_naver_biz_items(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_above)):
    """Sync biz items from Naver Smart Place API"""
    provider = get_reservation_provider()
    items = await provider.fetch_biz_items()

    added = 0
    updated = 0
    synced_biz_ids = set()

    for item_data in items:
        synced_biz_ids.add(item_data['biz_item_id'])
        existing = db.query(NaverBizItem).filter(
            NaverBizItem.biz_item_id == item_data['biz_item_id']
        ).first()

        if existing:
            existing.name = item_data['name']
            existing.biz_item_type = item_data.get('biz_item_type')
            existing.is_exposed = item_data.get('is_exposed', True)
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
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

    # 동기화에 없는 기존 상품은 비활성화
    deactivated = (
        db.query(NaverBizItem)
        .filter(NaverBizItem.biz_item_id.notin_(synced_biz_ids), NaverBizItem.is_active == True)
        .update({"is_active": False}, synchronize_session="fetch")
    )

    db.commit()
    return {"success": True, "added": added, "updated": updated, "deactivated": deactivated}


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a single room by ID"""
    room = db.query(Room).options(selectinload(Room.biz_item_links), selectinload(Room.building)).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")
    return _room_to_response(room)


@router.post("", response_model=RoomResponse)
async def create_room(room: RoomCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a new room (duplicates allowed)"""
    # Resolve biz_item_ids: prefer biz_item_ids, fall back to legacy naver_biz_item_id
    biz_item_ids = room.biz_item_ids if room.biz_item_ids is not None else (
        [room.naver_biz_item_id] if room.naver_biz_item_id else []
    )

    db_room = Room(
        room_number=room.room_number,
        room_type=room.room_type,
        base_capacity=room.base_capacity,
        max_capacity=room.max_capacity,
        is_active=room.active,
        sort_order=room.sort_order,
        naver_biz_item_id=biz_item_ids[0] if biz_item_ids else None,
        building_id=room.building_id,
        is_dormitory=room.dormitory,
        bed_capacity=room.bed_capacity,
        door_password=room.door_password,
    )
    db.add(db_room)
    db.flush()  # Get room.id before creating links

    # Create N:M links
    for biz_id in biz_item_ids:
        db.add(RoomBizItemLink(room_id=db_room.id, biz_item_id=biz_id))

    db.commit()
    db.refresh(db_room)

    logger.info(f"Created room: {room.room_number} - {room.room_type} (biz_items: {biz_item_ids})")
    return _room_to_response(db_room)


@router.put("/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: int,
    room: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a room"""
    db_room = db.query(Room).options(selectinload(Room.biz_item_links), selectinload(Room.building)).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

    update_data = room.dict(exclude_unset=True)

    # Handle biz_item_ids separately
    biz_item_ids = update_data.pop("biz_item_ids", None)

    # Handle legacy naver_biz_item_id: if biz_item_ids not provided but naver_biz_item_id is,
    # treat it as a single-item list for backward compat
    legacy_biz_id = update_data.pop("naver_biz_item_id", None)
    if biz_item_ids is None and legacy_biz_id is not None:
        biz_item_ids = [legacy_biz_id] if legacy_biz_id else []

    # Remap JSON keys to ORM column names
    if "active" in update_data:
        update_data["is_active"] = update_data.pop("active")
    if "dormitory" in update_data:
        update_data["is_dormitory"] = update_data.pop("dormitory")

    for field, value in update_data.items():
        setattr(db_room, field, value)

    # Sync N:M links if biz_item_ids was provided
    if biz_item_ids is not None:
        _sync_biz_item_links(db, db_room, biz_item_ids)

    db.commit()
    db.refresh(db_room)

    logger.info(f"Updated room {room_id}: {db_room.room_number} - {db_room.room_type}")
    return _room_to_response(db_room)


@router.delete("/{room_id}", response_model=ActionResponse)
async def delete_room(room_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a room"""
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

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
    return {"success": True, "message": f"객실 '{room_number}'이(가) 삭제되었습니다."}


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
    from zoneinfo import ZoneInfo as _ZI

    if not date:
        date = dt.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")

    today = date

    # 기존 자동 배정만 삭제 (수동 배정 유지)
    db.query(RoomAssignment).filter(
        RoomAssignment.date == today,
        RoomAssignment.assigned_by == "auto",
    ).delete(synchronize_session="fetch")
    db.commit()

    # 재배정 (오늘만)
    result_today = auto_assign_rooms(db, today)

    total_assigned = result_today.get("assigned", 0)
    log_activity(
        db,
        type="room_assign",
        title=f"객실 자동 배정 ({today})",
        detail={"today": result_today},
        target_count=total_assigned,
        success_count=total_assigned,
        created_by=current_user.username,
    )
    db.commit()

    return {
        "success": True,
        "today": result_today,
    }
