"""
Shared schedule date utilities.

Extracted from room_assignment.py to break circular dependency:
  room_assignment -> chip_reconciler -> template_scheduler -> room_assignment
"""
from datetime import datetime, timedelta
from typing import Optional, List


def get_schedule_dates(schedule, reservation) -> List[str]:
    """Get target dates for a schedule+reservation pair based on target_mode and date_target."""
    # event schedule: return check-in date only
    if (schedule.schedule_category or 'standard') == 'event':
        return [reservation.check_in_date] if reservation.check_in_date else []

    date_target = schedule.date_target

    # last_day mode: only create chip for last-in-group reservation
    if (schedule.target_mode or 'once') == 'last_day':
        if not reservation.check_out_date:
            return []
        if reservation.stay_group_id:
            if reservation.is_last_in_group:
                last_day = (datetime.strptime(reservation.check_out_date, "%Y-%m-%d")
                            - timedelta(days=1)).strftime("%Y-%m-%d")
                return [last_day]
            else:
                return []  # Not last in group
        else:
            last_day = (datetime.strptime(reservation.check_out_date, "%Y-%m-%d")
                        - timedelta(days=1)).strftime("%Y-%m-%d")
            return [last_day]

    # daily mode always uses full date range
    if (
        (schedule.target_mode or 'once') == 'daily'
        and reservation.check_out_date
        and reservation.check_out_date > (reservation.check_in_date or '')
    ):
        return date_range(reservation.check_in_date, reservation.check_out_date)

    # checkout-based date_target
    if date_target and date_target.endswith('_checkout'):
        return [reservation.check_out_date or reservation.check_in_date or '']

    return [reservation.check_in_date or '']


def date_range(from_date: str, end_date: Optional[str]) -> List[str]:
    """Generate list of date strings [from_date, end_date) in YYYY-MM-DD format.
    If end_date is None or same as from_date, returns [from_date].
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
    """Convert a date_target enum value to a concrete YYYY-MM-DD date string.

    Args:
        date_target_val: One of 'today', 'tomorrow', 'today_checkout', 'tomorrow_checkout'

    Returns:
        Date string for today or tomorrow, regardless of checkout suffix.
    """
    if date_target_val and date_target_val.startswith('tomorrow'):
        return (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
    return datetime.now().date().strftime('%Y-%m-%d')
