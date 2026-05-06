"""
Reservations API — consecutive stay (연박) endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from app.api.deps import get_tenant_scoped_db
from app.db.models import Reservation, ReservationStatus, User, ReservationSmsAssignment, RoomAssignment, ReservationDailyInfo
from app.auth.dependencies import get_current_user
from app.api.shared_schemas import ActionResponse
from app.diag_logger import diag


router = APIRouter(prefix="/api/reservations", tags=["reservations"])


# ---------------------------------------------------------------------------
# Consecutive stay (연박) endpoints
# ---------------------------------------------------------------------------

class StayGroupLinkRequest(BaseModel):
    reservation_ids: List[int]


class ExtendStayRequest(BaseModel):
    """연박추가: create next-day reservation, link stay group, assign room"""
    room_id: Optional[int] = None  # Room to assign on next day (None = no assignment)


class ExtendStayResponse(BaseModel):
    success: bool
    new_reservation_id: int
    stay_group_id: str
    conflict_guests: List[str] = []  # Names of guests already in the room on next day


class ExtendStayAssignRequest(BaseModel):
    new_reservation_id: int
    room_id: int
    date: str  # YYYY-MM-DD
    move_existing_to_unassigned: bool = False  # True = move existing guests to unassigned


@router.post("/detect-consecutive", response_model=ActionResponse)
async def detect_consecutive_stays(
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger consecutive stay detection for the current tenant."""
    from app.services.consecutive_stay import detect_and_link_consecutive_stays

    result = detect_and_link_consecutive_stays(db)
    db.commit()

    return {
        "success": True,
        "message": f"연박 감지 완료: {result['groups']}개 그룹, {result['linked']}건 링크, {result['unlinked']}건 해제",
    }


