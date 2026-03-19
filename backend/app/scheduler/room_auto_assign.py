"""
Room auto-assignment scheduler job.
Runs daily to assign rooms for today and tomorrow.
Manual assignments (assigned_by='manual') are never overwritten.

Unified assignment logic (biz_item_id mapping + capacity check + gender lock):
- All rooms (regular and dormitory) use a single biz_item_id → rooms mapping.
- For each unassigned reservation, candidate rooms are looked up by biz_item_id.
- Regular rooms: one reservation per room (capacity check via check_capacity_all_dates).
- Dormitory rooms: multiple reservations per room up to bed_capacity; gender lock
  prevents mixing genders in the same room on the same date.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
from typing import List, Dict
from sqlalchemy.orm import Session
import logging

from sqlalchemy import exists
from sqlalchemy.orm import selectinload
from app.db.models import Reservation, Room, RoomAssignment, ReservationStatus, TemplateSchedule, RoomBizItemLink
from app.services import room_assignment
from app.db.tenant_context import current_tenant_id

logger = logging.getLogger(__name__)


def auto_assign_rooms(db: Session, target_date: str = None):
    """
    Auto-assign rooms for target_date (defaults to today).
    Uses a unified biz_item_id mapping for all room types.
    Never touches manual assignments.
    """
    if not target_date:
        target_date = datetime.now(KST).strftime("%Y-%m-%d")

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

    # Build biz_item_id -> rooms mapping for ALL rooms (regular + dormitory)
    biz_to_rooms: Dict[str, List[Room]] = {}
    for room in rooms_with_biz:
        for link in room.biz_item_links:
            biz_to_rooms.setdefault(link.biz_item_id, []).append(room)

    # Get all unassigned confirmed reservations for target_date
    unassigned = _get_unassigned_reservations(db, target_date)

    assigned_reservation_ids = _assign_all_rooms(db, unassigned, biz_to_rooms, target_date)

    assigned_count = len(assigned_reservation_ids)

    # Flush then sync SMS tags in bulk
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
                    RoomAssignment.date == target_date,
                    RoomAssignment.tenant_id == current_tenant_id.get(),
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


def _sort_candidate_rooms(rooms: List[Room], biz_item_id: str, gender: str) -> List[Room]:
    """Sort candidate rooms by gender-specific priority from RoomBizItemLink."""
    def get_priority(room: Room) -> tuple:
        for link in room.biz_item_links:
            if link.biz_item_id == biz_item_id:
                if gender == "여":
                    return (link.female_priority or 0, room.sort_order, room.id)
                elif gender == "남":
                    return (link.male_priority or 0, room.sort_order, room.id)
                break
        return (0, room.sort_order, room.id)
    return sorted(rooms, key=get_priority)


def _gender_sort_key(res: Reservation) -> int:
    """Sort key: females first (0), males second (1), unknown last (2)."""
    g = (res.gender or "").strip()
    if g == "여": return 0
    if g == "남": return 1
    return 2


def _assign_all_rooms(
    db: Session,
    candidates: List[Reservation],
    biz_to_rooms: Dict[str, List[Room]],
    target_date: str,
) -> List[int]:
    """
    Assign rooms based on biz_item_id mapping.
    For dormitory rooms: respects bed_capacity and gender lock.
    For regular rooms: one reservation per room.
    Gender lock: if a dormitory room already has occupants, only same-gender guests can be added.
    """
    assigned_ids = []

    # Sort candidates: females first, then males, then unknown gender
    candidates = sorted(candidates, key=_gender_sort_key)

    for res in candidates:
        candidate_rooms = biz_to_rooms.get(res.naver_biz_item_id, [])
        # Sort rooms by gender-specific priority
        res_gender = (res.gender or "").strip()
        candidate_rooms = _sort_candidate_rooms(candidate_rooms, res.naver_biz_item_id, res_gender)
        if not candidate_rooms:
            continue

        people_count = res.party_size or res.booking_count or 1

        for room in candidate_rooms:
            if room.is_dormitory:
                # Check capacity with actual party size
                if not room_assignment.check_capacity_all_dates(
                    db, room.room_number, target_date, res.check_out_date,
                    people_count=people_count, exclude_reservation_id=res.id
                ):
                    continue

                # Gender lock: check ALL existing occupants' gender
                existing = (
                    db.query(RoomAssignment)
                    .filter(
                        RoomAssignment.room_number == room.room_number,
                        RoomAssignment.date == target_date,
                    )
                    .all()
                )
                if existing:
                    existing_reservations = db.query(Reservation).filter(
                        Reservation.id.in_([e.reservation_id for e in existing])
                    ).all()
                    res_gender = (res.gender or "").strip()
                    gender_conflict = False
                    for existing_res in existing_reservations:
                        existing_gender = (existing_res.gender or "").strip()
                        if existing_gender and res_gender and existing_gender != res_gender:
                            gender_conflict = True
                            break
                    if gender_conflict:
                        continue

                # Assign
                room_assignment.assign_room(
                    db, res.id, room.room_number, target_date, res.check_out_date,
                    assigned_by="auto", skip_sms_sync=True,
                )
                db.flush()
                assigned_ids.append(res.id)
                break
            else:
                # Regular room: one per room
                if room_assignment.check_capacity_all_dates(
                    db, room.room_number, target_date, res.check_out_date,
                    people_count=1, exclude_reservation_id=res.id
                ):
                    room_assignment.assign_room(
                        db, res.id, room.room_number, target_date, res.check_out_date,
                        assigned_by="auto", skip_sms_sync=True,
                    )
                    db.flush()
                    assigned_ids.append(res.id)
                    break

    return assigned_ids


def daily_assign_rooms(db: Session):
    """
    Daily job: auto-assign rooms for today and tomorrow.
    Clears all auto-assigned rooms first, then re-assigns from scratch.
    Manual assignments (assigned_by='manual') are preserved.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Running daily room assignment for {today} and {tomorrow}")

    # Clear existing auto assignments before re-assigning
    for target_date in [today, tomorrow]:
        deleted = db.query(RoomAssignment).filter(
            RoomAssignment.date == target_date,
            RoomAssignment.assigned_by == "auto",
        ).delete(synchronize_session="fetch")
        if deleted:
            logger.info(f"Cleared {deleted} auto-assignments for {target_date}")
    db.flush()

    result_today = auto_assign_rooms(db, today)
    result_tomorrow = auto_assign_rooms(db, tomorrow)

    return {
        "today": result_today,
        "tomorrow": result_tomorrow,
    }
