"""
Rooms API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
from typing import List, Optional, Dict
from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.db.models import Room, NaverBizItem, User, Tenant, RoomAssignment, RoomBizItemLink, Building
from app.factory import get_reservation_provider_for_tenant
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.rate_limit import limiter
from datetime import datetime, timezone
import logging

from app.scheduler.room_auto_assign import auto_assign_rooms
from app.api.shared_schemas import ActionResponse

router = APIRouter(prefix="/api/rooms", tags=["rooms"])
logger = logging.getLogger(__name__)


class BizItemLinkInput(BaseModel):
    biz_item_id: str
    male_priority: int = 0
    female_priority: int = 0

class BizItemLinkResponse(BaseModel):
    biz_item_id: str
    male_priority: int = 0
    female_priority: int = 0


class RoomCreate(BaseModel):
    room_number: str
    room_type: str
    base_capacity: int = 2
    max_capacity: int = 4
    active: bool = True
    sort_order: int = 0
    naver_biz_item_id: Optional[str] = None  # Deprecated: use biz_item_ids
    biz_item_ids: Optional[List[str]] = None
    biz_item_links: Optional[List[BizItemLinkInput]] = None  # Priority-aware links
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
    biz_item_links: Optional[List[BizItemLinkInput]] = None  # Priority-aware links
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
    biz_item_links_detail: List[BizItemLinkResponse] = []
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
        biz_item_links_detail=[
            BizItemLinkResponse(
                biz_item_id=link.biz_item_id,
                male_priority=link.male_priority or 0,
                female_priority=link.female_priority or 0,
            ) for link in (room.biz_item_links or [])
        ],
        building_id=room.building_id,
        building_name=room.building.name if room.building else None,
        dormitory=room.is_dormitory,
        bed_capacity=room.bed_capacity,
        door_password=room.door_password,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


def _sync_biz_item_links(db: Session, room: Room, biz_item_ids: List[str],
                          priorities: Optional[Dict[str, dict]] = None):
    """Upsert biz_item_links: preserve existing priority, add new, remove stale."""
    # Validate all biz_item_ids belong to current tenant's NaverBizItem
    if biz_item_ids:
        valid_biz_ids = {
            item.biz_item_id for item in db.query(NaverBizItem).filter(
                NaverBizItem.biz_item_id.in_(biz_item_ids)
            ).all()
        }  # auto-filtered by tenant via before_compile
        invalid = set(biz_item_ids) - valid_biz_ids
        if invalid:
            raise HTTPException(status_code=400, detail=f"유효하지 않은 상품 ID: {', '.join(invalid)}")

    existing = {link.biz_item_id: link for link in room.biz_item_links}
    target_ids = set(biz_item_ids)

    # Remove stale links
    for biz_id, link in existing.items():
        if biz_id not in target_ids:
            db.delete(link)

    # Add or update
    for biz_id in biz_item_ids:
        if biz_id in existing:
            link = existing[biz_id]
            if priorities and biz_id in priorities:
                link.male_priority = priorities[biz_id].get("male_priority", link.male_priority)
                link.female_priority = priorities[biz_id].get("female_priority", link.female_priority)
        else:
            prio = (priorities or {}).get(biz_id, {})
            db.add(RoomBizItemLink(
                room_id=room.id, biz_item_id=biz_id,
                male_priority=prio.get("male_priority", 0),
                female_priority=prio.get("female_priority", 0),
            ))

    room.naver_biz_item_id = biz_item_ids[0] if biz_item_ids else None


@router.get("", response_model=List[RoomResponse])
async def get_rooms(
    include_inactive: bool = False,
    db: Session = Depends(get_tenant_scoped_db),
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
async def get_naver_biz_items(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get stored Naver biz items"""
    items = db.query(NaverBizItem).filter(NaverBizItem.is_active == True).order_by(NaverBizItem.name).all()
    return [_biz_item_to_response(i) for i in items]


