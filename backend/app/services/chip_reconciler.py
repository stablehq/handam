"""
Unified SMS chip (ReservationSmsAssignment) reconciliation.

Single source of truth for chip create/delete logic, replacing the
previous split between sync_sms_tags (reservation-centric) and
auto_assign_for_schedule (schedule-centric).

Both entry points use the same matching source (apply_structural_filters)
and the same diff+protect logic (_sync_chips).
"""
import logging
from datetime import date
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.db.models import (
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
    TemplateSchedule,
)
from app.services.filters import apply_structural_filters
from app.services.schedule_utils import get_schedule_dates, resolve_target_date

logger = logging.getLogger(__name__)

# Chip protection rules (unified)
_PROTECTED_ASSIGNED_BY = {'manual', 'excluded'}


def reconcile_chips_for_reservation(
    db: Session,
    reservation_id: int,
    schedules: Optional[list] = None,
) -> None:
    """Reconcile chips for a single reservation against all active schedules.

    For each schedule, checks if the reservation matches the schedule's
    structural filters. Creates missing chips, deletes stale chips.

    Does NOT commit — caller owns the transaction.
    """
    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id
    ).first()
    if not reservation:
        return

    if schedules is None:
        schedules = db.query(TemplateSchedule).filter(
            TemplateSchedule.is_active == True
        ).all()

    # Compute expected (template_key, date) pairs
    expected_pairs: Set[Tuple[str, str]] = set()
    for schedule in schedules:
        if not schedule.template or not schedule.template.is_active:
            continue
        # Event schedules cannot have static chips
        if (schedule.schedule_category or 'standard') == 'event':
            continue

        if _reservation_matches_schedule(db, schedule, reservation_id):
            template_key = schedule.template.template_key
            dates = get_schedule_dates(schedule, reservation)
            for d in dates:
                expected_pairs.add((template_key, d))

    # Get current chips for this reservation
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
    ).all()

    _sync_chips(db, expected_pairs, existing, reservation_id=reservation_id)


def reconcile_chips_for_schedule(
    db: Session,
    schedule: TemplateSchedule,
) -> int:
    """Reconcile chips for a single schedule against all matching reservations.

    Finds all reservations that match the schedule's structural filters,
    computes expected chips, and syncs (create missing, delete stale).

    Does NOT commit — caller owns the transaction.

    Returns:
        Number of new chips created.
    """
    if not schedule.template or not schedule.template.is_active:
        return 0
    if (schedule.schedule_category or 'standard') == 'event':
        return 0

    template_key = schedule.template.template_key

    # Resolve target date
    target_date = resolve_target_date(schedule.date_target) if schedule.date_target else date.today().strftime('%Y-%m-%d')

    # Build matching reservations query with structural filters only
    matching_reservations = _get_matching_reservations(db, schedule, target_date)

    # Compute expected (reservation_id, date) pairs
    expected_pairs: Set[Tuple[int, str]] = set()
    for reservation in matching_reservations:
        dates = get_schedule_dates(schedule, reservation)
        for d in dates:
            expected_pairs.add((reservation.id, d))

    # Get ALL existing chips for this template_key (across all reservations)
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.template_key == template_key,
    ).all()

    return _sync_chips_for_schedule(db, expected_pairs, existing, template_key)


def _reservation_matches_schedule(
    db: Session,
    schedule: TemplateSchedule,
    reservation_id: int,
) -> bool:
    """Check if a single reservation matches a schedule's structural filters.

    Uses apply_structural_filters on a single-row query for consistency
    with the batch path.
    """
    target_date = resolve_target_date(schedule.date_target) if schedule.date_target else date.today().strftime('%Y-%m-%d')

    query = db.query(Reservation).filter(Reservation.id == reservation_id)
    query = apply_structural_filters(db, query, schedule, target_date)
    return query.first() is not None


def _get_matching_reservations(
    db: Session,
    schedule: TemplateSchedule,
    target_date: str,
) -> List[Reservation]:
    """Get all reservations matching a schedule's structural filters.

    Applies only structural filters (building/assignment/room/column_match).
    Does NOT apply send-time filters (exclude_sent, once_per_stay, etc.).
    """
    query = db.query(Reservation).filter(
        Reservation.status == ReservationStatus.CONFIRMED,
    )

    # Date range: include reservations active on target_date
    # For checkout-based: target checkout date
    date_target_val = schedule.date_target
    if date_target_val and date_target_val.endswith('_checkout'):
        query = query.filter(
            Reservation.check_out_date.isnot(None),
            Reservation.check_out_date == target_date,
        )
    else:
        target_mode = schedule.target_mode or 'once'
        if target_mode in ('daily', 'last_day'):
            query = query.filter(
                or_(
                    and_(
                        Reservation.check_in_date <= target_date,
                        Reservation.check_out_date > target_date,
                    ),
                    and_(
                        Reservation.check_in_date == target_date,
                        Reservation.check_out_date.is_(None),
                    ),
                )
            )
        else:
            query = query.filter(Reservation.check_in_date == target_date)

    # Apply structural filters (building/assignment/room/column_match)
    query = apply_structural_filters(db, query, schedule, target_date)

    return query.all()


def _sync_chips(
    db: Session,
    expected_pairs: Set[Tuple[str, str]],
    existing: list,
    reservation_id: int,
) -> int:
    """Diff-based chip sync for a single reservation.

    expected_pairs: set of (template_key, date)
    existing: list of ReservationSmsAssignment for this reservation

    Returns number of chips created.
    """
    existing_pairs = {(a.template_key, a.date) for a in existing}
    excluded_pairs = {(a.template_key, a.date) for a in existing if a.assigned_by == 'excluded'}

    created = 0

    # Create missing chips (skip excluded)
    for (key, d) in expected_pairs:
        if (key, d) not in existing_pairs and (key, d) not in excluded_pairs:
            db.add(ReservationSmsAssignment(
                reservation_id=reservation_id,
                template_key=key,
                date=d,
                assigned_by='auto',
                sent_at=None,
            ))
            created += 1

    # Delete stale chips (only unprotected)
    for a in existing:
        if (a.template_key, a.date) not in expected_pairs:
            if a.sent_at is None and a.assigned_by not in _PROTECTED_ASSIGNED_BY:
                db.delete(a)

    return created


def _sync_chips_for_schedule(
    db: Session,
    expected_pairs: Set[Tuple[int, str]],
    existing: list,
    template_key: str,
) -> int:
    """Diff-based chip sync for a single schedule (across all reservations).

    expected_pairs: set of (reservation_id, date)
    existing: list of ReservationSmsAssignment for this template_key

    Returns number of chips created.
    """
    existing_pairs = {(a.reservation_id, a.date) for a in existing}
    excluded_pairs = {(a.reservation_id, a.date) for a in existing if a.assigned_by == 'excluded'}

    created = 0

    # Create missing chips (skip excluded)
    for (res_id, d) in expected_pairs:
        if (res_id, d) not in existing_pairs and (res_id, d) not in excluded_pairs:
            db.add(ReservationSmsAssignment(
                reservation_id=res_id,
                template_key=template_key,
                date=d,
                assigned_by='schedule',
                sent_at=None,
            ))
            created += 1

    # Delete stale chips (only unprotected)
    for a in existing:
        if (a.reservation_id, a.date) not in expected_pairs:
            if a.sent_at is None and a.assigned_by not in _PROTECTED_ASSIGNED_BY:
                db.delete(a)

    return created
