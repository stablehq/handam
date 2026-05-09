"""
Schedule filter logic v2 — nested structure + normalize-on-read dual parser.

v2 Schema (persisted form):
    assignment filter:
        {"type": "assignment",
         "value": "room" | "party" | "unstable" | "unassigned",
         "buildings": [int, ...],        # room only, optional
         "include_unassigned": bool,     # room only, optional (legacy has_unassigned trick)
         "stay_filter": "exclude"|None}  # room only, optional (연박자 제외)

    column_match filter (unchanged):
        {"type": "column_match", "value": "{column}:{operator}:{text}"}

v1 (legacy, still readable via dual-parse):
    - {"type": "assignment", "value": "..."} + separate {"type": "building", "value": "N"}
    - {"type": "room", "value": "N"}   (ghost, dropped)
    - {"type": "room_assigned"} / {"type": "party_only"}  (legacy aliases)
    - has_unassigned OR trick: absorbed into include_unassigned modifier

Combining semantics:
    - Multiple assignment filters: OR  (same as v1)
    - Multiple column_match filters: AND (same as v1)
    - assignment AND column_match: AND

Stay options (stay_filter):
    - Live inside the "room" assignment filter (v2)
    - extract_stay_filter() returns stay_filter for the scheduler
    - Falls back to legacy TemplateSchedule column during transition
"""
import json
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, exists