@router.post("/{reservation_id}/stay-group/link", response_model=ActionResponse)
async def link_stay_group(
    reservation_id: int,
    request: StayGroupLinkRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Manually link reservations into a consecutive stay group."""
    from app.services.consecutive_stay import link_reservations

    all_ids = list(set([reservation_id] + request.reservation_ids))
    try:
        group_id, linked_ids = link_reservations(db, all_ids)
    except ValueError as e:
        diag(
            "stay_group.link_api.validation_failed",
            level="critical",
            reservation_id=reservation_id,
            requested_ids=all_ids,
            error=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e))

    from app.services.room_assignment import sync_sms_tags
    from app.db.models import TemplateSchedule
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    # 자동 확장된 멤버까지 포함해서 sync (linked_ids 는 확장 후 전체)
    for res_id in linked_ids:
        sync_sms_tags(db, res_id, schedules=schedules)

    db.commit()

    diag(
        "stay_group.link_api.done",
        level="critical",
        group_id=group_id,
        member_count=len(linked_ids),
        actor=current_user.username if current_user else None,
    )

    return {"success": True, "message": f"연박 그룹 생성: {group_id}"}


@router.delete("/{reservation_id}/stay-group/unlink", response_model=ActionResponse)
async def unlink_stay_group(
    reservation_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a reservation from its consecutive stay group."""
    from app.services.consecutive_stay import unlink_from_group
    from app.services.room_assignment import sync_sms_tags
    from app.db.models import TemplateSchedule, Reservation

    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    affected_ids = []
    if res and res.stay_group_id:
        affected_ids = [r.id for r in db.query(Reservation).filter(
            Reservation.stay_group_id == res.stay_group_id
        ).all()]

    unlinked = unlink_from_group(db, reservation_id, exclude_from_auto_link=True)
    if not unlinked:
        diag("stay_group.unlink_api.not_in_group", level="critical",
             reservation_id=reservation_id)
        raise HTTPException(status_code=404, detail="연박 그룹에 속하지 않은 예약입니다")

    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    for res_id in affected_ids:
        sync_sms_tags(db, res_id, schedules=schedules)

    db.commit()

    diag(
        "stay_group.unlink_api.done",
        level="critical",
        reservation_id=reservation_id,
        affected_count=len(affected_ids),
        actor=current_user.username if current_user else None,
    )

    return {"success": True, "message": "연박 그룹에서 해제되었습니다"}


@router.post("/{reservation_id}/extend-stay", response_model=ExtendStayResponse)
async def extend_stay(
    reservation_id: int,
    request: ExtendStayRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박추가: 다음날 예약 생성 + 연박 그룹 연결 + 방 배정 (단일 트랜잭션)"""
    from app.services.consecutive_stay import link_reservations
    from app.services.room_assignment import sync_sms_tags, assign_room
    from app.db.models import TemplateSchedule
    from datetime import timedelta, date as date_type

    # 1. 원본 예약 조회
    original = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # 1-1. 변환 전 그룹 상태 캡처 (link_reservations 이후 manual- 로 바뀌므로 미리 저장)
    original_group_id_before = original.stay_group_id
    if original_group_id_before is None:
        original_group_kind = "none"
    elif original_group_id_before.startswith("manual-"):
        original_group_kind = "manual"
    else:
        original_group_kind = "naver_auto"

    # 2. 다음날 날짜 계산
    orig_date = date_type.fromisoformat(original.check_in_date)
    next_date = orig_date + timedelta(days=1)
    next_date_str = next_date.isoformat()
    next_checkout = (next_date + timedelta(days=1)).isoformat()

    # 3. 다음날 예약 생성 (이름, 전화, 인원만 복사)
    new_res = Reservation(
        customer_name=original.customer_name,
        phone=original.phone,
        check_in_date=next_date_str,
        check_in_time=original.check_in_time or "15:00",
        check_out_date=next_checkout,
        male_count=original.male_count,
        female_count=original.female_count,
        party_size=original.party_size,
        gender=original.gender,
        booking_source="extend",
        naver_room_type="수동연박",
        section="room" if request.room_id else "unassigned",
        status=ReservationStatus.CONFIRMED,
    )
    db.add(new_res)
    db.flush()  # Get new_res.id

    # 4. 연박 그룹 연결
    all_ids = [reservation_id, new_res.id]
    if original.stay_group_id:
        group_members = db.query(Reservation.id).filter(
            Reservation.stay_group_id == original.stay_group_id
        ).all()
        all_ids = list(set([m[0] for m in group_members] + [new_res.id]))

    try:
        group_id, linked_ids = link_reservations(db, all_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 5. SMS 태그 동기화 (자동 확장된 멤버까지 포함)
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    for res_id in linked_ids:
        sync_sms_tags(db, res_id, schedules=schedules)

    from app.db.tenant_context import get_session_tenant_id
    tid = get_session_tenant_id(db)

    # 6. 방 배정 + 충돌 확인
    conflict_guests = []
    if request.room_id:
        existing = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == next_date_str,
                RoomAssignment.room_id == request.room_id,
                RoomAssignment.tenant_id == tid,
            )
            .all()
        )
        if existing:
            conflict_guests = [
                db.query(Reservation.customer_name)
                .filter(Reservation.id == ra.reservation_id, Reservation.tenant_id == tid)
                .scalar() or "Unknown"
                for ra in existing
            ]
        if not conflict_guests:
            assign_room(
                db, new_res.id, request.room_id, next_date_str,
                assigned_by="manual",
                created_by=current_user.username,
            )

    db.commit()

    diag(
        "reservation.extend_stay",
        level="critical",
        source_reservation_id=reservation_id,
        new_reservation_id=new_res.id,
        stay_group_id=group_id,
        original_stay_group_id=original_group_id_before,
        original_group_kind=original_group_kind,
        conflict_count=len(conflict_guests),
        room_id=request.room_id,
        actor=current_user.username if current_user else None,
    )

    return ExtendStayResponse(
        success=True,
        new_reservation_id=new_res.id,
        stay_group_id=group_id,
        conflict_guests=conflict_guests,
    )


@router.post("/{reservation_id}/extend-stay/assign-room", response_model=ActionResponse)
async def extend_stay_assign_room(
    reservation_id: int,
    request: ExtendStayAssignRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박추가 충돌 해결: 방 배정 확정"""
    from app.services.room_assignment import assign_room
    from app.db.tenant_context import get_session_tenant_id
    tid = get_session_tenant_id(db)

    if request.move_existing_to_unassigned:
        existing = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == request.date,
                RoomAssignment.room_id == request.room_id,
                RoomAssignment.reservation_id != request.new_reservation_id,
                RoomAssignment.tenant_id == tid,
            )
            .all()
        )
        for ra in existing:
            res = db.query(Reservation).filter(Reservation.id == ra.reservation_id, Reservation.tenant_id == tid).first()
            if res:
                res.section = "unassigned"
            db.delete(ra)
        db.flush()

    assign_room(
        db, request.new_reservation_id, request.room_id, request.date,
        assigned_by="manual",
        created_by=current_user.username,
    )

    db.commit()
    return {"success": True, "message": "방 배정 완료"}