@router.post("/naver/biz-items/sync")
@limiter.limit("5/minute")
async def sync_naver_biz_items(request: Request, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(require_admin_or_above), tenant: Tenant = Depends(get_current_tenant)):
    """Sync biz items from Naver Smart Place API"""
    provider = get_reservation_provider_for_tenant(tenant)
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

    # 동기화에 없는 기존 상품은 비활성화 (현재 테넌트만)
    from app.db.tenant_context import current_tenant_id
    tid = current_tenant_id.get()
    deactivated = (
        db.query(NaverBizItem)
        .filter(
            NaverBizItem.biz_item_id.notin_(synced_biz_ids),
            NaverBizItem.is_active == True,
            NaverBizItem.tenant_id == tid,
        )
        .update({"is_active": False}, synchronize_session="fetch")
    )

    db.commit()
    return {"success": True, "added": added, "updated": updated, "deactivated": deactivated}


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get a single room by ID"""
    room = db.query(Room).options(selectinload(Room.biz_item_links), selectinload(Room.building)).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")
    return _room_to_response(room)


@router.post("", response_model=RoomResponse)
async def create_room(room: RoomCreate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Create a new room (duplicates allowed)"""
    # Resolve biz_item_links: prefer biz_item_links (with priority), fall back to biz_item_ids, then legacy
    if room.biz_item_links is not None:
        biz_item_ids = [item.biz_item_id for item in room.biz_item_links]
        priorities = {item.biz_item_id: {"male_priority": item.male_priority, "female_priority": item.female_priority} for item in room.biz_item_links}
    else:
        biz_item_ids = room.biz_item_ids if room.biz_item_ids is not None else (
            [room.naver_biz_item_id] if room.naver_biz_item_id else []
        )
        priorities = None

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

    # Create N:M links with priority
    for biz_id in biz_item_ids:
        prio = (priorities or {}).get(biz_id, {})
        db.add(RoomBizItemLink(
            room_id=db_room.id, biz_item_id=biz_id,
            male_priority=prio.get("male_priority", 0),
            female_priority=prio.get("female_priority", 0),
        ))

    db.commit()
    db.refresh(db_room)

    logger.info(f"Created room: {room.room_number} - {room.room_type} (biz_items: {biz_item_ids})")
    return _room_to_response(db_room)


@router.put("/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: int,
    room: RoomUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Update a room"""
    db_room = db.query(Room).options(selectinload(Room.biz_item_links), selectinload(Room.building)).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

    update_data = room.dict(exclude_unset=True)

    # Handle biz_item_links (priority-aware) — takes precedence over biz_item_ids
    biz_item_links_input = update_data.pop("biz_item_links", None)
    biz_item_ids = update_data.pop("biz_item_ids", None)
    legacy_biz_id = update_data.pop("naver_biz_item_id", None)

    priorities = None
    if biz_item_links_input is not None:
        biz_item_ids = [item["biz_item_id"] for item in biz_item_links_input]
        priorities = {item["biz_item_id"]: {"male_priority": item.get("male_priority", 0), "female_priority": item.get("female_priority", 0)} for item in biz_item_links_input}
    elif biz_item_ids is None and legacy_biz_id is not None:
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
        _sync_biz_item_links(db, db_room, biz_item_ids, priorities)

    db.commit()
    db.refresh(db_room)

    logger.info(f"Updated room {room_id}: {db_room.room_number} - {db_room.room_type}")
    return _room_to_response(db_room)


@router.delete("/{room_id}", response_model=ActionResponse)
async def delete_room(room_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
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
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """
    수동 트리거: 미배정 예약자만 빈 객실에 배정.
    기존 배정(수동/자동)은 유지하고, 미배정자만 추가 배정.
    """
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo as _ZI

    if not date:
        date = dt.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")

    today = date

    # 미배정자만 추가 배정 (기존 배정 유지, 로그는 auto_assign_rooms 내부에서 생성)
    result_today = auto_assign_rooms(db, today, created_by=current_user.username)

    return {
        "success": True,
        "today": result_today,
    }
