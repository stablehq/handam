"""
Centralized room assignment service.
All room assignment operations go through this module to maintain
consistency between room_assignments table and denormalized fields.
"""
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import logging

from app.db.models import RoomAssignment, Reservation, Room
from app.db.tenant_context import current_tenant_id
from app.services.activity_logger import log_activity

logger = logging.getLogger(__name__)


def _compute_bed_order(db: Session, reservation_id: int, room_id: int, date_str: str, room_obj: Room) -> int:
    """도미토리 배정 시 bed_order를 계산한다.

    1. 전날 같은 방에 같은 reservation_id 배정 → 그 bed_order 재사용
    2. 전날 같은 방에 같은 stay_group_id 배정 → 그 bed_order 재사용
    3. 둘 다 없으면 → 해당 room+date의 기존 bed_order 중 빈 슬롯 (1부터)
    """
    if not room_obj.is_dormitory:
        return 0

    prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1) 같은 reservation_id로 전날 같은 방 배정 확인 (2박+ 단일 예약)
    prev_same = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.room_id == room_id,
        RoomAssignment.date == prev_date,
    ).first()
    if prev_same and prev_same.bed_order > 0:
        return prev_same.bed_order

    # 2) stay_group_id로 전날 같은 방 배정 확인 (연박 체인)
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation and reservation.stay_group_id:
        group_members = db.query(Reservation.id).filter(
            Reservation.stay_group_id == reservation.stay_group_id,
            Reservation.id != reservation_id,
        ).all()
        member_ids = [m.id for m in group_members]
        if member_ids:
            prev_group = db.query(RoomAssignment).filter(
                RoomAssignment.reservation_id.in_(member_ids),
                RoomAssignment.room_id == room_id,
                RoomAssignment.date == prev_date,
            ).first()
            if prev_group and prev_group.bed_order > 0:
                return prev_group.bed_order

    # 3) 빈 슬롯 찾기: 해당 room+date + 전날 연박자의 bed_order도 예약으로 간주
    taken = {
        row.bed_order for row in
        db.query(RoomAssignment.bed_order).filter(
            RoomAssignment.room_id == room_id,
            RoomAssignment.date == date_str,
            RoomAssignment.bed_order > 0,
        ).all()
    }
    # 전날 같은 방의 연박자 bed_order도 taken에 포함 (다음날 배정이 아직 안 만들어진 경우 대비)
    prev_assignments = db.query(RoomAssignment.bed_order, RoomAssignment.reservation_id).filter(
        RoomAssignment.room_id == room_id,
        RoomAssignment.date == prev_date,
        RoomAssignment.bed_order > 0,
    ).all()
    for pa in prev_assignments:
        prev_res = db.query(Reservation).filter(Reservation.id == pa.reservation_id).first()
        if prev_res and prev_res.check_out_date and prev_res.check_out_date > date_str:
            taken.add(pa.bed_order)
    order = 1
    while order in taken:
        order += 1
    return order


def sync_sms_tags(db: Session, reservation_id: int, schedules=None) -> None:
    """
    Reconcile SMS tags for a reservation based on active TemplateSchedules.
    Thin wrapper delegating to chip_reconciler for unified matching and sync logic.
    """
    from app.services.chip_reconciler import reconcile_chips_for_reservation
    reconcile_chips_for_reservation(db, reservation_id, schedules)


# _date_range moved to services/schedule_utils.py
# to break circular dependency. Re-export for backward compatibility.
from app.services.schedule_utils import date_range as _date_range



