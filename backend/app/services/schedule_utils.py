"""
Shared schedule date utilities.

Extracted from room_assignment.py to break circular dependency:
  room_assignment -> chip_reconciler -> template_scheduler -> room_assignment
"""
from datetime import datetime, timedelta
from typing import Optional, List

from app.config import today_kst, today_kst_date


def get_schedule_dates(schedule, reservation) -> List[str]:
    """Get target dates for a schedule+reservation pair."""
    if (schedule.schedule_category or 'standard') == 'event':
        return [reservation.check_in_date] if reservation.check_in_date else []

    target_mode = schedule.target_mode  # first_night | last_night | None

    # last_night: 마지막 투숙일 1개
    if target_mode == 'last_night':
        # check_out_date IS NULL 또는 check_out_date == check_in_date 는
        # 모두 "당일 1박" 으로 동일 취급 — 체크인일이 곧 마지막 투숙일.
        # _filter_last_day(template_scheduler.py) 와 동일 invariant.
        if not reservation.check_out_date or reservation.check_out_date == reservation.check_in_date:
            return [reservation.check_in_date] if reservation.check_in_date else []
        if reservation.stay_group_id:
            if reservation.is_last_in_group:
                last_day = (datetime.strptime(reservation.check_out_date, "%Y-%m-%d")
                            - timedelta(days=1)).strftime("%Y-%m-%d")
                return [last_day]
            return []
        last_day = (datetime.strptime(reservation.check_out_date, "%Y-%m-%d")
                    - timedelta(days=1)).strftime("%Y-%m-%d")
        return [last_day]

    # first_night: 체크인일 1개 (stay_group 내에서는 첫 멤버만)
    if target_mode == 'first_night':
        if reservation.stay_group_id:
            if reservation.stay_group_order == 0:
                return [reservation.check_in_date or '']
            return []  # 그룹의 첫 멤버가 아니면 칩 생성 안 함
        return [reservation.check_in_date or '']

    # 기본(None): stay-coverage 전체 일정 매일 칩 (옛 daily 동작)
    if reservation.check_out_date and reservation.check_out_date > (reservation.check_in_date or ''):
        return date_range(reservation.check_in_date, reservation.check_out_date)
    return [reservation.check_in_date or '']


def date_range(from_date: str, end_date: Optional[str]) -> List[str]:
    """Generate dates in [from_date, end_date) — **end_date EXCLUSIVE**.

    For a stay: pass check_in_date as from_date and check_out_date as end_date.
    The returned list covers all NIGHTS (체류 일수), not including checkout day.

    Examples:
        date_range("2026-04-10", "2026-04-13") → ["2026-04-10", "2026-04-11", "2026-04-12"]
        date_range("2026-04-10", "2026-04-10") → ["2026-04-10"]  # fallback
        date_range("2026-04-10", None) → ["2026-04-10"]

    If end_date is None or <= from_date: returns [from_date].
    """
    if not end_date or end_date <= from_date:
        return [from_date]
    dates = []
    current = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current < end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates if dates else [from_date]


def resolve_target_date(date_target_val: str) -> str:
    """Convert a date_target enum value to YYYY-MM-DD.
    Supported: 'yesterday' | 'today' | 'tomorrow'.
    Unknown values → today (safe fallback + diag log).
    """
    if date_target_val == 'yesterday':
        return (today_kst_date() - timedelta(days=1)).strftime('%Y-%m-%d')
    if date_target_val == 'tomorrow':
        return (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
    if date_target_val and date_target_val not in ('today', 'yesterday', 'tomorrow'):
        # Legacy *_checkout or other unknown: log and treat as today
        from app.diag_logger import diag
        diag("schedule.date_target.legacy_value", level="critical",
             value=date_target_val)
    return today_kst()
