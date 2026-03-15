"""
Room auto-assignment scheduler job.
Runs daily to assign rooms for today and tomorrow.
Manual assignments (assigned_by='manual') are never overwritten.

Dormitory logic:
- Dormitory rooms are NOT 1:1 matched to reservations.
- Guests are split by gender (no mixed rooms).
- Rooms are allocated to the gender with more people first.
- Each room is filled up to dormitory_beds capacity.
"""
from datetime import datetime, timedelta
from math import ceil
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import logging

from app.db.models import Reservation, Room, RoomAssignment, ReservationStatus
from app.services import room_assignment

logger = logging.getLogger(__name__)


def auto_assign_rooms(db: Session, target_date: str = None):
    """
    Auto-assign rooms for target_date (defaults to today).
    1. Assign regular (non-dormitory) rooms first.
    2. Then assign dormitory rooms by gender grouping.
    Never touches manual assignments.
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Starting room auto-assignment for {target_date}")

    # Get rooms with biz_item_id linked
    rooms_with_biz = (
        db.query(Room)
        .filter(Room.naver_biz_item_id.isnot(None), Room.is_active == True)
        .order_by(Room.sort_order)
        .all()
    )
    if not rooms_with_biz:
        logger.info("No rooms with biz_item_id found, skipping auto-assign")
        return {"target_date": target_date, "assigned": 0, "unassigned": 0}

    # Split rooms into regular and dormitory
    regular_rooms: List[Room] = []
    dormitory_rooms: List[Room] = []
    for room in rooms_with_biz:
        if room.is_dormitory:
            dormitory_rooms.append(room)
        else:
            regular_rooms.append(room)

    # Build biz_item_id -> rooms mapping (regular only)
    biz_to_regular = {}
    for room in regular_rooms:
        biz_to_regular.setdefault(room.naver_biz_item_id, []).append(room)

    # Get all unassigned confirmed reservations for target_date
    unassigned = _get_unassigned_reservations(db, target_date)

    # Separate into regular and dormitory candidates
    regular_candidates = []
    dormitory_candidates = []
    dormitory_biz_ids = {r.naver_biz_item_id for r in dormitory_rooms}

    for res in unassigned:
        if res.naver_biz_item_id in dormitory_biz_ids:
            dormitory_candidates.append(res)
        else:
            regular_candidates.append(res)

    assigned_count = 0

    # === Step 1: Regular room assignment ===
    assigned_count += _assign_regular_rooms(
        db, regular_candidates, biz_to_regular, target_date
    )

    # === Step 2: Dormitory room assignment ===
    assigned_count += _assign_dormitory_rooms(
        db, dormitory_candidates, dormitory_rooms, target_date
    )

    db.commit()

    result = {
        "target_date": target_date,
        "assigned": assigned_count,
        "unassigned": len(unassigned) - assigned_count,
    }
    logger.info(f"Room auto-assignment complete: {result}")
    return result


def _get_unassigned_reservations(db: Session, target_date: str) -> List[Reservation]:
    """Get confirmed reservations with no assignment for target_date."""
    unassigned = (
        db.query(Reservation)
        .filter(
            Reservation.naver_biz_item_id.isnot(None),
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.date <= target_date,
        )
        .filter(
            ~Reservation.id.in_(
                db.query(RoomAssignment.reservation_id).filter(
                    RoomAssignment.date == target_date
                )
            )
        )
        .all()
    )
    # Filter to only those actually active on target_date
    return [
        r for r in unassigned
        if r.end_date is None or r.end_date > target_date or r.date == target_date
    ]


def _assign_regular_rooms(
    db: Session,
    candidates: List[Reservation],
    biz_to_rooms: Dict[str, List[Room]],
    target_date: str,
) -> int:
    """
    Assign regular (non-dormitory) rooms. One room per reservation.
    Uses db.flush() after each assignment to prevent double-booking.
    """
    assigned_count = 0

    for res in candidates:
        candidate_rooms = biz_to_rooms.get(res.naver_biz_item_id, [])
        if not candidate_rooms:
            continue

        for room in candidate_rooms:
            if room_assignment.check_capacity_all_dates(
                db, room.room_number, target_date, res.end_date,
                people_count=1, exclude_reservation_id=res.id
            ):
                room_assignment.assign_room(
                    db, res.id, room.room_number, target_date, res.end_date,
                    assigned_by="auto"
                )
                db.flush()  # flush 해야 다음 반복에서 이 배정이 보임
                assigned_count += 1
                break

    return assigned_count


def _assign_dormitory_rooms(
    db: Session,
    candidates: List[Reservation],
    dormitory_rooms: List[Room],
    target_date: str,
) -> int:
    """
    Assign dormitory rooms by gender grouping.
    - Split guests by gender
    - Allocate rooms to each gender group
    - Fill rooms up to dormitory_beds capacity
    - No mixed-gender rooms
    """
    if not candidates or not dormitory_rooms:
        return 0

    # Split by gender
    male_reservations = []
    female_reservations = []
    for res in candidates:
        gender = (res.gender or "").strip()
        if gender == "남":
            male_reservations.append(res)
        elif gender == "여":
            female_reservations.append(res)
        else:
            # Unknown gender: skip (can't assign to dormitory without gender)
            logger.warning(f"Reservation {res.id} ({res.customer_name}) has no gender, skipping dormitory assignment")

    # Count total people per gender
    def count_people(reservations):
        return sum(r.party_participants or r.booking_count or 1 for r in reservations)

    male_total = count_people(male_reservations)
    female_total = count_people(female_reservations)

    logger.info(f"Dormitory assignment: 남 {male_total}명 ({len(male_reservations)}건), 여 {female_total}명 ({len(female_reservations)}건)")

    # Get already manually assigned dormitory rooms for this date (exclude from pool)
    manually_assigned_rooms = set()
    manual_assignments = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.date == target_date,
            RoomAssignment.assigned_by == "manual",
            RoomAssignment.room_number.in_([r.room_number for r in dormitory_rooms]),
        )
        .all()
    )
    for ma in manual_assignments:
        manually_assigned_rooms.add(ma.room_number)

    # Available dormitory rooms (not manually assigned)
    available_rooms = [r for r in dormitory_rooms if r.room_number not in manually_assigned_rooms]

    if not available_rooms:
        logger.info("No available dormitory rooms (all manually assigned)")
        return 0

    # Sort by sort_order
    available_rooms.sort(key=lambda r: r.sort_order)

    # Calculate rooms needed per gender
    # Use the first room's bed count as reference (assume uniform)
    bed_count = available_rooms[0].dormitory_beds if available_rooms else 4

    female_rooms_needed = ceil(female_total / bed_count) if female_total > 0 else 0
    male_rooms_needed = ceil(male_total / bed_count) if male_total > 0 else 0

    # If not enough rooms, allocate proportionally
    total_rooms_needed = female_rooms_needed + male_rooms_needed
    total_available = len(available_rooms)

    if total_rooms_needed > total_available:
        # Proportional allocation
        if female_total + male_total > 0:
            female_rooms_needed = round(total_available * female_total / (female_total + male_total))
            male_rooms_needed = total_available - female_rooms_needed
        else:
            female_rooms_needed = 0
            male_rooms_needed = 0

    # Allocate rooms: more people gender gets first pick
    if female_total >= male_total:
        female_room_list = available_rooms[:female_rooms_needed]
        male_room_list = available_rooms[female_rooms_needed:female_rooms_needed + male_rooms_needed]
    else:
        male_room_list = available_rooms[:male_rooms_needed]
        female_room_list = available_rooms[male_rooms_needed:male_rooms_needed + female_rooms_needed]

    logger.info(f"Dormitory room allocation: 여 {len(female_room_list)}개 방, 남 {len(male_room_list)}개 방")

    assigned_count = 0

    # Assign female guests
    assigned_count += _fill_dormitory_rooms(
        db, female_reservations, female_room_list, target_date
    )

    # Assign male guests
    assigned_count += _fill_dormitory_rooms(
        db, male_reservations, male_room_list, target_date
    )

    return assigned_count


def _fill_dormitory_rooms(
    db: Session,
    reservations: List[Reservation],
    rooms: List[Room],
    target_date: str,
) -> int:
    """
    Fill dormitory rooms with reservations, respecting bed count capacity.
    Packs guests into rooms sequentially.
    """
    if not reservations or not rooms:
        return 0

    assigned_count = 0
    room_idx = 0
    room_occupancy = 0  # Current occupancy of current room

    for res in reservations:
        if room_idx >= len(rooms):
            logger.warning(f"No more dormitory rooms available for reservation {res.id}")
            break

        current_room = rooms[room_idx]
        people = res.party_participants or res.booking_count or 1

        # Check if this reservation fits in current room
        if room_occupancy + people > current_room.dormitory_beds:
            # Move to next room
            room_idx += 1
            room_occupancy = 0
            if room_idx >= len(rooms):
                logger.warning(f"No more dormitory rooms available for reservation {res.id}")
                break
            current_room = rooms[room_idx]

        # Assign
        room_assignment.assign_room(
            db, res.id, current_room.room_number, target_date, res.end_date,
            assigned_by="auto"
        )
        db.flush()
        room_occupancy += people
        assigned_count += 1

        # If room is full, move to next
        if room_occupancy >= current_room.dormitory_beds:
            room_idx += 1
            room_occupancy = 0

    return assigned_count


def daily_assign_rooms(db: Session):
    """
    Daily job: auto-assign rooms for today and tomorrow.
    Only fills in missing assignments, never overwrites manual ones.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Running daily room assignment for {today} and {tomorrow}")

    result_today = auto_assign_rooms(db, today)
    result_tomorrow = auto_assign_rooms(db, tomorrow)

    return {
        "today": result_today,
        "tomorrow": result_tomorrow,
    }