def assign_room(
    db: Session,
    reservation_id: int,
    room_id: int,
    from_date: str,
    end_date: Optional[str] = None,
    assigned_by: str = "auto",
    skip_sms_sync: bool = False,
    created_by: Optional[str] = None,
    skip_logging: bool = False,
) -> List[RoomAssignment]:
    """
    Assign a room for date range [from_date, end_date).
    Creates RoomAssignment records for each date.
    For non-dormitory rooms, uses SELECT FOR UPDATE to prevent double-booking.
    Does NOT overwrite records for dates before from_date.
    """
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise ValueError(f"Reservation {reservation_id} not found")

    room_obj = db.query(Room).filter(Room.id == room_id, Room.is_active == True).first()
    if not room_obj:
        raise ValueError("Room not found")

    dates = _date_range(from_date, end_date)
    is_dorm = room_obj.is_dormitory
    # 객실에 설정된 비밀번호 사용 (없으면 빈 문자열)
    password = room_obj.door_password or ""

    # Concurrency guard for non-dormitory rooms
    if not is_dorm:
        for d in dates:
            existing = (
                db.query(RoomAssignment)
                .filter(
                    RoomAssignment.date == d,
                    RoomAssignment.room_id == room_id,
                    RoomAssignment.reservation_id != reservation_id,
                )
                .with_for_update()
                .first()
            )
            if existing:
                if assigned_by == "auto":
                    raise ValueError(
                        f"Room {room_obj.room_number} is already occupied on {d} by reservation {existing.reservation_id}"
                    )
                # 수동배정: 잠금은 유지한 채 경고 로그만 남기고 진행
                logger.warning(
                    f"Manual multi-assign: room {room_obj.room_number} on {d} "
                    f"already has reservation {existing.reservation_id}, "
                    f"adding reservation {reservation_id} (by {assigned_by})"
                )

    # Capture old room for move logging
    old_assignments = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date.in_(dates),
        )
        .all()
    )
    old_room_display = old_assignments[0].room.room_number if old_assignments and old_assignments[0].room else None

    # Delete existing assignments for this reservation in the date range (현재 테넌트만)
    tid = current_tenant_id.get()
    db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.date.in_(dates),
        RoomAssignment.tenant_id == tid,
    ).delete(synchronize_session="fetch")

    new_room_display = room_obj.room_number

    # Log room move/assignment (skip when caller will log in bulk)
    if not skip_logging:
        log_creator = created_by or ("system" if assigned_by == "auto" else assigned_by)
        if old_room_display and old_room_display != new_room_display:
            log_activity(
                db, type="room_move",
                title=f"[{reservation.customer_name}] 객실이동 {old_room_display} → {new_room_display}",
                detail={
                    "reservation_id": reservation_id,
                    "move_type": assigned_by,
                    "customer_name": reservation.customer_name,
                    "dates": dates,
                    "old_room": old_room_display,
                    "new_room": new_room_display,
                },
                created_by=log_creator,
            )
        elif not old_room_display:
            log_activity(
                db, type="room_move",
                title=f"[{reservation.customer_name}] 객실배정 {new_room_display}",
                detail={
                    "reservation_id": reservation_id,
                    "move_type": assigned_by,
                    "customer_name": reservation.customer_name,
                    "dates": dates,
                    "old_room": None,
                    "new_room": new_room_display,
                },
                created_by=log_creator,
            )

    # Create new assignments
    assignments = []
    for d in dates:
        bed_order = _compute_bed_order(db, reservation_id, room_id, d, room_obj)
        assignment = RoomAssignment(
            reservation_id=reservation_id,
            date=d,
            room_id=room_id,
            room_password=password,
            assigned_by=assigned_by,
            bed_order=bed_order,
        )
        db.add(assignment)
        db.flush()  # 다음 날짜 계산에서 이 레코드가 보이도록
        assignments.append(assignment)

    # Flush to persist all date records before any subsequent queries
    # (autoflush=False 환경에서 sync_denormalized_field 쿼리 전에 반드시 필요)
    db.flush()
    logger.info(f"assign_room: res={reservation_id} room={room_id} dates={dates} created={len(assignments)} assigned_by={assigned_by}")

    # Update denormalized field
    sync_denormalized_field(db, reservation)

    # Update section field
    reservation.section = 'room'

    # ★ 칩 reconcile (2차): 방 배정 후 재실행
    # 이제 RoomAssignment 있으므로 building/room 필터 통과 → 칩 생성됨
    # skip_sms_sync=True이면 건너뜀 (일괄 처리 시 사용)
    if not skip_sms_sync:
        db.flush()
        sync_sms_tags(db, reservation_id)

    return assignments


