"""
칩(ReservationSmsAssignment) reconcile 모듈.

칩 = "이 예약자에게 / 이 날짜에 / 이 템플릿 SMS를 보낼 예정" 이라는 기록.

두 가지 reconcile 경로:
  - reservation-centric: 1 예약 × N 스케줄 × M 날짜 (예약 생성/수정/배정 시)
  - schedule-centric:    1 스케줄 × N 예약 × M 날짜 (스케줄 생성/수정/실행 시)

핵심 로직:
  1. get_schedule_dates(schedule, reservation) → 칩이 필요한 날짜 목록
  2. _reservation_matches_schedule(db, schedule, reservation, date) → 그 날 필터 통과?
  3. _sync_chips(expected, existing) → diff: 없는 칩 생성, 불필요 칩 삭제

칩 보호: assigned_by='manual'/'excluded' 또는 sent_at 있으면 삭제 안 됨.
"""
import logging
from datetime import timedelta
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
    TemplateSchedule,
)
from app.config import today_kst, today_kst_date
from app.diag_logger import diag
from app.services.filters import apply_structural_filters, extract_stay_filter
from app.services.schedule_utils import get_schedule_dates, resolve_target_date

logger = logging.getLogger(__name__)

# Chip protection rules — chip_store 의 PROTECTED_ASSIGNED_BY + send_status
# 가드가 통합 보호. 본 상수는 PR7 이후 미사용 (제거 예정).


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

    # Cross-tenant guard: session 의 tenant 와 reservation 의 tenant 가 다르면
    # silent ghost chip 생성 위험. 진단만 발화 (raise 시 정상 reconcile 막을 수
    # 있으니 critical diag 로 가시화만 — 이후 로그 조사로 root cause 추적).
    _session_tid = db.info.get('tenant_id')
    if _session_tid is not None and _session_tid != reservation.tenant_id:
        diag(
            "chip.tenant_mismatch",
            level="critical",
            session_tid=_session_tid,
            reservation_id=reservation_id,
            reservation_tid=reservation.tenant_id,
        )

    diag("reconcile_chips_for_reservation.enter", level="verbose", res_id=reservation_id)

    # 취소된 예약: 기존 미발송 칩만 정리하고 리턴 (새 칩 생성 안 함).
    # chip_store.delete_chips_for_reservation 위임 (PR7) — force=False 가
    # manual/excluded/failed + send_status='failed' 보호.
    if reservation.status == ReservationStatus.CANCELLED:
        from app.services.chip_store import delete_chips_for_reservation
        cleaned = delete_chips_for_reservation(
            db, reservation_id=reservation_id,
        )
        diag(
            "reconcile_chips_for_reservation.exit",
            level="verbose",
            res_id=reservation_id,
            cancelled_cleanup=cleaned,
        )
        return

    if schedules is None:
        # Defense-in-depth: bind schedules to the reservation's tenant. If
        # bypass_tenant_filter is leaked True, the implicit before_compile
        # filter is skipped and cross-tenant schedules would otherwise be
        # mixed in, causing chips with the wrong tenant's schedule_id and
        # template_key to be created on this reservation.
        schedules = db.query(TemplateSchedule).filter(
            TemplateSchedule.tenant_id == reservation.tenant_id,
            TemplateSchedule.is_active == True,
        ).all()
    else:
        # Caller supplied schedules — strip any cross-tenant rows that may
        # have leaked through. Cheap O(N) post-filter; required because
        # callers (e.g. room_auto_assign) historically queried without an
        # explicit tenant filter.
        schedules = [s for s in schedules if s.tenant_id == reservation.tenant_id]

    # Compute expected (template_key, date) pairs with schedule_id tracking
    expected_pairs: Set[Tuple[str, str]] = set()
    expected_schedule_map: dict = {}  # (template_key, date) -> schedule_id
    for schedule in schedules:
        if not schedule.template or not schedule.template.is_active:
            continue
        # Event schedules cannot have static chips
        if (schedule.schedule_category or 'standard') in ('event', 'custom_schedule'):
            continue

        template_key = schedule.template.template_key
        dates = get_schedule_dates(schedule, reservation)
        for d in dates:
            if _reservation_matches_schedule(db, schedule, reservation, d):
                expected_pairs.add((template_key, d))
                if (template_key, d) not in expected_schedule_map:
                    expected_schedule_map[(template_key, d)] = schedule.id

    # Get current chips for this reservation (custom_schedule 소속 칩 제외)
    custom_schedule_ids = {s.id for s in schedules if (s.schedule_category or 'standard') == 'custom_schedule'}
    all_existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
    ).all()
    existing = [a for a in all_existing if a.schedule_id not in custom_schedule_ids]

    created = _sync_chips(db, expected_pairs, existing, reservation_id=reservation_id, schedule_map=expected_schedule_map)

    diag(
        "reconcile_chips_for_reservation.exit",
        level="verbose",
        res_id=reservation_id,
        expected=len(expected_pairs),
        existing=len(existing),
        created=created,
    )


