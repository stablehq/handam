"""
Rooms API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
from typing import List, Optional, Dict
from app.api.deps import get_tenant_scoped_db, get_current_tenant, _remap_active_field
from app.db.models import Room, RoomGroup, NaverBizItem, User, Tenant, RoomAssignment, RoomBizItemLink
from app.db.tenant_context import get_session_tenant_id
from app.factory import get_reservation_provider_for_tenant
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.rate_limit import limiter
from datetime import datetime, timezone
import logging

from app.services.room_auto_assign import auto_assign_rooms
from app.api.shared_schemas import ActionResponse
from app.diag_logger import diag

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
    room_memo: Optional[str] = None


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
    room_memo: Optional[str] = None


class RoomResponse(BaseModel):
    id: int
    room_number: str
    room_type: str
    base_capacity: int
    max_capacity: int
    active: bool
    hidden: bool = False
    sort_order: int
    naver_biz_item_id: Optional[str] = None  # Deprecated: computed from first biz_item_link
    biz_item_ids: List[str] = []
    biz_item_links_detail: List[BizItemLinkResponse] = []
    building_id: Optional[int] = None
    building_name: Optional[str] = None
    dormitory: bool = False
    bed_capacity: int = 1
    room_group_id: Optional[int] = None
    room_group_name: Optional[str] = None
    door_password: Optional[str] = None
    room_memo: Optional[str] = None
    grade: Optional[int] = None  # 1~5 객실 등급 (room_upgrade_review 칩 발송 조건)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoomUpdateResponse(BaseModel):
    room: RoomResponse
    warning: Optional[str] = None
    affected_reservation_ids: List[int] = []


class NaverBizItemResponse(BaseModel):
    id: int
    biz_item_id: str
    name: str
    display_name: Optional[str] = None
    default_capacity: Optional[int] = None
    section_hint: Optional[str] = None
    default_party_type: Optional[str] = None
    biz_item_type: Optional[str] = None
    grade: Optional[int] = None  # 1~5 예약 상품 등급 (room_upgrade_review 칩 발송 조건)
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
        hidden=bool(room.is_hidden),
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
        room_group_id=room.room_group_id,
        room_group_name=room.room_group.name if room.room_group else None,
        dormitory=room.is_dormitory,
        bed_capacity=room.bed_capacity,
        door_password=room.door_password,
        room_memo=room.room_memo,
        grade=room.grade,
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
        selectinload(Room.room_group),
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
        display_name=item.display_name,
        default_capacity=item.default_capacity,
        section_hint=item.section_hint,
        default_party_type=item.default_party_type,
        biz_item_type=item.biz_item_type,
        grade=item.grade,
        exposed=item.is_exposed,
        active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/naver/biz-items", response_model=List[NaverBizItemResponse])
async def get_naver_biz_items(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get stored Naver biz items"""
    items = db.query(NaverBizItem).order_by(NaverBizItem.is_exposed.desc(), NaverBizItem.updated_at.desc()).all()
    return [_biz_item_to_response(i) for i in items]


class BizItemUpdateRequest(BaseModel):
    biz_item_id: str
    display_name: Optional[str] = None
    default_capacity: Optional[int] = None
    section_hint: Optional[str] = None
    default_party_type: Optional[str] = None
    grade: Optional[int] = None  # 1~5. None 은 변경 안 함 (NULL 로 되돌리기 미지원)


