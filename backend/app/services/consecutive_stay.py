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
from app.db.tenant_context import current_tenant_id

logger = logging.getLogger(__name__)


def compute_is_long_stay(res) -> bool:
    """연박자(2박+) OR 연장자(stay_group_id) 판단"""
    if res.stay_group_id:
        return True
    if res.check_out_date and res.check_in_date:
        try:
            from datetime import datetime as _dt
            d1 = _dt.strptime(str(res.check_in_date), "%Y-%m-%d")
            d2 = _dt.strptime(str(res.check_out_date), "%Y-%m-%d")
            return (d2 - d1).days > 1
        except (ValueError, TypeError):
            pass
    return False


def detect_and_link_consecutive_stays(db: Session, tenant_id: int = None) -> dict:
    """
    Scan all CONFIRMED reservations and link consecutive stays.

    Groups by (name, phone) identity, sorts by check_in_date,
    and links where A.check_out_date == B.check_in_date.

    Idempotent: re-scans every time. Unlinks reservations that are
    no longer consecutive. Preserves existing group IDs where valid.

    Args:
        tenant_id: explicit tenant scope. Falls back to ContextVar if omitted.

    Returns:
        dict with counts: {"linked": N, "unlinked": M, "groups": G}
    """
    tid = tenant_id or current_tenant_id.get()
    if tid is None:
        raise RuntimeError("detect_and_link_consecutive_stays requires tenant context")

    # Fetch all CONFIRMED reservations with check_out_date
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.tenant_id == tid,
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
                is_last = (order == len(chain) - 1)
                if res.stay_group_id != group_id or res.stay_group_order != order or res.is_last_in_group != is_last:
                    res.stay_group_id = group_id
                    res.stay_group_order = order
                    res.is_last_in_group = is_last
                    res.is_long_stay = True
                    linked_count += 1
                elif not res.is_long_stay:
                    res.is_long_stay = True

    # Unlink reservations that are no longer consecutive
    for res in reservations:
        if res.stay_group_id and res.id not in should_be_grouped and not res.stay_group_id.startswith("manual-"):
            res.stay_group_id = None
            res.stay_group_order = None
            res.is_last_in_group = None
            res.is_long_stay = compute_is_long_stay(res)
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
    tid = current_tenant_id.get()

    query = db.query(Reservation).filter(Reservation.id == reservation_id)
    if tid:
        query = query.filter(Reservation.tenant_id == tid)
    res = query.first()
    if not res or not res.stay_group_id:
        return False

    group_id = res.stay_group_id
    res.stay_group_id = None
    res.stay_group_order = None
    res.is_last_in_group = None
    res.is_long_stay = compute_is_long_stay(res)

    # Re-order remaining members
    remaining_q = (
        db.query(Reservation)
        .filter(
            Reservation.stay_group_id == group_id,
            Reservation.id != reservation_id,
        )
    )
    if tid:
        remaining_q = remaining_q.filter(Reservation.tenant_id == tid)
    remaining = remaining_q.order_by(Reservation.stay_group_order).all()

    if len(remaining) <= 1:
        # Dissolve group if only 1 member left
        for r in remaining:
            r.stay_group_id = None
            r.stay_group_order = None
            r.is_last_in_group = None
            r.is_long_stay = compute_is_long_stay(r)
    else:
        for i, r in enumerate(remaining):
            r.stay_group_order = i
            r.is_last_in_group = (i == len(remaining) - 1)

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
    group_id = group_id or f"manual-{uuid.uuid4()}"

    for order, res in enumerate(reservations):
        res.stay_group_id = group_id
        res.stay_group_order = order
        res.is_last_in_group = (order == len(reservations) - 1)
        res.is_long_stay = True

    db.flush()
    return group_id
