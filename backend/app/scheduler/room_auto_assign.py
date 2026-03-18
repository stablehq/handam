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

    for res in candidates:
        candidate_rooms = biz_to_rooms.get(res.naver_biz_item_id, [])
        if not candidate_rooms:
            continue

        for room in candidate_rooms:
            if room.is_dormitory:
                # Check capacity
                if not room_assignment.check_capacity_all_dates(
                    db, room.room_number, target_date, res.check_out_date,
                    people_count=1, exclude_reservation_id=res.id
                ):
                    continue

                # Gender lock: check existing occupants' gender
                existing = (
                    db.query(RoomAssignment)
                    .join(Reservation, Reservation.id == RoomAssignment.reservation_id)
                    .filter(
                        RoomAssignment.room_number == room.room_number,
                        RoomAssignment.date == target_date,
                    )
                    .all()
                )
                if existing:
                    # Get gender of existing occupants
                    existing_res = db.query(Reservation).filter(
                        Reservation.id.in_([e.reservation_id for e in existing])
                    ).first()
                    if existing_res:
                        existing_gender = (existing_res.gender or "").strip()
                        res_gender = (res.gender or "").strip()
                        # If existing has a gender and it doesn't match, skip this room
                        if existing_gender and res_gender and existing_gender != res_gender:
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
    Only fills in missing assignments, never overwrites manual ones.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Running daily room assignment for {today} and {tomorrow}")

    result_today = auto_assign_rooms(db, today)
    result_tomorrow = auto_assign_rooms(db, tomorrow)

    return {
        "today": result_today,
        "tomorrow": result_tomorrow,
    }