@router.patch("/naver/biz-items")
def update_biz_items(
    items: List[BizItemUpdateRequest],
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Batch update NaverBizItem settings (display_name, default_capacity, section_hint)"""
    updated = []
    for item_data in items:
        biz_item = db.query(NaverBizItem).filter(
            NaverBizItem.biz_item_id == item_data.biz_item_id
        ).first()
        if not biz_item:
            continue
        if item_data.display_name is not None:
            biz_item.display_name = item_data.display_name or None  # empty string → None
        if item_data.default_capacity is not None:
            biz_item.default_capacity = item_data.default_capacity
        if item_data.section_hint is not None:
            biz_item.section_hint = item_data.section_hint or None  # empty string → None
        if item_data.default_party_type is not None:
            biz_item.default_party_type = item_data.default_party_type or None  # empty string → None
        if item_data.grade is not None:
            from app.services.room_grade import is_valid_grade
            if not is_valid_grade(item_data.grade):
                raise HTTPException(
                    status_code=400,
                    detail=f"등급은 1~5 사이의 정수여야 합니다 (입력: {item_data.grade})",
                )
            biz_item.grade = item_data.grade
        updated.append(biz_item)

    # grade 가 변경된 biz_item 의 영향 예약에 대해 stale 칩 정리.
    # commit 전에 reconcile 실행 — 같은 트랜잭션에 묶어 race 방지.
    grade_changed_biz_ids = [
        item.biz_item_id
        for item in updated
        for req in items
        if req.biz_item_id == item.biz_item_id and req.grade is not None
    ]
    if grade_changed_biz_ids:
        _reconcile_room_upgrade_after_grade_change(
            db, biz_item_ids=grade_changed_biz_ids,
        )

    db.commit()
    return [_biz_item_to_response(item) for item in updated]


class RoomGradeUpdateItem(BaseModel):
    id: int
    grade: int  # 1~5 (NULL 로 되돌리기 미지원)


@router.patch("/grades")
def update_room_grades(
    items: List[RoomGradeUpdateItem],
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """객실 등급 일괄 업데이트 (room_upgrade_review 칩 발송 조건).

    단일 트랜잭션 — 한 행 validation 실패 시 전체 rollback.
    """
    from app.services.room_grade import is_valid_grade

    # 1. validation 먼저 — 한 행이라도 잘못되면 DB 안 건드림
    for item_data in items:
        if not is_valid_grade(item_data.grade):
            raise HTTPException(
                status_code=400,
                detail=f"등급은 1~5 사이의 정수여야 합니다 (id={item_data.id}, 입력={item_data.grade})",
            )

    # 2. 일괄 업데이트
    target_ids = [i.id for i in items]
    grade_map = {i.id: i.grade for i in items}
    rooms = db.query(Room).filter(Room.id.in_(target_ids)).all()
    found_ids = {r.id for r in rooms}
    missing = set(target_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"존재하지 않는 객실 id: {sorted(missing)}",
        )
    for room in rooms:
        room.grade = grade_map[room.id]

    # grade 가 변경된 Room 에 배정된 오늘 이후 예약 stale 칩 정리.
    # commit 전에 reconcile 실행 — 같은 트랜잭션.
    _reconcile_room_upgrade_after_grade_change(db, room_ids=target_ids)

    db.commit()
    diag(
        "rooms.grades_updated",
        level="critical",
        count=len(rooms),
        room_ids=sorted(target_ids),
        grade_map={str(r.id): r.grade for r in rooms},
    )
    return [_room_to_response(r) for r in rooms]


def _reconcile_room_upgrade_after_grade_change(
    db: Session,
    *,
    room_ids: Optional[List[int]] = None,
    biz_item_ids: Optional[List[str]] = None,
) -> None:
    """grade 변경 직후 영향 예약의 room_upgrade_promise / _review 칩 재계산.

    room_ids: 해당 객실에 배정된 오늘 이후 RoomAssignment 대상
    biz_item_ids: 해당 상품을 예약한 진행중/미래 예약의 stay 전체 박일 대상

    각 모듈은 스케줄 비활성 시 즉시 return — grade 만 입력해두는 운영 단계
    (스케줄 활성화 전) 에서도 부담 0.
    """
    from app.config import today_kst
    from app.services.room_upgrade_promise import reconcile_room_upgrade_promise_batch
    from app.services.room_upgrade_review import reconcile_room_upgrade_review_batch

    today_str = today_kst()

    # date → reservation_id 집합 으로 그룹핑 (batch 함수가 (ids, date) 시그니처)
    targets: Dict[str, set] = {}

    if room_ids:
        assigns = (
            db.query(RoomAssignment.reservation_id, RoomAssignment.date)
            .filter(
                RoomAssignment.room_id.in_(room_ids),
                RoomAssignment.date >= today_str,
            )
            .all()
        )
        for res_id, date in assigns:
            targets.setdefault(date, set()).add(res_id)

    if biz_item_ids:
        # 진행 중 / 미래 예약: check_out_date >= today 또는 check_out_date IS NULL
        from app.db.models import Reservation, ReservationStatus
        from sqlalchemy import or_

        res_rows = (
            db.query(Reservation.id, Reservation.check_in_date, Reservation.check_out_date)
            .filter(
                Reservation.naver_biz_item_id.in_(biz_item_ids),
                Reservation.status == ReservationStatus.CONFIRMED,
                or_(
                    Reservation.check_out_date.is_(None),
                    Reservation.check_out_date >= today_str,
                ),
            )
            .all()
        )
        # stay 의 각 박일 (오늘 이후만) 추가
        from app.services.schedule_utils import date_range
        for res_id, ci, co in res_rows:
            if not ci:
                continue
            for d in date_range(ci, co):
                if d >= today_str:
                    targets.setdefault(d, set()).add(res_id)

    for date, ids in targets.items():
        try:
            reconcile_room_upgrade_promise_batch(db, list(ids), date)
        except Exception as e:
            logger.warning(
                f"grade-change promise reconcile failed for date={date}: {e}"
            )
        try:
            reconcile_room_upgrade_review_batch(db, list(ids), date)
        except Exception as e:
            logger.warning(
                f"grade-change review reconcile failed for date={date}: {e}"
            )


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
            # ★ 운영자 전용 컬럼은 여기서 갱신하지 않음 (네이버 API 응답에 없는 필드):
            #   display_name, default_capacity, section_hint, default_party_type, grade
            # 운영자가 모달에서 직접 입력한 값을 sync 가 덮어쓰지 않도록 보존.
            # 새 운영자 컬럼 추가 시 같은 원칙 유지할 것.
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
    from app.db.tenant_context import get_session_tenant_id
    tid = get_session_tenant_id(db)
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



# ── Room Groups (MUST be before /{room_id} to avoid route shadowing) ─────────

class RoomGroupCreate(BaseModel):
    name: str
    sort_order: int = 0
    color: Optional[str] = None
    room_ids: List[int] = []


class RoomGroupUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    color: Optional[str] = None
    room_ids: Optional[List[int]] = None


class RoomGroupResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    color: Optional[str] = None
    room_ids: List[int] = []
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/groups", response_model=List[RoomGroupResponse])
async def get_room_groups(
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    groups = db.query(RoomGroup).options(selectinload(RoomGroup.rooms)).order_by(RoomGroup.sort_order).all()
    return [
        RoomGroupResponse(
            id=g.id, name=g.name, sort_order=g.sort_order, color=g.color,
            room_ids=[r.id for r in g.rooms],
            created_at=g.created_at,
        ) for g in groups
    ]


@router.post("/groups", response_model=RoomGroupResponse)
async def create_room_group(
    data: RoomGroupCreate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    group = RoomGroup(name=data.name, sort_order=data.sort_order, color=data.color)
    db.add(group)
    db.flush()

    if data.room_ids:
        tid = get_session_tenant_id(db)
        db.query(Room).filter(Room.id.in_(data.room_ids), Room.tenant_id == tid).update(
            {Room.room_group_id: group.id}, synchronize_session="fetch"
        )

    db.commit()
    db.refresh(group)
    return RoomGroupResponse(
        id=group.id, name=group.name, sort_order=group.sort_order, color=group.color,
        room_ids=[r.id for r in group.rooms],
        created_at=group.created_at,
    )


@router.put("/groups/{group_id}", response_model=RoomGroupResponse)
async def update_room_group(
    group_id: int,
    data: RoomGroupUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    group = db.query(RoomGroup).filter(RoomGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다")

    if data.name is not None:
        group.name = data.name
    if data.sort_order is not None:
        group.sort_order = data.sort_order
    if data.color is not None:
        group.color = data.color

    if data.room_ids is not None:
        tid = get_session_tenant_id(db)
        # Clear old assignments
        db.query(Room).filter(Room.room_group_id == group.id, Room.tenant_id == tid).update(
            {Room.room_group_id: None}, synchronize_session="fetch"
        )
        # Assign new
        if data.room_ids:
            db.query(Room).filter(Room.id.in_(data.room_ids), Room.tenant_id == tid).update(
                {Room.room_group_id: group.id}, synchronize_session="fetch"
            )

    db.commit()
    db.refresh(group)
    return RoomGroupResponse(
        id=group.id, name=group.name, sort_order=group.sort_order, color=group.color,
        room_ids=[r.id for r in group.rooms],
        created_at=group.created_at,
    )


@router.delete("/groups/{group_id}")
async def delete_room_group(
    group_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    group = db.query(RoomGroup).filter(RoomGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다")

    # Clear room assignments
    tid = get_session_tenant_id(db)
    db.query(Room).filter(Room.room_group_id == group.id, Room.tenant_id == tid).update(
        {Room.room_group_id: None}, synchronize_session="fetch"
    )
    db.delete(group)
    db.commit()
    return {"success": True}


# ── Single Room CRUD ─────────────────────────────────────────────────────────

@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get a single room by ID"""
    room = db.query(Room).options(selectinload(Room.biz_item_links), selectinload(Room.building), selectinload(Room.room_group)).filter(Room.id == room_id).first()
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
        room_memo=room.room_memo,
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


@router.put("/{room_id}", response_model=RoomUpdateResponse)
async def update_room(
    room_id: int,
    room: RoomUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Update a room"""
    db_room = db.query(Room).options(selectinload(Room.biz_item_links), selectinload(Room.building), selectinload(Room.room_group)).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

    update_data = room.dict(exclude_unset=True)
    # Phase 2-5b (C-C): 배정에 영향 주는 필드 변경 감지 (remap 이전 원본 key 기준)
    _AFFECTS_ASSIGNMENT = {
        "biz_item_ids", "biz_item_links", "base_capacity",
        "is_dormitory", "dormitory", "bed_capacity",
    }
    _original_keys = set(update_data.keys())
    affects_assignment = bool(_AFFECTS_ASSIGNMENT & _original_keys)

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
    _remap_active_field(update_data)
    if "dormitory" in update_data:
        update_data["is_dormitory"] = update_data.pop("dormitory")

    for field, value in update_data.items():
        setattr(db_room, field, value)

    # Sync N:M links if biz_item_ids was provided
    if biz_item_ids is not None:
        _sync_biz_item_links(db, db_room, biz_item_ids, priorities)

    # Phase 2-5b: 영향 감지 (commit 전, 미래 배정 조회는 현재 room_id 기준)
    warning: Optional[str] = None
    affected_ids: List[int] = []
    if affects_assignment:
        from app.services.room_assignment_invariants import check_room_config_impact
        try:
            affected_ids = check_room_config_impact(db, room_id)
            if affected_ids:
                warning = f"{len(affected_ids)}건의 미래 배정이 영향받을 수 있습니다. 수동 재배정을 고려하세요."
            diag(
                "rooms.update.config_affects_assignments",
                level="critical",
                room_id=room_id,
                affected_count=len(affected_ids),
                changed_fields=list(_original_keys & _AFFECTS_ASSIGNMENT),
            )
        except Exception as e:
            logger.warning(f"check_room_config_impact failed for room {room_id}: {e}")

    db.commit()
    db.refresh(db_room)

    logger.info(f"Updated room {room_id}: {db_room.room_number} - {db_room.room_type}")
    return RoomUpdateResponse(
        room=_room_to_response(db_room),
        warning=warning,
        affected_reservation_ids=affected_ids,
    )


class RoomReorderRequest(BaseModel):
    ordered_ids: List[int]  # 새 정렬 순서대로 정렬된 room id 배열


@router.post("/reorder", response_model=ActionResponse)
def reorder_rooms(
    payload: RoomReorderRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """ordered_ids 순서대로 sort_order 일괄 갱신 (DnD용).

    현재 테넌트의 전체 객실 ID 와 정확히 일치해야 함 (중복/누락 모두 거부).
    부분 reorder 를 허용하면 보내지 않은 객실과 sort_order 가 충돌할 수 있음.
    프론트에서 N개 PUT 병렬 → 1회 호출로 단순화 + 트랜잭션 보장.
    """
    sent_ids = payload.ordered_ids
    if not sent_ids:
        raise HTTPException(status_code=400, detail="ordered_ids가 비어 있습니다")

    if len(sent_ids) != len(set(sent_ids)):
        raise HTTPException(status_code=400, detail="중복된 객실 ID가 포함되어 있습니다")

    # 현재 테넌트의 모든 객실 (TenantMixin auto-filter 적용)
    all_ids = {row[0] for row in db.query(Room.id).all()}
    if set(sent_ids) != all_ids:
        raise HTTPException(status_code=400, detail="전체 객실 목록과 일치하지 않습니다")

    rooms_list = db.query(Room).filter(Room.id.in_(sent_ids)).all()
    by_id = {r.id: r for r in rooms_list}

    for index, rid in enumerate(sent_ids):
        by_id[rid].sort_order = index + 1  # 1-based (기존 RoomSettings 동작과 일치)

    db.commit()

    diag("rooms.reordered", level="critical", count=len(sent_ids))
    return {"success": True, "message": "정렬 순서가 변경되었습니다"}


@router.delete("/{room_id}", response_model=ActionResponse)
async def delete_room(room_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Delete a room"""
    diag("rooms.delete", level="critical", room_id=room_id)
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

    # Check if room is currently assigned to any reservations
    assigned_count = db.query(RoomAssignment).filter(
        RoomAssignment.room_id == room_id
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


@router.post("/{room_id}/hide", response_model=ActionResponse)
async def hide_room(
    room_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """객실을 미노출 처리 — 객실 배정 페이지에서 카드 자체 안 보이게.

    부수효과:
    - 오늘 이후 (date >= today_kst) 의 RoomAssignment 행 모두 삭제 → 해당 예약자들 미배정 zone 으로 이동
    - 영향받은 예약 각각 reconcile_all_chips() 호출 → SMS 칩 재계산
    - 과거 RoomAssignment 는 그대로 보존 (이력)
    """
    from app.config import today_kst
    from app.services.activity_logger import log_activity
    from app.services.reconcile import reconcile_all_chips

    diag("rooms.hide.enter", level="critical", room_id=room_id)

    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

    if db_room.is_hidden:
        return {"success": True, "message": f"객실 '{db_room.room_number}'은(는) 이미 미노출 상태입니다."}

    today = today_kst()
    future_assignments = db.query(RoomAssignment).filter(
        RoomAssignment.room_id == room_id,
        RoomAssignment.date >= today,
    ).all()
    affected_pairs = [(a.reservation_id, a.date) for a in future_assignments]
    affected_res_ids = sorted({r for r, _ in affected_pairs})

    for a in future_assignments:
        db.delete(a)

    db_room.is_hidden = True
    db.flush()

    # 영향받은 예약자 칩 재계산 (삭제된 날짜만 대상)
    res_to_dates: dict[int, list[str]] = {}
    for res_id, d in affected_pairs:
        res_to_dates.setdefault(res_id, []).append(d)
    for res_id, dates in res_to_dates.items():
        try:
            reconcile_all_chips(db, res_id, dates=dates, room_id=room_id)
        except Exception as e:
            logger.warning(f"hide_room: reconcile failed res={res_id} room={room_id}: {e}")

    log_activity(
        db, type="room_hide",
        title=f"객실 미노출 : {db_room.room_number}",
        detail={
            "room_id": room_id,
            "room_number": db_room.room_number,
            "future_assignments_removed": len(affected_pairs),
            "affected_reservation_ids": affected_res_ids,
        },
        created_by=current_user.username,
    )
    db.commit()

    diag(
        "rooms.hide.exit",
        level="info",
        room_id=room_id,
        removed=len(affected_pairs),
        affected_res_count=len(affected_res_ids),
    )

    return {
        "success": True,
        "message": (
            f"객실 '{db_room.room_number}' 미노출 처리됨. "
            f"미래 배정자 {len(affected_res_ids)}명을 미배정으로 이동했습니다."
        ),
    }


@router.post("/{room_id}/unhide", response_model=ActionResponse)
async def unhide_room(
    room_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """객실 미노출 해제 — 페이지에 다시 노출. 과거 RoomAssignment 그대로 보임.

    미노출 시 삭제된 미래 배정자는 자동 복귀하지 않음 (정책상). 필요 시 수동/자동 배정 재실행.
    """
    from app.services.activity_logger import log_activity

    diag("rooms.unhide.enter", level="info", room_id=room_id)

    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="객실을 찾을 수 없습니다")

    if not db_room.is_hidden:
        return {"success": True, "message": f"객실 '{db_room.room_number}'은(는) 이미 노출 상태입니다."}

    db_room.is_hidden = False
    log_activity(
        db, type="room_unhide",
        title=f"객실 미노출 해제 : {db_room.room_number}",
        detail={"room_id": room_id, "room_number": db_room.room_number},
        created_by=current_user.username,
    )
    db.commit()

    return {
        "success": True,
        "message": f"객실 '{db_room.room_number}' 노출 처리됨.",
    }


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
    from zoneinfo import ZoneInfo as _ZI

    if not date:
        date = datetime.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")

    today = date

    diag("rooms.manual_auto_assign_trigger", level="verbose", date=today)

    # 미배정자만 추가 배정 (기존 배정 유지, 로그는 auto_assign_rooms 내부에서 생성)
    result_today = auto_assign_rooms(db, today, created_by=current_user.username)
    db.commit()

    return {
        "success": True,
        "today": result_today,
    }