def unassign_room(
    db: Session,
    reservation_id: int,
    from_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    Remove room assignments for a reservation.
    If from_date is None, clears ALL assignments.
    If from_date provided, clears [from_date, end_date) range.
    Returns count of deleted records.
    """
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        return 0

    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id
    )

    if from_date:
        dates = _date_range(from_date, end_date)
        query = query.filter(RoomAssignment.date.in_(dates))

    # Capture old room for unassign logging
    old_assignments = query.all()
    if old_assignments:
        old_room_display = old_assignments[0].room.room_number if old_assignments[0].room else None
        old_assigned_by = old_assignments[0].assigned_by
        log_activity(
            db, type="room_move",
            title=f"[{reservation.customer_name}] 객실해제 {old_room_display}",
            detail={
                "reservation_id": reservation_id,
                "move_type": old_assigned_by,
                "customer_name": reservation.customer_name,
                "dates": [a.date for a in old_assignments],
                "old_room": old_room_display,
                "new_room": None,
            },
            created_by="system" if old_assigned_by == "auto" else old_assigned_by,
        )

    # Re-query since .all() consumed the query (현재 테넌트만)
    tid = current_tenant_id.get()
    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.tenant_id == tid,
    )
    if from_date:
        query = query.filter(RoomAssignment.date.in_(dates))

    count = query.delete(synchronize_session="fetch")

    # Update denormalized field
    sync_denormalized_field(db, reservation)

    # section과 SMS 태그는 호출자가 관리 (PUT endpoint → sync_sms_tags)

    return count


def clear_all_for_reservation(db: Session, reservation_id: int) -> int:
    """Delete ALL RoomAssignment records for a reservation and clear denormalized fields."""
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    tid = current_tenant_id.get()
    count = (
        db.query(RoomAssignment)
        .filter(RoomAssignment.reservation_id == reservation_id, RoomAssignment.tenant_id == tid)
        .delete(synchronize_session="fetch")
    )
    if reservation:
        reservation.room_number = None
        reservation.room_password = None

    # section과 SMS 태그는 호출자가 관리

    return count


def sync_denormalized_field(db: Session, reservation: Reservation):
    """
    Set reservation.room_number to check-in date's room assignment.
    This is the denormalized field for backward compatibility.
    """
    assignment = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.date == reservation.check_in_date,
        )
        .first()
    )
    if assignment:
        room = db.query(Room).filter(Room.id == assignment.room_id).first()
        reservation.room_number = room.room_number if room else None
        reservation.room_password = assignment.room_password
    else:
        # Check if any assignment exists (for mid-stay changes)
        first_assignment = (
            db.query(RoomAssignment)
            .filter(RoomAssignment.reservation_id == reservation.id)
            .order_by(RoomAssignment.date)
            .first()
        )
        if first_assignment:
            room = db.query(Room).filter(Room.id == first_assignment.room_id).first()
            reservation.room_number = room.room_number if room else None
            reservation.room_password = first_assignment.room_password
        else:
            reservation.room_number = None
            reservation.room_password = None


def reconcile_dates(db: Session, reservation: Reservation):
    """
    Called when reservation dates change.
    Deletes assignments for dates no longer in [date, end_date) range.
    Does NOT auto-extend assignments.
    """
    valid_dates = set(_date_range(reservation.check_in_date, reservation.check_out_date))

    if not valid_dates:
        # check_in_date가 없는 비정상 데이터 — 삭제하지 않고 스킵
        logger.warning(f"reconcile_dates: reservation {reservation.id} has no valid dates, skipping")
        return

    tid = current_tenant_id.get()
    orphaned = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.tenant_id == tid,
            ~RoomAssignment.date.in_(valid_dates),
        )
        .all()
    )

    for assignment in orphaned:
        if assignment.date not in valid_dates:
            db.delete(assignment)

    if orphaned:
        sync_denormalized_field(db, reservation)
        logger.info(
            f"Reconciled dates for reservation {reservation.id}: "
            f"removed {len(orphaned)} orphaned assignments"
        )


def check_capacity_all_dates(
    db: Session,
    room_id: int,
    from_date: str,
    end_date: Optional[str],
    people_count: int = 1,
    exclude_reservation_id: Optional[int] = None,
) -> bool:
    """
    Check if a room has capacity for ALL dates in [from_date, end_date).
    Used by auto-assign to ensure multi-night guests get the same room every night.
    Note: For non-dormitory rooms, capacity is hardcoded to 1 (auto-assign policy).
    Manual assignments bypass this check via assign_room()'s assigned_by guard.
    """
    room = db.query(Room).filter(
        Room.id == room_id, Room.is_active == True
    ).first()
    if not room:
        return False

    dates = _date_range(from_date, end_date)
    is_dorm = room.is_dormitory
    capacity = room.bed_capacity if is_dorm else 1

    if is_dorm:
        # Batch: fetch occupancy for all dates in one JOIN + GROUP BY query
        agg_query = (
            db.query(
                RoomAssignment.date,
                func.coalesce(
                    func.sum(
                        func.coalesce(Reservation.party_size, Reservation.booking_count, 1)
                    ),
                    0,
                ).label("occupancy"),
            )
            .join(Reservation, and_(RoomAssignment.reservation_id == Reservation.id, RoomAssignment.tenant_id == Reservation.tenant_id))
            .filter(
                RoomAssignment.room_id == room_id,
                RoomAssignment.date.in_(dates),
            )
        )
        if exclude_reservation_id:
            agg_query = agg_query.filter(RoomAssignment.reservation_id != exclude_reservation_id)
        occupancy_map = {row.date: row.occupancy for row in agg_query.group_by(RoomAssignment.date).all()}

        for d in dates:
            current = occupancy_map.get(d, 0)
            if current + people_count > capacity:
                return False
    else:
        for d in dates:
            query = db.query(RoomAssignment).filter(
                RoomAssignment.date == d,
                RoomAssignment.room_id == room_id,
            )
            if exclude_reservation_id:
                query = query.filter(RoomAssignment.reservation_id != exclude_reservation_id)
            if query.count() >= capacity:
                return False

    return True