def reconcile_chips_for_schedule(
    db: Session,
    schedule: TemplateSchedule,
) -> int:
    """Reconcile chips for a single schedule against all matching reservations.

    Finds candidate reservations (date-independent filters), then checks
    date-dependent filters per-date for each candidate.

    Does NOT commit — caller owns the transaction.

    Returns:
        Number of new chips created.
    """
    if not schedule.template:
        return 0
    template_key = schedule.template.template_key

    diag(
        "reconcile_chips_for_schedule.enter",
        level="verbose",
        schedule_id=schedule.id,
        template_key=template_key,
    )

    # 비활성 스케줄/템플릿/이벤트: 자기가 만든 칩만 삭제
    if not schedule.template.is_active or not schedule.is_active or (schedule.schedule_category or 'standard') in ('event', 'custom_schedule'):
        existing = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.schedule_id == schedule.id,
        ).all()
        created = _sync_chips_for_schedule(db, set(), existing, template_key, schedule.id)
        diag(
            "reconcile_chips_for_schedule.exit",
            level="verbose",
            schedule_id=schedule.id,
            template_key=template_key,
            inactive_cleanup=True,
            existing=len(existing),
            created=created,
        )
        return created

    # 활성: 후보 예약 조회 (날짜 무관 필터만) + per-date 필터링
    target_date = resolve_target_date(schedule.date_target) if schedule.date_target else today_kst()
    candidates = _get_candidate_reservations(db, schedule, target_date)
    candidate_ids = [r.id for r in candidates]

    # scope_dates: 후보 예약의 전체 스케줄 날짜 범위 (필터링 전)
    # → stale 칩 삭제 누락 방지
    scope_dates: set = {target_date}
    expected_pairs: Set[Tuple[int, str]] = set()

    for reservation in candidates:
        dates = get_schedule_dates(schedule, reservation)
        scope_dates.update(dates)  # 필터링 전에 scope에 추가
        for d in dates:
            if _reservation_matches_schedule(db, schedule, reservation, d):
                expected_pairs.add((reservation.id, d))

    # scope_dates 범위 내 + candidate 범위 내 자기 칩만 diff 대상
    # ★ reservation_id 필터가 없으면, scope_dates 에 우연히 포함된
    #   타 예약의 칩(예: 다른 예약의 last_night 이 같은 날짜)까지 잘못 삭제됨.
    existing = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.template_key == template_key,
        ReservationSmsAssignment.schedule_id == schedule.id,
        ReservationSmsAssignment.date.in_(scope_dates),
        ReservationSmsAssignment.reservation_id.in_(candidate_ids) if candidate_ids else False,
    ).all()

    created = _sync_chips_for_schedule(db, expected_pairs, existing, template_key, schedule.id)

    diag(
        "reconcile_chips_for_schedule.exit",
        level="verbose",
        schedule_id=schedule.id,
        template_key=template_key,
        candidates=len(candidates),
        expected=len(expected_pairs),
        existing=len(existing),
        created=created,
    )

    return created


def _reservation_matches_schedule(
    db: Session,
    schedule: TemplateSchedule,
    reservation: Reservation,
    target_date: str,
) -> bool:
    """Check if a reservation matches a schedule's structural filters for target_date."""
    query = db.query(Reservation).filter(Reservation.id == reservation.id)
    query = apply_structural_filters(db, query, schedule, target_date)
    return query.first() is not None


def _get_candidate_reservations(
    db: Session,
    schedule: TemplateSchedule,
    target_date: str,
) -> List[Reservation]:
    """Get candidate reservations using only date-independent filters.

    Applies date range filter + assignment/gender/naver_room_type only.
    Building/room/column_match(party_type, notes) are deferred to per-date check.
    """
    query = db.query(Reservation).filter(
        Reservation.status == ReservationStatus.CONFIRMED,
    )

    # Safety guard: check_in 이 ±7일 범위 내 (A 경로와 동일)
    # — 너무 과거/미래 예약에 칩이 만들어졌다가 safety guard 로 발송 못 되는 stale 방지
    min_date = (today_kst_date() - timedelta(days=7)).strftime('%Y-%m-%d')
    max_date = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
    query = query.filter(
        Reservation.check_in_date >= min_date,
        Reservation.check_in_date <= max_date,
    )

    # Date range: include reservations active on target_date
    target_mode = schedule.target_mode
    # 기본: stay-coverage (연박 중간일 + NULL/당일 포함)
    from app.services.filters import stay_coverage_filter
    query = query.filter(stay_coverage_filter(target_date))
    # first_night narrow
    if target_mode == 'first_night':
        query = query.filter(Reservation.check_in_date == target_date)
    # last_night 는 post-filter 없이 stay-coverage 면 충분 (실행 시점에 _filter_last_day)

    # stay_filter='exclude': 연박자는 칩 대상에서 제외 (A 경로와 동일)
    if extract_stay_filter(schedule) == 'exclude':
        query = query.filter(Reservation.is_long_stay == False)  # noqa: E712

    # 날짜 무관 필터만 적용 (assignment, gender, naver_room_type 등)
    query = apply_structural_filters(db, query, schedule, target_date, only_date_independent=True)

    return query.all()


