"""
Shared Naver reservation sync logic.
Used by both the API endpoint and the scheduler job.
"""
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging

from app.db.models import Reservation, ReservationStatus, Room

logger = logging.getLogger(__name__)


async def sync_naver_to_db(reservation_provider, db: Session, target_date=None) -> Dict[str, Any]:
    """
    Fetch reservations from Naver and upsert into DB.

    Returns summary dict with synced/added/updated counts.
    """
    logger.info("Starting Naver reservation sync...")

    reservations = await reservation_provider.sync_reservations(target_date)

    # Bulk-fetch existing reservations by external_id/naver_booking_id in one query
    all_ext_ids = [
        r.get("external_id") or r.get("naver_booking_id")
        for r in reservations
        if r.get("external_id") or r.get("naver_booking_id")
    ]
    existing_map: Dict[str, Reservation] = {}
    if all_ext_ids:
        existing_rows = (
            db.query(Reservation)
            .filter(
                or_(
                    Reservation.external_id.in_(all_ext_ids),
                    Reservation.naver_booking_id.in_(all_ext_ids),
                )
            )
            .all()
        )
        for row in existing_rows:
            if row.external_id:
                existing_map[row.external_id] = row
            if row.naver_booking_id:
                existing_map[row.naver_booking_id] = row

    added_count = 0
    updated_count = 0

    for res_data in reservations:
        external_id = res_data.get("external_id") or res_data.get("naver_booking_id")
        existing = existing_map.get(external_id) if external_id else None

        if existing:
            _update_reservation(existing, res_data)
            updated_count += 1
        else:
            new_res = _create_reservation(res_data)
            db.add(new_res)
            added_count += 1

    db.commit()

    # Auto-assign rooms based on naver_biz_item_id matching
    assigned_count = _auto_assign_rooms(db)

    logger.info(f"Naver sync completed: {added_count} added, {updated_count} updated, {assigned_count} auto-assigned")

    return {
        "status": "success",
        "synced": len(reservations),
        "added": added_count,
        "updated": updated_count,
        "assigned": assigned_count,
        "message": f"{len(reservations)}건 조회, {added_count}건 추가, {updated_count}건 갱신, {assigned_count}건 자동배정",
    }


def _create_reservation(res_data: Dict[str, Any]) -> Reservation:
    """Create a new Reservation from Naver API data."""
    try:
        status_enum = ReservationStatus(res_data.get("status", "pending"))
    except ValueError:
        status_enum = ReservationStatus.CONFIRMED

    return Reservation(
        external_id=res_data.get("external_id"),
        naver_booking_id=res_data.get("naver_booking_id"),
        naver_biz_item_id=res_data.get("naver_biz_item_id"),
        customer_name=res_data.get("customer_name", ""),
        phone=res_data.get("phone", ""),
        visitor_name=res_data.get("visitor_name"),
        visitor_phone=res_data.get("visitor_phone"),
        date=res_data.get("date", ""),
        time=res_data.get("time", ""),
        status=status_enum,
        source="naver",
        room_info=res_data.get("room_type", ""),
        party_participants=res_data.get("people_count", 1),
        end_date=res_data.get("end_date"),
        biz_item_name=res_data.get("biz_item_name"),
        booking_count=res_data.get("booking_count", 1),
        booking_options=res_data.get("booking_options"),
        custom_form_input=res_data.get("custom_form_input"),
        total_price=res_data.get("total_price"),
        confirmed_datetime=res_data.get("confirmed_datetime"),
        cancelled_datetime=res_data.get("cancelled_datetime"),
        gender=res_data.get("gender"),
    )


def _update_reservation(existing: Reservation, res_data: Dict[str, Any]):
    """Update an existing Reservation with fresh Naver API data."""
    # Only update fields that come from Naver (don't overwrite local edits like room_number)
    existing.customer_name = res_data.get("customer_name", existing.customer_name)
    existing.phone = res_data.get("phone", existing.phone)
    existing.visitor_name = res_data.get("visitor_name")
    existing.visitor_phone = res_data.get("visitor_phone")
    existing.naver_biz_item_id = res_data.get("naver_biz_item_id", existing.naver_biz_item_id)
    existing.room_info = res_data.get("room_type", existing.room_info)
    existing.party_participants = res_data.get("people_count", existing.party_participants)
    existing.date = res_data.get("date", existing.date)
    existing.time = res_data.get("time", existing.time)
    existing.end_date = res_data.get("end_date", existing.end_date)
    existing.biz_item_name = res_data.get("biz_item_name", existing.biz_item_name)
    existing.booking_count = res_data.get("booking_count", existing.booking_count)
    existing.booking_options = res_data.get("booking_options", existing.booking_options)
    existing.custom_form_input = res_data.get("custom_form_input", existing.custom_form_input)
    existing.total_price = res_data.get("total_price", existing.total_price)
    existing.confirmed_datetime = res_data.get("confirmed_datetime", existing.confirmed_datetime)
    existing.cancelled_datetime = res_data.get("cancelled_datetime", existing.cancelled_datetime)
    if res_data.get("gender"):
        existing.gender = res_data["gender"]

    # Update status based on Naver status
    naver_status = res_data.get("status", "confirmed")
    if naver_status == "confirmed":
        existing.status = ReservationStatus.CONFIRMED
    elif naver_status == "cancelled":
        existing.status = ReservationStatus.CANCELLED

    existing.updated_at = datetime.utcnow()


def _auto_assign_rooms(db: Session) -> int:
    """
    Auto-assign rooms to unassigned reservations based on naver_biz_item_id.
    Matches reservation's naver_biz_item_id to room's naver_biz_item_id.
    Skips rooms already taken for the same date.
    """
    # Get rooms that have a naver_biz_item_id linked
    rooms_with_biz = (
        db.query(Room)
        .filter(Room.naver_biz_item_id.isnot(None), Room.is_active == True)
        .order_by(Room.sort_order)
        .all()
    )
    if not rooms_with_biz:
        return 0

    # Build mapping: naver_biz_item_id -> list of room_numbers
    biz_to_rooms: dict = {}
    for room in rooms_with_biz:
        biz_to_rooms.setdefault(room.naver_biz_item_id, []).append(room.room_number)

    # Get unassigned confirmed reservations with a naver_biz_item_id
    unassigned = (
        db.query(Reservation)
        .filter(
            Reservation.room_number.is_(None),
            Reservation.naver_biz_item_id.isnot(None),
            Reservation.status == ReservationStatus.CONFIRMED,
        )
        .all()
    )

    # Pre-fetch all occupied (date, room_number) pairs in one query
    dates = {res.date for res in unassigned}
    existing_assignments = (
        db.query(Reservation.date, Reservation.room_number)
        .filter(Reservation.date.in_(dates), Reservation.room_number.isnot(None))
        .all()
    )
    occupied = {(d, r) for d, r in existing_assignments}

    assigned_count = 0
    for res in unassigned:
        candidate_rooms = biz_to_rooms.get(res.naver_biz_item_id, [])
        if not candidate_rooms:
            continue

        for room_number in candidate_rooms:
            if (res.date, room_number) not in occupied:
                res.room_number = room_number
                occupied.add((res.date, room_number))
                assigned_count += 1
                break

    if assigned_count:
        db.commit()
        logger.info(f"Auto-assigned {assigned_count} reservations to rooms")

    return assigned_count
