"""
Reservations API — consecutive stay (연박) endpoints
"""
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from app.api.deps import get_tenant_scoped_db
from app.db.models import (
    Reservation, User,
    ReservationSmsAssignment, RoomAssignment,
    ReservationDailyInfo,
)
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
    """연박추가: original reservation end_date += 1 day, assign room for new day"""
    room_id: Optional[int] = None  # Room to assign on next day (None = no assignment)


class ExtendStayResponse(BaseModel):
    success: bool
    reservation_id: int          # original reservation
    new_end_date: str
    conflict_guests: List[str] = []
    # Kept for backward compat with frontend (will deprecate later)
    new_reservation_id: int      # same as reservation_id
    stay_group_id: Optional[str] = None  # always None for new flow


class ExtendStayAssignRequest(BaseModel):
    new_reservation_id: int      # treated as original reservation_id (backward compat)
    room_id: int
    date: str  # YYYY-MM-DD


class ReduceExtensionRequest(BaseModel):
    days: int = 1


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

    # 5종 칩 통합 reconcile — 연박 그룹 변경으로 인한 surcharge 합산 변동 등
    # 4종 칩 정대 보장 (sync-sms-tags PR1).
    from app.services.reconcile import reconcile_all_chips
    for res_id in linked_ids:
        reconcile_all_chips(db, res_id)

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

    # 5종 칩 통합 reconcile — unlink 후 affected res 들의 4종 칩 stale 방지
    # (sync-sms-tags PR1).
    from app.services.reconcile import reconcile_all_chips
    for res_id in affected_ids:
        reconcile_all_chips(db, res_id)

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
    """연박추가: original reservation end_date += 1 day + room assignment for new day"""
    from app.services.room_assignment import assign_room
    from app.db.tenant_context import get_session_tenant_id
    from datetime import timedelta, date as date_type

    _t0 = time.monotonic()

    # 1. Load original reservation
    original = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    current_end = original.check_out_date
    # New night = current checkout date (last night of new stay)
    # e.g. checkout=2026-05-10 → new night stays 2026-05-10, new checkout=2026-05-11
    if not current_end:
        raise HTTPException(status_code=400, detail="check_out_date가 없는 예약입니다")

    new_end_dt = date_type.fromisoformat(current_end) + timedelta(days=1)
    new_end_str = new_end_dt.isoformat()
    # The new night to assign is current_end (the added night)
    new_night_str = current_end

    diag(
        "extend_stay.invoked",
        level="verbose",
        reservation_id=reservation_id,
        current_end=current_end,
        new_end=new_end_str,
        days_added=1,
        actor=current_user.username if current_user else None,
    )

    # 2. Conflict check for new night
    tid = get_session_tenant_id(db)
    conflict_guests: List[str] = []
    conflict_resolved = False

    if request.room_id:
        existing_assignments = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == new_night_str,
                RoomAssignment.room_id == request.room_id,
                RoomAssignment.tenant_id == tid,
            )
            .all()
        )
        if existing_assignments:
            conflict_guests = [
                db.query(Reservation.customer_name)
                .filter(Reservation.id == ra.reservation_id, Reservation.tenant_id == tid)
                .scalar() or "Unknown"
                for ra in existing_assignments
            ]

    # 3. Extend end_date
    from app.services.consecutive_stay import compute_is_long_stay
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(db, original, ChangeSource.MANUAL, {"check_out_date": new_end_str})
    original.manually_extended_until = new_end_str
    original.check_out_pinned = True  # Mutator MANUAL→자동 True, 안전망으로 명시 유지
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()

    # 4. Assign room for the new night (only if no conflict)
    if request.room_id and not conflict_guests:
        _result = assign_room(
            db, reservation_id, request.room_id, new_night_str,
            end_date=new_end_str,
            assigned_by="manual",
            created_by=current_user.username,
        )
        conflict_resolved = True
        # lifecycle 단계 #16: on_room_assigned (push-out 예약 칩 재계산 포함)
        from app.services.reservation_lifecycle import on_room_assigned
        _pushed_out = _result[1] if isinstance(_result, tuple) else None
        on_room_assigned(db, original, pushed_out=_pushed_out)

    # 5. lifecycle 단계 #16: on_dates_changed (shift_daily + reconcile_dates + reconcile_all_chips 5종)
    from app.services.reservation_lifecycle import on_dates_changed
    on_dates_changed(db, original, original.check_in_date, current_end)

    db.commit()

    duration_ms = int((time.monotonic() - _t0) * 1000)
    diag(
        "extend_stay.completed",
        level="critical",
        reservation_id=reservation_id,
        old_end=current_end,
        new_end=new_end_str,
        room_id=request.room_id,
        conflict_resolved=conflict_resolved,
        duration_ms=duration_ms,
        actor=current_user.username if current_user else None,
    )

    return ExtendStayResponse(
        success=True,
        reservation_id=reservation_id,
        new_end_date=new_end_str,
        conflict_guests=conflict_guests,
        new_reservation_id=reservation_id,
        stay_group_id=None,
    )


