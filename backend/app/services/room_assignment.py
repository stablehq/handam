"""
Centralized room assignment service.
All room assignment operations go through this module to maintain
consistency between room_assignments table and denormalized fields.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import logging

from app.db.models import RoomAssignment, Reservation, Room
from app.db.tenant_context import current_tenant_id
from app.services.activity_logger import log_activity
from app.templates.renderer import TemplateRenderer

logger = logging.getLogger(__name__)


def sync_sms_tags(db: Session, reservation_id: int, schedules=None) -> None:
    """
    Reconcile SMS tags for a reservation based on active TemplateSchedules.
    Thin wrapper delegating to chip_reconciler for unified matching and sync logic.
    """
    from app.services.chip_reconciler import reconcile_chips_for_reservation
    reconcile_chips_for_reservation(db, reservation_id, schedules)


# get_schedule_dates and _date_range moved to services/schedule_utils.py
# to break circular dependency. Re-export for backward compatibility.
from app.services.schedule_utils import get_schedule_dates, date_range as _date_range



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
    # 객실에 고정 비밀번호가 있으면 사용, 없으면 자동 생성
    password = (room_obj.door_password if room_obj.door_password else
                TemplateRenderer.generate_room_password(room_obj.room_number))

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
                raise ValueError(
                    f"Room {room_obj.room_number} is already occupied on {d} by reservation {existing.reservation_id}"
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
        assignment = RoomAssignment(
            reservation_id=reservation_id,
            date=d,
            room_id=room_id,
            room_password=password,
            assigned_by=assigned_by,
        )
        db.add(assignment)
        assignments.append(assignment)

    # Flush to persist all date records before any subsequent queries
    # (autoflush=False 환경에서 sync_denormalized_field 쿼리 전에 반드시 필요)
    db.flush()
    logger.info(f"assign_room: res={reservation_id} room={room_id} dates={dates} created={len(assignments)} assigned_by={assigned_by}")

    # Update denormalized field
    sync_denormalized_field(db, reservation)

    # Update section field
    reservation.section = 'room'

    # skip_sms_sync=True이면 태그 동기화를 건너뜀 (일괄 처리 시 사용)
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

    orphaned = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
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
