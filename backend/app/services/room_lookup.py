"""Batch room lookup utilities to avoid N+1 queries."""
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models import Room, RoomAssignment


def batch_room_lookup(
    db: Session,
    reservation_ids: list[int],
    target_date: Optional[str] = None,
) -> dict[int, dict]:
    """Batch lookup room info for reservations.

    Returns: {reservation_id: {"room_id": int, "room_number": str, "room_password": str, "assigned_by": str}}
    If target_date is None, uses the earliest assignment per reservation.
    """
    if not reservation_ids:
        return {}

    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id.in_(reservation_ids),
    )
    if target_date:
        query = query.filter(RoomAssignment.date == target_date)

    assignments = query.all()

    # Build reservation_id -> assignment mapping (first assignment per reservation)
    ra_map: dict[int, RoomAssignment] = {}
    for ra in assignments:
        if ra.reservation_id not in ra_map:
            ra_map[ra.reservation_id] = ra

    # Batch fetch rooms
    room_ids = {ra.room_id for ra in ra_map.values() if ra.room_id}
    if not room_ids:
        return {}

    rooms = db.query(Room).filter(Room.id.in_(room_ids)).all()
    room_map = {rm.id: rm for rm in rooms}

    result = {}
    for res_id, ra in ra_map.items():
        rm = room_map.get(ra.room_id)
        result[res_id] = {
            "room_id": ra.room_id,
            "room_number": rm.room_number if rm else None,
            "room_password": ra.room_password,
            "assigned_by": ra.assigned_by,
        }
    return result


def batch_room_number_map(
    db: Session,
    reservation_ids: list[int],
    target_date: str,
) -> dict[int, str]:
    """Simple batch lookup: reservation_id -> room_number string.

    Convenience wrapper for cases that only need room_number.
    """
    lookup = batch_room_lookup(db, reservation_ids, target_date)
    return {res_id: info["room_number"] or "" for res_id, info in lookup.items()}
