"""
Room auto-assignment scheduler job.
Runs daily to assign rooms for today and tomorrow.
Manual assignments (assigned_by='manual') are never overwritten.

Dormitory logic (N:M based on Room.biz_item_links):
- Dormitory candidates identified via Room.is_dormitory + Room.biz_item_links.
- Guests are split by gender (no mixed rooms).
- Rooms are allocated to the gender with more people first.
- Each room is filled up to its bed_capacity capacity.
"""
from datetime import datetime, timedelta
from math import ceil
from typing import List, Dict
from sqlalchemy.orm import Session
import logging

from sqlalchemy import exists
from sqlalchemy.orm import selectinload
from app.db.models import Reservation, Room, RoomAssignment, ReservationStatus, TemplateSchedule, RoomBizItemLink
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

    # Get rooms with at least one biz_item linked (N:M via RoomBizItemLink)
    rooms_with_biz = (
        db.query(Room)
        .filter(
            Room.is_active == True,
            exists().where(RoomBizItemLink.room_id == Room.id),
        )
        .options(selectinload(Room.biz_item_links))
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

    # Build dormitory biz_item_ids from Room.biz_item_links (객실 기준)
    dormitory_biz_ids: set = set()
    for room in dormitory_rooms:
        for link in room.biz_item_links:
            dormitory_biz_ids.add(link.biz_item_id)

    # Build biz_item_id -> rooms mapping (regular only, N:M)
    biz_to_regular = {}
    for room in regular_rooms:
        for link in room.biz_item_links:
            biz_to_regular.setdefault(link.biz_item_id, []).append(room)

    # Get all unassigned confirmed reservations for target_date
    unassigned = _get_unassigned_reservations(db, target_date)

    # Separate into regular and dormitory candidates (상품 기준 분류)
    regular_candidates = []
    dormitory_candidates = []

    for res in unassigned:
        if res.naver_biz_item_id in dormitory_biz_ids:
            dormitory_candidates.append(res)
        else:
            regular_candidates.append(res)

    assigned_count = 0
    assigned_reservation_ids = []

    # === Step 1: Regular room assignment ===
    regular_ids = _assign_regular_rooms(
        db, regular_candidates, biz_to_regular, target_date
    )
    assigned_reservation_ids.extend(regular_ids)

    # === Step 2: Dormitory room assignment (성별 분리, 방별 순차 배정) ===
    dorm_ids = _assign_dormitory_rooms(
        db, dormitory_candidates, dormitory_rooms, target_date
    )
    assigned_reservation_ids.extend(dorm_ids)

    assigned_count = len(assigned_reservation_ids)

    # 전부 배정 후 한 번에 flush → SMS 태그 동기화
    db.flush()
    schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
    for res_id in assigned_reservation_ids:
        room_assignment.sync_sms_tags(db, res_id, schedules=schedules)

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
            Reservation.check_in_date <= target_date,
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
        if r.check_out_date is None or r.check_out_date > target_date or r.check_in_date == target_date
    ]


def _assign_regular_rooms(
    db: Session,
    candidates: List[Reservation],
    biz_to_rooms: Dict[str, List[Room]],
    target_date: str,
) -> List[int]:
    """
    Assign regular (non-dormitory) rooms. One room per reservation.
    Returns list of assigned reservation IDs.
    """
    assigned_ids = []

    for res in candidates:
        candidate_rooms = biz_to_rooms.get(res.naver_biz_item_id, [])
        if not candidate_rooms:
            continue

        for room in candidate_rooms:
            if room_assignment.check_capacity_all_dates(
                db, room.room_number, target_date, res.check_out_date,
                people_count=1, exclude_reservation_id=res.id
            ):
                room_assignment.assign_room(
                    db, res.id, room.room_number, target_date, res.check_out_date,
                    assigned_by="auto", skip_sms_sync=True,
                )
                db.flush()  # flush 해야 다음 반복에서 이 배정이 보임
                assigned_ids.append(res.id)
                break

    return assigned_ids