from app.diag_logger import diag
from app.db.models import (
    Reservation,
    Room,
    RoomAssignment,
    ReservationDailyInfo,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ASSIGNMENT_VALUES = {"room", "party", "unassigned", "unstable"}
_COLUMN_MATCH_COLUMNS = {"party_type", "gender", "naver_room_type", "notes"}


# ---------------------------------------------------------------------------
# Stay-coverage filter (canonical "date d 에 투숙/방문 중" 조건)
# ---------------------------------------------------------------------------

def stay_coverage_filter(date_str: str):
    """date_str 날에 "있는" 예약을 모두 잡는 SQLAlchemy 조건.

    포함:
      - 숙박 첫날                (check_in == d, check_out > d)
      - 연박 중간일              (check_in <  d, check_out > d)
      - NULL 체크아웃 (당일예약)  (check_in == d, check_out IS NULL)
      - 당일만 (파티/언스테이블)  (check_in == d == check_out)

    제외:
      - 퇴실일 (check_in < d, check_out == d)
      - 해당 날짜와 무관한 예약

    두 번째 OR 분기 `check_in == d` 가 NULL·당일 케이스를 한꺼번에 흡수한다.
    상태/섹션 필터는 호출자가 별도로 붙인다.
    """
    return or_(
        and_(
            Reservation.check_in_date <= date_str,
            Reservation.check_out_date > date_str,
        ),
        Reservation.check_in_date == date_str,
    )


# ---------------------------------------------------------------------------
# Dual-parse: v1 → v2 normalization (normalize-on-read)
# ---------------------------------------------------------------------------

def _is_v2_shape(filters: list) -> bool:
    """Heuristic: any v2 marker present (nested keys) and no v1 flat-only markers."""
    has_nested = any(
        f.get("type") == "assignment" and any(
            k in f for k in ("buildings", "include_unassigned", "stay_filter")
        )
        for f in filters
    )
    has_v1_only = any(
        f.get("type") in ("building", "room", "room_assigned", "party_only")
        for f in filters
    )
    if has_nested and not has_v1_only:
        return True
    # Empty/assignment-only + column_match with no legacy types: already v2 (trivially compatible)
    if not has_v1_only:
        return True
    return False


def _normalize_to_v2(filters: list) -> list:
    """Convert v1 filter list to v2 nested structure. Idempotent.

    Rules:
      - {"type":"room_assigned"}   → {"type":"assignment","value":"room"}
      - {"type":"party_only"}      → {"type":"assignment","value":"party"}
      - {"type":"room", ...}       → dropped (ghost)
      - {"type":"building","value":N} items → merge into assignment.buildings
        (attach to room assignment; if no room, create one)
      - {"type":"assignment","value":"unassigned"} + any room/building → fold as
        include_unassigned=true modifier on room
      - {"type":"assignment","value":"unassigned"} alone → keep as peer (legacy)
    """
    if not filters:
        return []

    if _is_v2_shape(filters):
        # Still strip ghost room type & legacy aliases (idempotent cleanup)
        out: list = []
        for f in filters:
            t = f.get("type")
            if t == "room":
                continue
            if t == "room_assigned":
                out.append({"type": "assignment", "value": "room"})
            elif t == "party_only":
                out.append({"type": "assignment", "value": "party"})
            else:
                out.append(f)
        return out

    diag("filter.v1_normalize.hit", level="verbose", filter_count=len(filters))

    assignments: list[str] = []
    buildings: list[int] = []
    has_unassigned = False
    column_matches: list[dict] = []
    # Preserve any unknown/pass-through items so we never silently drop data
    passthrough: list[dict] = []

    for f in filters:
        t = f.get("type")
        v = f.get("value")
        if t == "assignment":
            if v == "unassigned":
                has_unassigned = True
            elif v in _ASSIGNMENT_VALUES:
                assignments.append(v)
        elif t == "room_assigned":
            assignments.append("room")
        elif t == "party_only":
            assignments.append("party")
        elif t == "building":
            try:
                buildings.append(int(v))
            except (ValueError, TypeError):
                pass
        elif t == "room":
            continue  # ghost: drop
        elif t == "column_match":
            column_matches.append({"type": "column_match", "value": v})
        else:
            passthrough.append(f)

    out: list = []
    room_emitted = False

    # Emit room assignment (if explicit OR implied by building filter)
    if "room" in assignments or buildings:
        room_filter: dict = {"type": "assignment", "value": "room"}
        if buildings:
            room_filter["buildings"] = sorted(set(buildings))
        if has_unassigned:
            room_filter["include_unassigned"] = True
            has_unassigned = False  # consumed
        out.append(room_filter)
        room_emitted = True

    # Emit non-room assignments (party/unstable)
    for v in assignments:
        if v == "room":
            continue
        out.append({"type": "assignment", "value": v})

    # Standalone unassigned (no room filter to absorb into)
    if has_unassigned and not room_emitted:
        out.append({"type": "assignment", "value": "unassigned"})

    out.extend(column_matches)
    out.extend(passthrough)
    return out


def _parse_filters(raw_filters) -> list:
    """Parse JSON/list filters and normalize to v2.

    Accepts string (DB TEXT) or list (already parsed).
    Invalid JSON → []. Unknown items preserved as passthrough.
    """
    if not raw_filters:
        return []
    if isinstance(raw_filters, str):
        try:
            parsed = json.loads(raw_filters)
        except (json.JSONDecodeError, TypeError):
            return []
    elif isinstance(raw_filters, list):
        parsed = raw_filters
    else:
        return []
    if not isinstance(parsed, list):
        return []
    return _normalize_to_v2(parsed)


# ---------------------------------------------------------------------------
# Stay options extraction (used by template_scheduler)
# ---------------------------------------------------------------------------

def extract_stay_filter(schedule) -> str | None:
    """Return stay_filter from filter JSON's room assignment ('exclude' | None).

    Reads from the v2 'room' assignment filter first. Falls back to legacy
    TemplateSchedule column (`stay_filter`) if the schedule has no room
    assignment filter (e.g. party-only or not yet migrated).
    """
    filters = _parse_filters(schedule.filters)
    room_filter = next(
        (f for f in filters if f.get("type") == "assignment" and f.get("value") == "room"),
        None,
    )
    if room_filter is not None:
        return room_filter.get("stay_filter") or None

    # Legacy fallback
    legacy_sf = getattr(schedule, "stay_filter", None)
    if legacy_sf and filters:
        has_non_room = any(
            f.get("type") == "assignment" and f.get("value") != "room"
            for f in filters
        )
        if has_non_room:
            diag("schedule.section_guard.ui_violation", level="critical",
                 schedule_id=getattr(schedule, "id", None),
                 legacy_stay_filter=legacy_sf)
    return legacy_sf


# ---------------------------------------------------------------------------
# Condition builders (v2)
# ---------------------------------------------------------------------------

def _condition_room(spec: dict, ctx: dict, *, with_buildings: bool = True):
    """Room assignment condition, optionally narrowed by buildings.

    Args:
        with_buildings: When False, ignore buildings narrow (used by
            only_date_independent mode for chip candidate prefilter).
    """
    target_date = ctx.get("target_date")
    buildings = spec.get("buildings") if with_buildings else None
    include_unassigned = bool(spec.get("include_unassigned"))

    if buildings:
        sub = (
            ctx["db"].query(RoomAssignment.reservation_id)
            .join(Room, and_(Room.id == RoomAssignment.room_id,
                              Room.tenant_id == RoomAssignment.tenant_id))
            .filter(
                RoomAssignment.date == target_date,
                Room.building_id.in_([int(b) for b in buildings]),
            )
        ).subquery()
        room_cond = and_(
            Reservation.section == 'room',
            Reservation.id.in_(sub),
        )
    else:
        room_cond = (Reservation.section == 'room')

    if include_unassigned:
        return or_(room_cond, Reservation.section == 'unassigned')
    return room_cond


def _condition_simple_assignment(spec: dict, ctx: dict):
    """Party / unstable / unassigned (peer) condition."""
    value = spec.get("value")
    if value == "party":
        return Reservation.section == 'party'
    if value == "unassigned":
        return Reservation.section == 'unassigned'
    if value == "unstable":
        target_date = ctx.get("target_date")
        if target_date:
            sub = (
                ctx["db"].query(ReservationDailyInfo.reservation_id)
                .filter(
                    ReservationDailyInfo.date == target_date,
                    ReservationDailyInfo.unstable_party == True,
                )
            ).subquery()
            return or_(
                Reservation.section == 'unstable',
                Reservation.id.in_(sub),
            )
        return Reservation.section == 'unstable'
    return None


def _condition_assignment(spec: dict, ctx: dict, *, only_date_independent: bool):
    value = spec.get("value")
    if value == "room":
        return _condition_room(spec, ctx, with_buildings=not only_date_independent)
    return _condition_simple_assignment(spec, ctx)


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so they match literally."""
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _condition_column_match(spec: dict, ctx: dict):
    """column_match filter: {column}:{operator}:{text}.

    For party_type / notes: resolves effective value via ReservationDailyInfo
    override, falling back to the reservation column.
    """
    value = spec.get("value", "")
    parts = value.split(':', 2)
    if len(parts) < 2:
        return None
    column, operator = parts[0], parts[1]
    text = parts[2] if len(parts) == 3 else ''
    if column not in _COLUMN_MATCH_COLUMNS:
        return None

    if column == 'party_type':
        # party_type 은 일자별 의미가 강함 (당일 파티 타입) → target_date 의 daily_info 우선
        target_date = ctx.get('target_date')
        daily_col = getattr(ReservationDailyInfo, column)
        daily_sub = (
            ctx['db'].query(daily_col)
            .filter(
                ReservationDailyInfo.reservation_id == Reservation.id,
                ReservationDailyInfo.date == target_date,
            )
            .correlate(Reservation)
            .scalar_subquery()
        )
        effective = func.coalesce(daily_sub, getattr(Reservation, column))
        if operator == 'is_empty':
            return effective.is_(None) | (effective == '')
        if operator == 'is_not_empty':
            return effective.isnot(None) & (effective != '')
        if operator == 'contains' and text:
            return effective.like(f'%{_escape_like(text)}%', escape='\\')
        if operator == 'not_contains' and text:
            return ~effective.like(f'%{_escape_like(text)}%', escape='\\') | effective.is_(None)
        return None

    if column == 'notes':
        # notes 는 stay 전체 메모로 취급 — stay 기간 daily_info notes OR reservation.notes 검사.
        # 운영자가 첫박/중간/마지막 어느 박일에 키워드 입력해도 first_night/last_night
        # 양쪽 스케줄이 모두 매칭되어야 한다 (예: 객후 → promiss 첫박 + review 마지막박).
        res_notes = getattr(Reservation, column)
        daily_notes = getattr(ReservationDailyInfo, column)
        # stay 박일 범위: check_in_date <= daily.date < check_out_date
        # (check_out_date NULL = 단일 박 → daily 매칭 없음, reservation.notes 만 검사)
        stay_predicate = and_(
            ReservationDailyInfo.reservation_id == Reservation.id,
            ReservationDailyInfo.date >= Reservation.check_in_date,
            Reservation.check_out_date.isnot(None),
            ReservationDailyInfo.date < Reservation.check_out_date,
        )
        if operator == 'contains' and text:
            like = f'%{_escape_like(text)}%'
            stay_match = exists().where(and_(stay_predicate, daily_notes.like(like, escape='\\')))
            return stay_match | res_notes.like(like, escape='\\')
        if operator == 'not_contains' and text:
            like = f'%{_escape_like(text)}%'
            any_match = exists().where(and_(stay_predicate, daily_notes.like(like, escape='\\')))
            return ~any_match & (~res_notes.like(like, escape='\\') | res_notes.is_(None))
        if operator == 'is_empty':
            any_nonempty = exists().where(and_(
                stay_predicate,
                daily_notes.isnot(None),
                daily_notes != '',
            ))
            return ~any_nonempty & (res_notes.is_(None) | (res_notes == ''))
        if operator == 'is_not_empty':
            any_nonempty = exists().where(and_(
                stay_predicate,
                daily_notes.isnot(None),
                daily_notes != '',
            ))
            return any_nonempty | (res_notes.isnot(None) & (res_notes != ''))
        return None

    col_attr = getattr(Reservation, column, None)
    if col_attr is None:
        return None
    if operator == 'is_empty':
        return col_attr.is_(None) | (col_attr == '')
    if operator == 'is_not_empty':
        return col_attr.isnot(None) & (col_attr != '')
    if operator == 'contains' and text:
        return col_attr.like(f'%{_escape_like(text)}%', escape='\\')
    if operator == 'not_contains' and text:
        return ~col_attr.like(f'%{_escape_like(text)}%', escape='\\') | col_attr.is_(None)
    return None


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

_COLUMN_MATCH_DATE_DEPENDENT = {"party_type", "notes"}


def apply_structural_filters(
    db: Session, query, schedule, target_date: str,
    *, only_date_independent: bool = False,
):
    """Apply v2 filters to a SQLAlchemy query.

    Args:
        db: session
        query: existing query on Reservation
        schedule: TemplateSchedule-like with .filters attribute (JSON string or list)
        target_date: YYYY-MM-DD string (needed by date-dependent filters)
        only_date_independent: When True, skip filters that depend on target_date.
            Used by chip_reconciler._get_candidate_reservations for per-date
            refinement later.

    Returns:
        Filtered query.
    """
    diag(
        "filter.apply.enter", level="verbose",
        schedule_id=getattr(schedule, 'id', None),
        target_date=target_date,
        only_date_independent=only_date_independent,
    )

    filters = _parse_filters(schedule.filters)
    ctx = {"db": db, "target_date": target_date}

    assignment_conds: list = []
    cm_conds: list = []

    for f in filters:
        ftype = f.get("type")
        if ftype == "assignment":
            cond = _condition_assignment(f, ctx, only_date_independent=only_date_independent)
            if cond is not None:
                assignment_conds.append(cond)
        elif ftype == "column_match":
            if only_date_independent:
                col = (f.get("value") or "").split(':', 1)[0]
                if col in _COLUMN_MATCH_DATE_DEPENDENT:
                    continue
            cond = _condition_column_match(f, ctx)
            if cond is not None:
                cm_conds.append(cond)
        # else: passthrough/unknown types silently ignored

    # assignment group: OR
    if assignment_conds:
        combined = or_(*assignment_conds) if len(assignment_conds) > 1 else assignment_conds[0]
        query = query.filter(combined)
        diag("filter.applied", level="verbose",
             filter_type="assignment", conditions_count=len(assignment_conds))

    # column_match: each AND
    for cm in cm_conds:
        query = query.filter(cm)
    if cm_conds:
        diag("filter.applied", level="verbose",
             filter_type="column_match", conditions_count=len(cm_conds))

    diag("filter.apply.exit", level="verbose")
    return query
