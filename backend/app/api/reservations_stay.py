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
    ReservationDailyInfo, TemplateSchedule,
)
from app.auth.dependencies import get_current_user
from app.api.shared_schemas import ActionResponse
from app.diag_logger import diag


router = APIRouter(prefix="/api/reservations", tags=["reservations"])


# ---------------------------------------------------------------------------
# Consecutive stay (연박) endpoints
# ---------------------------------------------------------------------------


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
    move_existing_to_unassigned: bool = False


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


# removed in extend-stay refactor 2026-05-09:
#   link_stay_group  (POST /{reservation_id}/stay-group/link)
#   unlink_stay_group (DELETE /{reservation_id}/stay-group/unlink)
# Users no longer manually link reservation groups. Naver auto-detection still
# works internally via detect_and_link_consecutive_stays().


@router.post("/{reservation_id}/extend-stay", response_model=ExtendStayResponse)
async def extend_stay(
    reservation_id: int,
    request: ExtendStayRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """연박추가: original reservation end_date += 1 day + room assignment for new day"""
    from app.services.room_assignment import assign_room
    from app.services.chip_reconciler import reconcile_chips_for_reservation
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
    original.check_out_date = new_end_str
    original.manually_extended_until = new_end_str
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()

    # 4. Assign room for the new night (only if no conflict)
    if request.room_id and not conflict_guests:
        assign_room(
            db, reservation_id, request.room_id, new_night_str,
            end_date=new_end_str,
            assigned_by="manual",
            created_by=current_user.username,
        )
        conflict_resolved = True

    # 5. Reconcile chips for the full new date range
    schedules = (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.tenant_id == tid,
            TemplateSchedule.is_active == True,
        )
        .all()
    )
    reconcile_chips_for_reservation(db, reservation_id, schedules=schedules)

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
    """연박추가 충돌 해결: 방 배정 확정 (operates on the original reservation)"""
    from app.services.room_assignment import assign_room
    from app.db.tenant_context import get_session_tenant_id

    # new_reservation_id is kept for backward compat — it IS the original reservation_id now
    target_reservation_id = request.new_reservation_id
    tid = get_session_tenant_id(db)

    if request.move_existing_to_unassigned:
        existing = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == request.date,
                RoomAssignment.room_id == request.room_id,
                RoomAssignment.reservation_id != target_reservation_id,
                RoomAssignment.tenant_id == tid,
            )
            .all()
        )
        for ra in existing:
            res = db.query(Reservation).filter(
                Reservation.id == ra.reservation_id,
                Reservation.tenant_id == tid,
            ).first()
            if res:
                res.section = "unassigned"
            db.delete(ra)
        db.flush()

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
    from app.services.chip_reconciler import reconcile_chips_for_reservation
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

    # 1. Delete room assignments for removed dates
    ra_deleted = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date.in_(dates_to_remove),
            RoomAssignment.tenant_id == tid,
        )
        .all()
    )
    room_assignments_deleted = len(ra_deleted)
    for ra in ra_deleted:
        db.delete(ra)

    # 2. Delete unsent SMS chips for removed dates (preserve sent chips)
    chips_to_check = (
        db.query(ReservationSmsAssignment)
        .filter(
            ReservationSmsAssignment.reservation_id == reservation_id,
            ReservationSmsAssignment.date.in_(dates_to_remove),
            ReservationSmsAssignment.tenant_id == tid,
        )
        .all()
    )
    chips_deleted_unsent = 0
    sent_chips_preserved = 0
    for chip in chips_to_check:
        if chip.sent_at is None:
            db.delete(chip)
            chips_deleted_unsent += 1
        else:
            # Preserve sent chips for audit
            sent_chips_preserved += 1
            diag(
                "reduce_extension.protected_chip_preserved",
                level="verbose",
                reservation_id=reservation_id,
                template_key=chip.template_key,
                date=chip.date,
                sent_at=str(chip.sent_at),
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
    from app.services.consecutive_stay import compute_is_long_stay
    original.check_out_date = new_end_str
    original.manually_extended_until = new_end_str
    original.is_long_stay = compute_is_long_stay(original)
    db.flush()

    # 6. Reconcile chips for new (shorter) date range
    schedules = (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.tenant_id == tid,
            TemplateSchedule.is_active == True,
        )
        .all()
    )
    reconcile_chips_for_reservation(db, reservation_id, schedules=schedules)

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