def _assign_dormitory_rooms(
    db: Session,
    candidates: List[Reservation],
    dormitory_rooms: List[Room],
    target_date: str,
) -> List[int]:
    """
    Assign dormitory rooms by gender (no bed-count grouping).
    All dormitory candidates are pooled together, split by gender,
    then filled into available dormitory rooms sequentially.
    Each room's bed_capacity is the capacity limit.
    """
    if not candidates or not dormitory_rooms:
        return []

    # Get manually assigned rooms for this date (exclude from pool)
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
        return []

    # Split candidates by gender
    male_reservations = []
    female_reservations = []
    unknown_reservations = []
    for res in candidates:
        effective_gender = (res.gender or "").strip()
        if effective_gender == "남":
            male_reservations.append(res)
        elif effective_gender == "여":
            female_reservations.append(res)
        else:
            unknown_reservations.append(res)
            logger.warning(f"Reservation {res.id} ({res.customer_name}) has no gender, will assign to remaining rooms")

    def count_people(reservations):
        return sum(r.party_size or r.booking_count or 1 for r in reservations)

    male_total = count_people(male_reservations)
    female_total = count_people(female_reservations)
    unknown_total = count_people(unknown_reservations)

    logger.info(f"Dormitory: 남 {male_total}명 ({len(male_reservations)}건), 여 {female_total}명 ({len(female_reservations)}건), 미상 {unknown_total}명 ({len(unknown_reservations)}건)")

    # Calculate total bed capacity
    total_beds = sum(r.bed_capacity or 1 for r in available_rooms)

    # Calculate rooms needed per gender using average beds per room
    avg_beds = total_beds / len(available_rooms) if available_rooms else 4
    female_rooms_needed = ceil(female_total / avg_beds) if female_total > 0 else 0
    male_rooms_needed = ceil(male_total / avg_beds) if male_total > 0 else 0

    total_rooms_needed = female_rooms_needed + male_rooms_needed
    total_available = len(available_rooms)

    if total_rooms_needed > total_available:
        if female_total + male_total > 0:
            female_rooms_needed = round(total_available * female_total / (female_total + male_total))
            male_rooms_needed = total_available - female_rooms_needed

    # Allocate rooms: more people gender gets first pick
    if female_total >= male_total:
        female_room_list = available_rooms[:female_rooms_needed]
        male_room_list = available_rooms[female_rooms_needed:female_rooms_needed + male_rooms_needed]
        remaining_rooms = available_rooms[female_rooms_needed + male_rooms_needed:]
    else:
        male_room_list = available_rooms[:male_rooms_needed]
        female_room_list = available_rooms[male_rooms_needed:male_rooms_needed + female_rooms_needed]
        remaining_rooms = available_rooms[male_rooms_needed + female_rooms_needed:]

    logger.info(f"Dormitory allocation: 여 {len(female_room_list)}방, 남 {len(male_room_list)}방, 잔여 {len(remaining_rooms)}방")

    assigned_ids: List[int] = []
    assigned_ids.extend(_fill_dormitory_rooms(db, female_reservations, female_room_list, target_date))
    assigned_ids.extend(_fill_dormitory_rooms(db, male_reservations, male_room_list, target_date))
    if unknown_reservations and remaining_rooms:
        assigned_ids.extend(_fill_dormitory_rooms(db, unknown_reservations, remaining_rooms, target_date))

    return assigned_ids


def _fill_dormitory_rooms(
    db: Session,
    reservations: List[Reservation],
    rooms: List[Room],
    target_date: str,
) -> List[int]:
    """
    Fill dormitory rooms with reservations, respecting bed count capacity.
    Packs guests into rooms sequentially.
    Returns list of assigned reservation IDs.
    """
    if not reservations or not rooms:
        return []

    assigned_ids: List[int] = []
    room_idx = 0
    room_occupancy = 0  # Current occupancy of current room

    for res in reservations:
        if room_idx >= len(rooms):
            logger.warning(f"No more dormitory rooms available for reservation {res.id}")
            break

        current_room = rooms[room_idx]
        people = res.party_size or res.booking_count or 1

        # Check if this reservation fits in current room
        if room_occupancy + people > current_room.bed_capacity:
            # Move to next room
            room_idx += 1
            room_occupancy = 0
            if room_idx >= len(rooms):
                logger.warning(f"No more dormitory rooms available for reservation {res.id}")
                break
            current_room = rooms[room_idx]

        # Assign (skip SMS sync, will be done in bulk later)
        room_assignment.assign_room(
            db, res.id, current_room.room_number, target_date, res.check_out_date,
            assigned_by="auto", skip_sms_sync=True,
        )
        room_occupancy += people
        assigned_ids.append(res.id)

        # If room is full, move to next
        if room_occupancy >= current_room.bed_capacity:
            room_idx += 1
            room_occupancy = 0

    return assigned_ids


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
