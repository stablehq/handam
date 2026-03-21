"""
Consecutive stay (연박) detection and linking service.

Detects guests who made separate single-day bookings for consecutive dates
and links them via a shared stay_group_id (UUID).

Detection criteria:
  - Same (customer_name, phone) OR (visitor_name, phone) OR (customer_name, visitor_phone)
  - A.check_out_date == B.check_in_date
  - Both CONFIRMED status

Idempotent: safe to run multiple times. Auto-unlinks stale groups.
"""
import logging
import uuid
from collections import defaultdict
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import Reservation, ReservationStatus

logger = logging.getLogger(__name__)


def detect_and_link_consecutive_stays(db: Session) -> dict:
    """
    Scan all CONFIRMED reservations and link consecutive stays.

    Groups by (name, phone) identity, sorts by check_in_date,
    and links where A.check_out_date == B.check_in_date.

    Idempotent: re-scans every time. Unlinks reservations that are
    no longer consecutive. Preserves existing group IDs where valid.

    Returns:
        dict with counts: {"linked": N, "unlinked": M, "groups": G}
    """
    # Fetch all CONFIRMED reservations with check_out_date
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.check_out_date.isnot(None),
            Reservation.phone.isnot(None),
            Reservation.phone != "",
        )
        .order_by(Reservation.check_in_date)
        .all()
    )

    # Build identity groups: multiple keys per reservation for fuzzy matching
    identity_map: dict[str, list[Reservation]] = defaultdict(list)
    for res in reservations:
        name = (res.customer_name or "").strip()
        phone = (res.phone or "").strip()
        if name and phone:
            identity_map[f"{name}|{phone}"].append(res)
        # Also match visitor_name/visitor_phone combinations
        vname = (res.visitor_name or "").strip()
        vphone = (res.visitor_phone or "").strip()
        if vname and phone and vname != name:
            identity_map[f"{vname}|{phone}"].append(res)
        if name and vphone and vphone != phone:
            identity_map[f"{name}|{vphone}"].append(res)

    # Deduplicate: merge groups that share reservations
    res_to_group: dict[int, set[int]] = {}
    for _key, group in identity_map.items():
        if len(group) < 2:
            continue
        res_ids = {r.id for r in group}
        # Find existing merged groups
        merged = set()
        for rid in res_ids:
            if rid in res_to_group:
                merged |= res_to_group[rid]
        merged |= res_ids
        for rid in merged:
            res_to_group[rid] = merged

    # Build final groups (sets of reservation IDs)
    seen_groups: list[set[int]] = []
    seen_ids: set[int] = set()
    for rid, group in res_to_group.items():
        if rid not in seen_ids:
            seen_groups.append(group)
            seen_ids |= group

    # Build reservation lookup
    res_lookup = {r.id: r for r in reservations}

    linked_count = 0
    unlinked_count = 0
    group_count = 0

    # Track which reservations should be in a stay group
    should_be_grouped: set[int] = set()

    for group_ids in seen_groups:
        # Sort by check_in_date
        group_res = sorted(
            [res_lookup[rid] for rid in group_ids if rid in res_lookup],
            key=lambda r: r.check_in_date,
        )
        if len(group_res) < 2:
            continue

        # Find consecutive chains within this identity group
        chains: list[list[Reservation]] = []
        current_chain = [group_res[0]]

        for i in range(1, len(group_res)):
            prev = current_chain[-1]
            curr = group_res[i]
            if prev.check_out_date and prev.check_out_date == curr.check_in_date:
                current_chain.append(curr)
            else:
                if len(current_chain) >= 2:
                    chains.append(current_chain)
                current_chain = [curr]

        if len(current_chain) >= 2:
            chains.append(current_chain)

        # Assign stay_group_id to each chain
        for chain in chains:
            group_count += 1
            # Reuse existing group ID if any member already has one
            existing_group_id = None
            for res in chain:
                if res.stay_group_id:
                    existing_group_id = res.stay_group_id
                    break
            group_id = existing_group_id or str(uuid.uuid4())

            for order, res in enumerate(chain):
                should_be_grouped.add(res.id)
                if res.stay_group_id != group_id or res.stay_group_order != order:
                    res.stay_group_id = group_id
                    res.stay_group_order = order
                    linked_count += 1

    # Unlink reservations that are no longer consecutive
    for res in reservations:
        if res.stay_group_id and res.id not in should_be_grouped:
            res.stay_group_id = None
            res.stay_group_order = None
            unlinked_count += 1

    if linked_count > 0 or unlinked_count > 0:
        db.flush()

    result = {"linked": linked_count, "unlinked": unlinked_count, "groups": group_count}
    if linked_count > 0 or unlinked_count > 0:
        logger.info(f"Consecutive stay detection: {result}")
    return result


def unlink_from_group(db: Session, reservation_id: int) -> bool:
    """
    Remove a reservation from its stay group.
    Re-orders remaining members. If only 1 member remains, dissolves the group.

    Returns True if the reservation was unlinked.
    """
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res or not res.stay_group_id:
        return False

    group_id = res.stay_group_id
    res.stay_group_id = None
    res.stay_group_order = None

    # Re-order remaining members
    remaining = (
        db.query(Reservation)
        .filter(
            Reservation.stay_group_id == group_id,
            Reservation.id != reservation_id,
        )
        .order_by(Reservation.stay_group_order)
        .all()
    )

    if len(remaining) <= 1:
        # Dissolve group if only 1 member left
        for r in remaining:
            r.stay_group_id = None
            r.stay_group_order = None
    else:
        for i, r in enumerate(remaining):
            r.stay_group_order = i

    db.flush()
    return True


def link_reservations(db: Session, reservation_ids: List[int]) -> Optional[str]:
    """
    Manually link multiple reservations into a stay group.
    Sorts by check_in_date and assigns stay_group_order.

    Returns the stay_group_id, or None if fewer than 2 valid reservations.
    """
    reservations = (
        db.query(Reservation)
        .filter(Reservation.id.in_(reservation_ids))
        .order_by(Reservation.check_in_date)
        .all()
    )

    if len(reservations) < 2:
        return None

    # Reuse existing group ID or create new
    group_id = None
    for res in reservations:
        if res.stay_group_id:
            group_id = res.stay_group_id
            break
    group_id = group_id or str(uuid.uuid4())

    for order, res in enumerate(reservations):
        res.stay_group_id = group_id
        res.stay_group_order = order

    db.flush()
    return group_id