@router.post("/{reservation_id}/extend-stay/assign-room", response_model=ActionResponse)
async def extend_stay_assign_room(
    reservation_id: int,
    request: ExtendStayAssignRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박추가 충돌 해결: 방 배정 확정 (operates on the original reservation).

    수동 배정은 항상 공동 점유 허용. 운영자가 의도적으로 같은 방에 배정하는 경우
    기존자를 밀어내지 않고 같은 셀에 공존 (RoomAssignment unique 는 (res_id, date) 만).
    """
    from app.services.room_assignment import assign_room

    # new_reservation_id is kept for backward compat — it IS the original reservation_id now
    target_reservation_id = request.new_reservation_id

    assign_room(
        db, target_reservation_id, request.room_id, request.date,
        assigned_by="manual",
        created_by=current_user.username,
    )

    db.commit()
    return {"success": True, "message": "방 배정 완료"}


# ---------------------------------------------------------------------------
# reduce-extension: shrink a manually extended reservation
# ---------------------------------------------------------------------------

def _do_reduce_extension(
    db: Session,
    reservation_id: int,
    days: int,
    actor: Optional[str],
) -> dict:
    """Core logic shared by reduce_extension and cancel_extend_stay (compat wrapper).

    Returns a dict with stats for diag logging.
    """
    from app.db.tenant_context import get_session_tenant_id
    from datetime import timedelta, date as date_type

    _t0 = time.monotonic()

    original = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    if not original.manually_extended_until:
        raise HTTPException(status_code=400, detail="수동 연박 연장이 없습니다")

    if not original.check_out_date:
        raise HTTPException(status_code=400, detail="check_out_date가 없는 예약입니다")

    current_end_dt = date_type.fromisoformat(original.check_out_date)
    new_end_dt = current_end_dt - timedelta(days=days)

    # Must stay at least 1 night
    check_in_dt = date_type.fromisoformat(original.check_in_date)
    if new_end_dt <= check_in_dt:
        raise HTTPException(
            status_code=400,
            detail=f"연박 축소 후 체크아웃 날짜({new_end_dt})가 체크인({check_in_dt}) 이하가 됩니다",
        )

    new_end_str = new_end_dt.isoformat()
    current_end_str = original.check_out_date

    diag(
        "reduce_extension.invoked",
        level="verbose",
        reservation_id=reservation_id,
        current_end=current_end_str,
        new_end=new_end_str,
        days=days,
        actor=actor,
    )

    tid = get_session_tenant_id(db)

    # Dates to remove: [new_end_str, current_end_str)
    # These are the date strings for nights being removed
    dates_to_remove = []
    d = new_end_dt
    while d < current_end_dt:
        dates_to_remove.append(d.isoformat())
        d += timedelta(days=1)

    # 1. Delete room assignments for removed dates (lifecycle 단계 #3)
    from app.services.room_assignment import unassign_dates
    room_assignments_deleted = unassign_dates(db, reservation_id, dates_to_remove)

    # 2. Delete unsent SMS chips for removed dates (preserve sent chips for audit).
    # chip_store 위임 (PR10) — force=True (manual/excluded/failed 도 cascade,
    # 사라진 날짜의 칩은 모두 obsolete) + protect_sent=True (이력 보존).
    # protected_chip_preserved diag 는 pre-SELECT 로 보존.
    sent_chips = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.date.in_(dates_to_remove),
            ReservationSmsAssignment.tenant_id == tid,
            ReservationSmsAssignment.sent_at.isnot(None),
        )
        .all()
    )
    sent_chips_preserved = len(sent_chips)
    for chip in sent_chips:
        diag(
            "reduce_extension.protected_chip_preserved",
            level="verbose",
            reservation_id=reservation_id,
            template_key=chip.template_key,
            date=chip.date,
            sent_at=str(chip.sent_at),
        )
    from app.services.chip_store import delete_chips_for_reservation
    chips_deleted_unsent = delete_chips_for_reservation(
        db,
        reservation_id=reservation_id,
        dates=dates_to_remove,
        force=True,
        protect_sent=True,
    )

    # 3. Delete ReservationDailyInfo for removed dates
    db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.date.in_(dates_to_remove),
        ReservationDailyInfo.tenant_id == tid,
    ).delete(synchronize_session=False)

    # 4. Delete PartyCheckin for removed dates (import here to avoid circular)
    try:
        from app.db.models import PartyCheckin
        db.query(PartyCheckin).filter(
            PartyCheckin.reservation_id == reservation_id,
            PartyCheckin.date.in_(dates_to_remove),
            PartyCheckin.tenant_id == tid,
        ).delete(synchronize_session=False)
    except Exception:
        pass  # PartyCheckin may not exist in all environments

    # 5. Update reservation dates
    from datetime import date as date_type
    from app.services.consecutive_stay import compute_is_long_stay
    new_end_dt = date_type.fromisoformat(new_end_str)
    check_in_dt = date_type.fromisoformat(original.check_in_date)
    days_remaining = (new_end_dt - check_in_dt).days

    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(db, original, ChangeSource.MANUAL, {"check_out_date": new_end_str})
    # Clear flag when fully retracted to a 1-night (or shorter) stay — naver_sync resumes normal sync
    if days_remaining <= 1:
        original.manually_extended_until = None
        # PR1-fix: pin 컬럼 + 방명록 dict 둘 다 클리어 (naver_sync 재차단 방지)
        ReservationMutator.release_manual_pin(original, "check_out_date")
        diag(
            "reduce_extension.flag_cleared",
            level="critical",
            reservation_id=reservation_id,
            new_end=new_end_str,
            days_remaining=days_remaining,
        )
    else:
        original.manually_extended_until = new_end_str
        original.check_out_pinned = True
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()

    # 6. lifecycle 단계 #17: on_dates_changed (shift_daily + reconcile_dates + reconcile_all_chips 5종)
    from app.services.reservation_lifecycle import on_dates_changed
    on_dates_changed(db, original, original.check_in_date, current_end_str)

    duration_ms = int((time.monotonic() - _t0) * 1000)
    diag(
        "reduce_extension.completed",
        level="critical",
        reservation_id=reservation_id,
        old_end=current_end_str,
        new_end=new_end_str,
        chips_deleted_unsent=chips_deleted_unsent,
        sent_chips_preserved=sent_chips_preserved,
        room_assignments_deleted=room_assignments_deleted,
        duration_ms=duration_ms,
        actor=actor,
    )

    return {
        "chips_deleted_unsent": chips_deleted_unsent,
        "sent_chips_preserved": sent_chips_preserved,
        "room_assignments_deleted": room_assignments_deleted,
        "new_end_date": new_end_str,
    }


@router.post("/{reservation_id}/reduce-extension", response_model=ActionResponse)
async def reduce_extension(
    reservation_id: int,
    request: ReduceExtensionRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박 축소: manually_extended reservation 의 end_date를 N일 줄임"""
    stats = _do_reduce_extension(
        db, reservation_id, days=request.days,
        actor=current_user.username if current_user else None,
    )
    db.commit()
    return {
        "success": True,
        "message": (
            f"연박 {request.days}일 축소 완료 → 체크아웃: {stats['new_end_date']}"
            f" (삭제 칩 {stats['chips_deleted_unsent']}건, 보존 {stats['sent_chips_preserved']}건)"
        ),
    }


@router.delete("/{reservation_id}/extend-stay", response_model=ActionResponse)
async def cancel_extend_stay(
    reservation_id: int,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박취소 (backward compat): reduce-extension days=1 위임"""
    stats = _do_reduce_extension(
        db, reservation_id, days=1,
        actor=current_user.username if current_user else None,
    )
    db.commit()
    return {
        "success": True,
        "message": (
            f"수동연박 취소 완료 → 체크아웃: {stats['new_end_date']}"
            f" (삭제 칩 {stats['chips_deleted_unsent']}건)"
        ),
    }
