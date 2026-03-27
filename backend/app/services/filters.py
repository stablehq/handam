"""
Schedule filter logic for template-based SMS scheduling.

Contains condition builders, filter parsing, grouping, and the
`matches_schedule()` helper used by room assignment tag sync.
"""
import json
from collections import defaultdict
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.db.models import (
    Reservation,
    Room,
    RoomAssignment,
    TemplateSchedule,
    ReservationDailyInfo,
)


# ---------------------------------------------------------------------------
# Condition builder functions: (value, ctx) -> condition
# Each returns a SQLAlchemy condition (not applied to query directly).
# Same-type conditions are OR-ed; different types are AND-ed.
# ---------------------------------------------------------------------------

def _condition_by_assignment(value, ctx):
    """Return condition for assignment status: room / party / unassigned."""
    if value == "room":
        return Reservation.section == 'room'
    elif value == "party":
        return Reservation.section == 'party'
    elif value == "unassigned":
        return Reservation.section == 'unassigned'
    return None


def _condition_by_building(value, ctx):
    """Return condition for building filter."""
    target_date = ctx.get("target_date")
    sub = (
        ctx["db"].query(RoomAssignment.reservation_id)
        .join(Room, Room.id == RoomAssignment.room_id)
        .filter(
            RoomAssignment.date == target_date,
            Room.building_id == int(value),
        )
    ).subquery()
    return Reservation.id.in_(sub)


def _condition_by_room(value, ctx):
    """Return condition for room id."""
    target_date = ctx.get("target_date")
    try:
        room_id_val = int(value)
    except (ValueError, TypeError):
        return None
    sub = (
        ctx["db"].query(RoomAssignment.reservation_id)
        .filter(
            RoomAssignment.date == target_date,
            RoomAssignment.room_id == room_id_val,
        )
    ).subquery()
    return Reservation.id.in_(sub)


# Whitelist of allowed columns for column_match filter
_COLUMN_MATCH_COLUMNS = {"party_type", "gender", "naver_room_type", "notes"}


def _escape_like(text: str) -> str:
    """Escape LIKE wildcard characters so they are matched literally."""
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _condition_by_column_match(value, ctx):
    """Return condition for column text match filter.

    value format: '{column}:{operator}:{text}'
    operator: 'contains', 'not_contains', 'is_empty', 'is_not_empty'

    For party_type: uses per-date ReservationDailyInfo if available,
    falling back to Reservation.party_type.
    """
    parts = value.split(':', 2)
    if len(parts) < 2:
        return None
    column = parts[0]
    operator = parts[1]
    text = parts[2] if len(parts) == 3 else ''
    if column not in _COLUMN_MATCH_COLUMNS:
        return None

    # For party_type: resolve effective value as daily info override OR reservation fallback
    if column == 'party_type':
        target_date = ctx.get('target_date')
        daily_sub = (
            ctx['db'].query(ReservationDailyInfo.party_type)
            .filter(
                ReservationDailyInfo.reservation_id == Reservation.id,
                ReservationDailyInfo.date == target_date,
            )
            .correlate(Reservation)
            .scalar_subquery()
        )
        effective = func.coalesce(daily_sub, Reservation.party_type)
        if operator == 'is_empty':
            return effective.is_(None) | (effective == '')
        elif operator == 'is_not_empty':
            return effective.isnot(None) & (effective != '')
        elif operator == 'contains' and text:
            return effective.like(f'%{_escape_like(text)}%', escape='\\')
        elif operator == 'not_contains' and text:
            return ~effective.like(f'%{_escape_like(text)}%', escape='\\') | effective.is_(None)
        return None

    col_attr = getattr(Reservation, column, None)
    if col_attr is None:
        return None
    if operator == 'is_empty':
        return col_attr.is_(None) | (col_attr == '')
    elif operator == 'is_not_empty':
        return col_attr.isnot(None) & (col_attr != '')
    elif operator == 'contains' and text:
        return col_attr.like(f'%{_escape_like(text)}%', escape='\\')
    elif operator == 'not_contains' and text:
        return ~col_attr.like(f'%{_escape_like(text)}%', escape='\\') | col_attr.is_(None)
    return None


