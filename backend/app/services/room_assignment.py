"""
Centralized room assignment service.
All room assignment operations go through this module to maintain
consistency between room_assignments table and denormalized fields.
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import logging

from app.db.models import RoomAssignment, Reservation, Room, ReservationSmsAssignment, TemplateSchedule
from app.templates.renderer import TemplateRenderer

logger = logging.getLogger(__name__)


def sync_sms_tags(db: Session, reservation_id: int, schedules=None) -> None:
    """
    Reconcile SMS tags for a reservation based on active TemplateSchedules.
    Supports both legacy target_type and new filters system.
    - Creates missing tags, removes obsolete unsent tags
    - Protects: sent tags (sent_at != null), manually assigned tags (assigned_by='manual')
    """
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        return

    # Get room assignment for this reservation (source of truth)
    room_assignment_row = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.date == reservation.check_in_date,
    ).first()
    has_room = room_assignment_row is not None

    if schedules is None:
        schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()

    # Prefetch building_id once to avoid N+1 queries in _matches_filter_group
    building_id: Optional[int] = None
    if room_assignment_row:
        room = db.query(Room).filter(Room.room_number == room_assignment_row.room_number).first()
        building_id = room.building_id if room else None

    # Compute which template_keys should exist based on schedule rules
    expected_keys: set[str] = set()
    for schedule in schedules:
        if _reservation_matches_schedule(reservation, schedule, has_room, room_assignment_row, building_id):
            expected_keys.add(schedule.template.template_key)

    # Get current tags
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
    ).all()

    existing_keys = {a.template_key for a in existing}

    # Add missing tags
    for key in expected_keys:
        if key not in existing_keys:
            db.add(ReservationSmsAssignment(
                reservation_id=reservation_id,
                template_key=key,
                assigned_by='auto',
                sent_at=None,
            ))

    # Remove obsolete tags (only unsent, non-manual)
    for a in existing:
        if a.template_key not in expected_keys and a.sent_at is None and a.assigned_by != 'manual':
            db.delete(a)


def _reservation_matches_schedule(
    reservation: Reservation,
    schedule: TemplateSchedule,
    has_room: bool,
    room_assignment_row=None,
    building_id: Optional[int] = None,
) -> bool:
    """Check if a reservation matches a schedule's filters or legacy target_type.

    Uses filters (new system) if present, falls back to target_type (legacy).
    Filters logic: same type = OR, different types = AND.
    """
    import json as _json

    # Parse filters
    filters = []
    if schedule.filters:
        try:
            filters = _json.loads(schedule.filters) if isinstance(schedule.filters, str) else schedule.filters
        except (ValueError, TypeError):
            filters = []

    # If filters exist, use new system
    if filters:
        # Group by type
        groups: dict[str, list[str]] = {}
        for f in filters:
            ftype = f.get("type", "")
            fval = f.get("value", "")
            if ftype and fval:
                groups.setdefault(ftype, []).append(fval)

        # Each group must match (AND between groups)
        for ftype, values in groups.items():
            # Any value in group must match (OR within group)
            if not _matches_filter_group(reservation, ftype, values, has_room, room_assignment_row, building_id):
                return False
        return True

    # Legacy target_type fallback
    if schedule.target_type == 'all':
        return True
    elif schedule.target_type == 'room_assigned':
        return has_room
    elif schedule.target_type == 'party_only':
        tags = reservation.tags or ''
        return not has_room and '파티만' in tags
    elif schedule.target_type == 'tag':
        if not schedule.target_value:
            return False
        tags = reservation.tags or ''
        return schedule.target_value in tags

    # No filters and no target_type → match all
    return True


def _matches_filter_group(
    reservation: Reservation,
    ftype: str,
    values: list[str],
    has_room: bool,
    room_assignment_row=None,
    building_id: Optional[int] = None,
) -> bool:
    """Check if reservation matches any value in a filter group (OR logic)."""
    for value in values:
        if ftype == "assignment":
            if value == "room" and has_room:
                return True
            if value == "party":
                naver_rt = reservation.naver_room_type or ''
                if not has_room and '파티만' in naver_rt:
                    return True
            if value == "unassigned":
                naver_rt = reservation.naver_room_type or ''
                if not has_room and '파티만' not in naver_rt:
                    return True
        elif ftype == "building":
            if building_id is not None and str(building_id) == str(value):
                return True
        elif ftype == "room":
            if room_assignment_row and room_assignment_row.room_number == value:
                return True
        elif ftype == "tag":
            tags = reservation.tags or ''
            if value in tags:
                return True
    return False


def _date_range(from_date: str, end_date: Optional[str]) -> List[str]:
    """Generate list of date strings [from_date, end_date) in YYYY-MM-DD format.
    If end_date is None or same as from_date, returns [from_date].
    """
    if not end_date or end_date <= from_date:
        return [from_date]
    dates = []
    current = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current < end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates if dates else [from_date]


def _is_dormitory_room(db: Session, room_number: str) -> bool:
    """Check if a room is a dormitory room."""
    room = db.query(Room).filter(Room.room_number == room_number, Room.is_active == True).first()
    return room.is_dormitory if room else False


def assign_room(
    db: Session,
    reservation_id: int,
    room_number: str,
    from_date: str,
    end_date: Optional[str] = None,
    assigned_by: str = "auto",
    skip_sms_sync: bool = False,
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

    dates = _date_range(from_date, end_date)
    is_dorm = _is_dormitory_room(db, room_number)
    # 객실에 고정 비밀번호가 있으면 사용, 없으면 자동 생성
    room_obj = db.query(Room).filter(Room.room_number == room_number, Room.is_active == True).first()
    password = (room_obj.door_password if room_obj and room_obj.door_password else
                TemplateRenderer.generate_room_password(room_number))

    # Concurrency guard for non-dormitory rooms
    if not is_dorm:
        for d in dates:
            existing = (
                db.query(RoomAssignment)
                .filter(
                    RoomAssignment.date == d,
                    RoomAssignment.room_number == room_number,
                    RoomAssignment.reservation_id != reservation_id,
                )
                .with_for_update()
                .first()
            )
            if existing:
                raise ValueError(
                    f"Room {room_number} is already occupied on {d} by reservation {existing.reservation_id}"
                )

    # Delete existing assignments for this reservation in the date range
    db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.date.in_(dates),
    ).delete(synchronize_session="fetch")

    # Create new assignments
    assignments = []
    for d in dates:
        assignment = RoomAssignment(
            reservation_id=reservation_id,
            date=d,
            room_number=room_number,
            room_password=password,
            assigned_by=assigned_by,
        )
        db.add(assignment)
        assignments.append(assignment)

    # Update denormalized field
    sync_denormalized_field(db, reservation)

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

    count = query.delete(synchronize_session="fetch")

    # Update denormalized field
    sync_denormalized_field(db, reservation)

    # Reconcile SMS tags based on new state
    sync_sms_tags(db, reservation_id)

    return count


def get_room_for_date(
    db: Session, reservation_id: int, date: str
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (room_number, room_password) for a specific date, or (None, None)."""
    assignment = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date == date,
        )
        .first()
    )
    if assignment:
        return (assignment.room_number, assignment.room_password)
    return (None, None)