def _sync_chips(
    db: Session,
    expected_pairs: Set[Tuple[str, str]],
    existing: list,
    reservation_id: int,
    schedule_map: Optional[dict] = None,
) -> int:
    """Diff-based chip sync for a single reservation.

    expected_pairs: set of (template_key, date)
    existing: list of ReservationSmsAssignment for this reservation
    schedule_map: optional dict of (template_key, date) -> schedule_id

    Returns number of chips created.
    """
    existing_pairs = {(a.template_key, a.date) for a in existing}
    excluded_pairs = {(a.template_key, a.date) for a in existing if a.assigned_by == 'excluded'}

    from app.services.chip_store import ensure_chip, remove_chip

    created = 0

    # Create missing chips — chip_store.ensure_chip 위임 (PR7).
    # idempotent + race-safe SAVEPOINT 가 내부에서 처리됨. (chip.race_save_point_triggered
    # → chip_store.ensure.race 로 흡수)
    for (key, d) in expected_pairs:
        if (key, d) not in existing_pairs and (key, d) not in excluded_pairs:
            schedule_id = schedule_map.get((key, d)) if schedule_map else None
            ensure_chip(
                db,
                reservation_id=reservation_id,
                template_key=key,
                date=d,
                assigned_by='auto',
                schedule_id=schedule_id,
            )
            created += 1

    # Delete stale chips — chip_store.remove_chip 위임 (PR7).
    # force=False 가드: sent_at + manual/excluded/failed + send_status='failed' 보호.
    for a in existing:
        if (a.template_key, a.date) not in expected_pairs:
            remove_chip(
                db,
                reservation_id=reservation_id,
                template_key=a.template_key,
                date=a.date,
                schedule_id=a.schedule_id,
            )

    return created


def _sync_chips_for_schedule(
    db: Session,
    expected_pairs: Set[Tuple[int, str]],
    existing: list,
    template_key: str,
    schedule_id: Optional[int] = None,
) -> int:
    """Diff-based chip sync for a single schedule (across all reservations).

    expected_pairs: set of (reservation_id, date)
    existing: list of ReservationSmsAssignment for this schedule
    schedule_id: the schedule that owns these chips

    Returns number of chips created.
    """
    existing_pairs = {(a.reservation_id, a.date) for a in existing}
    excluded_pairs = {(a.reservation_id, a.date) for a in existing if a.assigned_by == 'excluded'}

    from app.services.chip_store import ensure_chip, remove_chip

    created = 0

    # Create missing chips — chip_store.ensure_chip 위임 (PR7).
    # 기존 pre-check (already_exists) 는 chip_store 내부 idempotent 가 흡수.
    for (res_id, d) in expected_pairs:
        if (res_id, d) not in existing_pairs and (res_id, d) not in excluded_pairs:
            # ensure_chip 은 (res, template_key, date) 매칭이라 동일 unique 키
            # 의 다른 schedule 칩이 있으면 그걸 반환 (신규 생성 안 함). created
            # 카운트는 신규 생성 여부를 별도 확인.
            pre_existing = db.query(ReservationSmsAssignment.id).filter(
                ReservationSmsAssignment.reservation_id == res_id,
                ReservationSmsAssignment.template_key == template_key,
                ReservationSmsAssignment.date == d,
            ).scalar()
            ensure_chip(
                db,
                reservation_id=res_id,
                template_key=template_key,
                date=d,
                assigned_by='schedule',
                schedule_id=schedule_id,
            )
            if not pre_existing:
                created += 1

    # Delete stale chips — chip_store.remove_chip 위임 (PR7).
    for a in existing:
        if (a.reservation_id, a.date) not in expected_pairs:
            remove_chip(
                db,
                reservation_id=a.reservation_id,
                template_key=template_key,
                date=a.date,
                schedule_id=a.schedule_id,
            )

    return created