FILTER_BUILDERS = {
    "assignment": _condition_by_assignment,
    "building": _condition_by_building,
    "room": _condition_by_room,
    "column_match": _condition_by_column_match,
    # 레거시 호환
    "room_assigned": lambda v, ctx: _condition_by_assignment("room", ctx),
    "party_only": lambda v, ctx: _condition_by_assignment("party", ctx),
}


def apply_structural_filters(db: Session, query, schedule, target_date: str):
    """Apply structural filters (building/assignment/room/column_match) to a query.

    Standalone version of TemplateScheduleExecutor._apply_structural_filters.
    Used by chip_reconciler for unified matching.

    Args:
        db: Database session
        query: SQLAlchemy query to filter
        schedule: TemplateSchedule instance (needs .filters attribute)
        target_date: Resolved date string (YYYY-MM-DD)

    Returns:
        Filtered query
    """
    filters = _parse_filters(schedule.filters)

    ctx = {"db": db, "target_date": target_date}

    filter_groups, has_unassigned = _build_filter_groups(filters)

    for group_key, values in filter_groups.items():
        filter_type = group_key.split(':')[0] if group_key.startswith('column_match:') else group_key
        builder = FILTER_BUILDERS.get(filter_type)
        if not builder:
            continue
        conditions = [c for c in (builder(v, ctx) for v in values) if c is not None]
        if conditions:
            combined = or_(*conditions) if len(conditions) > 1 else conditions[0]
            if filter_type in ("building", "room") and has_unassigned:
                combined = or_(combined, Reservation.section == 'unassigned')
            query = query.filter(combined)

    return query


def _parse_filters(raw_filters) -> list:
    """Parse filters from string or list format."""
    if not raw_filters:
        return []
    if isinstance(raw_filters, str):
        try:
            return json.loads(raw_filters)
        except (json.JSONDecodeError, TypeError):
            return []
    return raw_filters if isinstance(raw_filters, list) else []


def _build_filter_groups(filters: list) -> tuple:
    """Group filters by type for OR/AND combination.

    Returns: (filter_groups dict, has_unassigned bool)
    """
    filter_groups: dict = defaultdict(list)
    _cm_idx = 0
    for f in filters:
        ftype = f.get("type", "")
        fval = f.get("value", "")
        if ftype == "column_match":
            # Each column_match gets its own group → AND between all column_match filters.
            # Other types (building, assignment) share a group → OR within same type.
            group_key = f"column_match:{_cm_idx}"
            _cm_idx += 1
        else:
            group_key = ftype
        filter_groups[group_key].append(fval)
    has_unassigned = 'unassigned' in filter_groups.get('assignment', [])
    return filter_groups, has_unassigned


def matches_schedule(db: Session, schedule: TemplateSchedule, reservation_id: int) -> bool:
    """Check if a single reservation matches a schedule's structural filters.

    .. deprecated::
        Use chip_reconciler._reservation_matches_schedule() instead, which
        resolves target_date from schedule.date_target rather than hardcoding today.

    Does NOT apply date_target or exclude_sent — those are for get_targets() only.
    Applies only building/assignment/room/column_match filters.

    Returns True if the reservation passes all filter groups (AND between groups,
    OR within same group), or if there are no filters.
    """
    # 이벤트 스케줄은 시간 기반이라 정적 태그 생성 불가
    if (schedule.schedule_category or 'standard') == 'event':
        return False

    filters = _parse_filters(schedule.filters)

    if not filters:
        return True

    query = db.query(Reservation).filter(Reservation.id == reservation_id)

    # Use today as target_date for building/room subqueries
    ctx = {"db": db, "target_date": date.today().strftime('%Y-%m-%d')}

    filter_groups, has_unassigned = _build_filter_groups(filters)

    for group_key, values in filter_groups.items():
        filter_type = group_key.split(':')[0] if group_key.startswith('column_match:') else group_key
        builder = FILTER_BUILDERS.get(filter_type)
        if not builder:
            continue
        conditions = [c for c in (builder(v, ctx) for v in values) if c is not None]
        if conditions:
            combined = or_(*conditions) if len(conditions) > 1 else conditions[0]
            # 미배정 예약자는 건물/객실 조건 면제 (RoomAssignment 없으므로 매칭 불가)
            if filter_type in ("building", "room") and has_unassigned:
                combined = or_(combined, Reservation.section == 'unassigned')
            query = query.filter(combined)

    return query.first() is not None