def get_occupancy(db: Session, date: str, room_number: str) -> int:
    """
    Get occupancy count for a room on a specific date.
    For non-dormitory rooms: count of assignments (should be 0 or 1).
    For dormitory rooms: sum of party_size/booking_count from reservations.
    """
    is_dorm = _is_dormitory_room(db, room_number)

    if not is_dorm:
        return (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.date == date,
                RoomAssignment.room_number == room_number,
            )
            .count()
        )

    # Dormitory: sum people from associated reservations via single JOIN + aggregate
    total = (
        db.query(
            func.coalesce(
                func.sum(
                    func.coalesce(Reservation.party_size, Reservation.booking_count, 1)
                ),
                0,
            )
        )
        .join(RoomAssignment, RoomAssignment.reservation_id == Reservation.id)
        .filter(
            RoomAssignment.date == date,
            RoomAssignment.room_number == room_number,
        )
        .scalar()
    ) or 0
    return total


def clear_all_for_reservation(db: Session, reservation_id: int) -> int:
    """Delete ALL RoomAssignment records for a reservation and clear denormalized fields."""
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    count = (
        db.query(RoomAssignment)
        .filter(RoomAssignment.reservation_id == reservation_id)
        .delete(synchronize_session="fetch")
    )
    if reservation:
        reservation.room_number = None
        reservation.room_password = None

    # Reconcile SMS tags based on new state
    sync_sms_tags(db, reservation_id)

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
        reservation.room_number = assignment.room_number
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
            reservation.room_number = first_assignment.room_number
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

    orphaned = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            ~RoomAssignment.date.in_(valid_dates) if valid_dates else True,
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
    room_number: str,
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
        Room.room_number == room_number, Room.is_active == True
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
            .join(Reservation, RoomAssignment.reservation_id == Reservation.id)
            .filter(
                RoomAssignment.room_number == room_number,
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
                RoomAssignment.room_number == room_number,
            )
            if exclude_reservation_id:
                query = query.filter(RoomAssignment.reservation_id != exclude_reservation_id)
            if query.count() >= capacity:
                return False

    return True