@router.delete("/{reservation_id}/extend-stay", response_model=ActionResponse)
async def cancel_extend_stay(
    reservation_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박취소: 수동연박 예약 삭제 + 연박 그룹 해제 + 원본 복원"""
    from app.services.consecutive_stay import unlink_from_group
    from app.services.room_assignment import sync_sms_tags
    from app.db.models import TemplateSchedule

    original = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    if not original.stay_group_id:
        raise HTTPException(status_code=400, detail="연박 그룹이 없습니다")

    # Find the extended reservation in the same stay group (booking_source='extend', next day)
    extended = (
        db.query(Reservation)
        .filter(
            Reservation.stay_group_id == original.stay_group_id,
            Reservation.booking_source == "extend",
            Reservation.id != reservation_id,
        )
        .order_by(Reservation.check_in_date.desc())
        .first()
    )

    if not extended:
        raise HTTPException(status_code=400, detail="수동연박 예약을 찾을 수 없습니다 (수동연박만 취소 가능)")

    from app.db.tenant_context import get_session_tenant_id
    tid = get_session_tenant_id(db)

    # 1. Delete room assignments for the extended reservation
    from app.services.room_assignment import clear_all_for_reservation
    clear_all_for_reservation(db, extended.id)

    # 2. Delete SMS assignments for the extended reservation
    db.query(ReservationSmsAssignment).filter(ReservationSmsAssignment.reservation_id == extended.id, ReservationSmsAssignment.tenant_id == tid).delete()

    # 3. Delete daily info for the extended reservation
    db.query(ReservationDailyInfo).filter(ReservationDailyInfo.reservation_id == extended.id, ReservationDailyInfo.tenant_id == tid).delete()

    # 4. Unlink the extended reservation from stay group (this also fixes remaining members)
    unlink_from_group(db, extended.id)

    # 5. Delete the extended reservation
    db.delete(extended)
    db.flush()

    # 6. Sync SMS tags for remaining group members
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    # Get remaining group members (if any)
    if original.stay_group_id:
        remaining = db.query(Reservation.id).filter(
            Reservation.stay_group_id == original.stay_group_id
        ).all()
        for (rid,) in remaining:
            sync_sms_tags(db, rid, schedules=schedules)
    # Also sync the original (it may have been unlinked if group dissolved)
    sync_sms_tags(db, original.id, schedules=schedules)

    db.commit()

    diag(
        "reservation.extend_stay_cancelled",
        level="critical",
        original_reservation_id=reservation_id,
        removed_reservation_id=extended.id,
        stay_group_id=original.stay_group_id,
        actor=current_user.username if current_user else None,
    )

    return {"success": True, "message": f"수동연박 취소 완료 ({extended.customer_name})"}
