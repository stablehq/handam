"""
Template-based schedule execution engine
"""
import json
import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from app.db.models import TemplateSchedule, Reservation, RoomAssignment, ReservationSmsAssignment, Room, ReservationStatus, ReservationDailyInfo
from app.factory import get_sms_provider
from app.templates.renderer import TemplateRenderer
from app.templates.variables import calculate_template_variables
from app.services.room_assignment import get_schedule_dates
from app.services.sms_tracking import record_sms_sent
from app.services.activity_logger import log_activity
from app.services.event_bus import publish as publish_event
from app.services.sms_sender import send_single_sms

logger = logging.getLogger(__name__)


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
        .join(Room, Room.room_number == RoomAssignment.room_number)
        .filter(
            RoomAssignment.date == target_date,
            Room.building_id == int(value),
        )
    ).subquery()
    return Reservation.id.in_(sub)


def _condition_by_room(value, ctx):
    """Return condition for room number."""
    target_date = ctx.get("target_date")
    sub = (
        ctx["db"].query(RoomAssignment.reservation_id)
        .filter(
            RoomAssignment.date == target_date,
            RoomAssignment.room_number == value,
        )
    ).subquery()
    return Reservation.id.in_(sub)


# Whitelist of allowed columns for column_match filter
_COLUMN_MATCH_COLUMNS = {"party_type", "gender", "naver_room_type", "notes"}


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
            return effective.like(f'%{text}%')
        elif operator == 'not_contains' and text:
            return ~effective.like(f'%{text}%') | effective.is_(None)
        return None

    col_attr = getattr(Reservation, column, None)
    if col_attr is None:
        return None
    if operator == 'is_empty':
        return col_attr.is_(None) | (col_attr == '')
    elif operator == 'is_not_empty':
        return col_attr.isnot(None) & (col_attr != '')
    elif operator == 'contains' and text:
        return col_attr.like(f'%{text}%')
    elif operator == 'not_contains' and text:
        return ~col_attr.like(f'%{text}%') | col_attr.is_(None)
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


def matches_schedule(db: Session, schedule: TemplateSchedule, reservation_id: int) -> bool:
    """Check if a single reservation matches a schedule's structural filters.

    Does NOT apply date_filter or exclude_sent — those are for get_targets() only.
    Applies only building/assignment/room/column_match filters.

    Returns True if the reservation passes all filter groups (AND between groups,
    OR within same group), or if there are no filters.
    """
    filters = []
    if schedule.filters:
        try:
            filters = json.loads(schedule.filters) if isinstance(schedule.filters, str) else schedule.filters
        except (json.JSONDecodeError, TypeError):
            filters = []

    if not filters:
        return True

    query = db.query(Reservation).filter(Reservation.id == reservation_id)

    # Use today as target_date for building/room subqueries
    ctx = {"db": db, "target_date": date.today().strftime('%Y-%m-%d')}

    # Group filters: OR within same group, AND between groups
    filter_groups: dict = defaultdict(list)
    for f in filters:
        ftype = f.get("type", "")
        fval = f.get("value", "")
        if ftype == "column_match":
            col = fval.split(':', 1)[0] if ':' in fval else fval
            group_key = f"column_match:{col}"
        else:
            group_key = ftype
        filter_groups[group_key].append(fval)

    for group_key, values in filter_groups.items():
        filter_type = group_key.split(':')[0] if group_key.startswith('column_match:') else group_key
        builder = FILTER_BUILDERS.get(filter_type)
        if not builder:
            continue
        conditions = [c for c in (builder(v, ctx) for v in values) if c is not None]
        if len(conditions) == 1:
            query = query.filter(conditions[0])
        elif len(conditions) > 1:
            query = query.filter(or_(*conditions))

    return query.first() is not None


class TemplateScheduleExecutor:
    """Execute template-based scheduled messages"""

    def __init__(self, db: Session):
        self.db = db
        self.sms_provider = get_sms_provider()
        self.template_renderer = TemplateRenderer(db)

    async def execute_schedule(self, schedule_id: int) -> Dict[str, Any]:
        """
        Execute a template schedule

        Steps:
        1. Load TemplateSchedule
        2. Filter targets based on configuration
        3. Render template for each target
        4. Send SMS (bulk)
        5. Update tracking flags
        6. Log campaign

        Returns:
            Dict with execution results
        """
        logger.info(f"Executing template schedule #{schedule_id}")

        # Load schedule
        schedule = self.db.query(TemplateSchedule).filter(
            TemplateSchedule.id == schedule_id,
            TemplateSchedule.is_active == True
        ).first()

        if not schedule:
            logger.warning(f"Schedule #{schedule_id} not found or inactive")
            return {"success": False, "error": "Schedule not found or inactive"}

        if not schedule.template or not schedule.template.is_active:
            logger.warning(f"Template for schedule #{schedule_id} not found or inactive")
            return {"success": False, "error": "Template not found or inactive"}

        try:
            # Get targets
            targets = self.get_targets(schedule)
            logger.info(f"Found {len(targets)} targets for schedule #{schedule_id}")

            if not targets:
                # Update last_run even if no targets
                schedule.last_run_at = datetime.now(timezone.utc)
                self.db.commit()
                return {"success": True, "sent_count": 0, "message": "No targets found"}

            # Send messages
            sent_count = 0
            failed_count = 0
            send_results = []

            target_date = self._parse_date_filter(schedule.date_filter) if schedule.date_filter else None

            # Build room_number -> building_name map for log display
            room_numbers = set()
            for r in targets:
                if r.room_number:
                    room_numbers.add(r.room_number)
            room_building_map = {}
            if room_numbers:
                rooms_with_building = self.db.query(Room).filter(Room.room_number.in_(room_numbers)).all()
                for rm in rooms_with_building:
                    building_name = rm.building.name if rm.building else ""
                    room_building_map[rm.room_number] = f"{building_name} {rm.room_number}호" if building_name else f"{rm.room_number}호"

            template_key = schedule.template.template_key

            schedule_custom_vars = {'_participant_buffer': schedule.template.participant_buffer or 0}

            for reservation in targets:
                try:
                    result = await send_single_sms(
                        db=self.db,
                        sms_provider=self.sms_provider,
                        reservation=reservation,
                        template_key=template_key,
                        date=target_date,
                        created_by="system",
                        skip_activity_log=True,
                        skip_commit=True,
                        custom_vars=schedule_custom_vars,
                    )

                    if result.get('success'):
                        sent_count += 1

                        record_sms_sent(
                            self.db,
                            reservation.id,
                            template_key,
                            schedule.template.category,
                            assigned_by='schedule',
                            date=target_date or '',
                        )

                        self.db.flush()
                        logger.info(f"Sent SMS to {reservation.customer_name} ({reservation.phone})")
                        send_results.append({
                            "name": reservation.customer_name,
                            "phone": reservation.phone,
                            "template_key": template_key,
                            "template_detail": room_building_map.get(reservation.room_number, "") if reservation.room_number else "",
                            "status": "success",
                            "message_id": result.get("message_id"),
                        })
                    else:
                        failed_count += 1
                        error_msg = result.get('error', 'unknown')
                        logger.error(f"Failed to send SMS to {reservation.phone}: {error_msg}")
                        send_results.append({
                            "name": reservation.customer_name,
                            "phone": reservation.phone,
                            "template_key": template_key,
                            "template_detail": room_building_map.get(reservation.room_number, "") if reservation.room_number else "",
                            "status": "failed",
                            "error": error_msg,
                        })

                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error sending SMS to reservation #{reservation.id}: {str(e)}")
                    send_results.append({
                        "name": reservation.customer_name,
                        "phone": reservation.phone,
                        "template_key": template_key,
                        "template_detail": "",
                        "status": "error",
                        "error": str(e),
                    })

            # Update schedule
            schedule.last_run_at = datetime.now(timezone.utc)

            # 활동 로그 기록 (대상자 상세 포함)
            log_activity(
                self.db,
                type="sms_template",
                title=f"스케줄 발송: {schedule.schedule_name}",
                detail={
                    "schedule_id": schedule.id,
                    "template_key": schedule.template.template_key,
                    "date_filter": schedule.date_filter,
                    "targets": send_results,
                },
                target_count=len(targets),
                success_count=sent_count,
                failed_count=failed_count,
                status="success" if failed_count == 0 else ("partial" if sent_count > 0 else "failed"),
                created_by="system",
            )

            self.db.commit()

            logger.info(f"Schedule #{schedule_id} execution completed: {sent_count} sent, {failed_count} failed")

            if sent_count > 0:
                publish_event("schedule_complete", {
                    "schedule_id": schedule_id,
                    "sent_count": sent_count,
                    "failed_count": failed_count,
                })

            return {
                "success": True,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "target_count": len(targets)
            }

        except Exception as e:
            logger.error(f"Error executing schedule #{schedule_id}: {str(e)}")
            self.db.rollback()
            return {"success": False, "error": str(e)}

    def get_targets(self, schedule: TemplateSchedule, exclude_sent: bool = True) -> List[Reservation]:
        """
        Filter targets based on schedule configuration.

        Uses the ``filters`` JSON column (AND-chained).

        Args:
            schedule: TemplateSchedule instance
            exclude_sent: When True (default), exclude reservations already sent via this template.

        Returns:
            List of Reservation instances
        """
        query = self.db.query(Reservation).filter(
            Reservation.status == ReservationStatus.CONFIRMED
        )

        # Safety guard: never send to reservations more than 1 day out
        max_date = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        query = query.filter(Reservation.check_in_date <= max_date)

        # Apply date filter
        target_date = None
        if schedule.date_filter:
            target_date = self._parse_date_filter(schedule.date_filter)
            if target_date:
                if schedule.target_mode == 'daily':
                    query = query.filter(
                        or_(
                            # 연박: 체크인 <= 오늘 < 체크아웃
                            and_(
                                Reservation.check_in_date <= target_date,
                                Reservation.check_out_date > target_date,
                            ),
                            # 1박(check_out 없음): 체크인 당일만
                            and_(
                                Reservation.check_in_date == target_date,
                                Reservation.check_out_date.is_(None),
                            ),
                        )
                    )
                else:
                    query = query.filter(Reservation.check_in_date == target_date)

        # Default target_date for filters that need it
        if not target_date:
            target_date = date.today().strftime('%Y-%m-%d')

        # --- Parse filters JSON ---
        filters = []
        if schedule.filters:
            try:
                filters = json.loads(schedule.filters)
            except (json.JSONDecodeError, TypeError):
                filters = []

        # Apply filters: OR within same type, AND between types
        ctx = {"db": self.db, "target_date": target_date}

        # Group filters by type
        filter_groups: dict = defaultdict(list)
        for f in filters:
            ftype = f.get("type", "")
            fval = f.get("value", "")
            # column_match: group by type:column so different columns are AND-ed
            if ftype == "column_match":
                col = fval.split(':', 1)[0] if ':' in fval else fval
                group_key = f"column_match:{col}"
            else:
                group_key = ftype
            filter_groups[group_key].append(fval)

        for group_key, values in filter_groups.items():
            # Extract base type from group key (e.g., "column_match:party_type" -> "column_match")
            filter_type = group_key.split(':')[0] if group_key.startswith('column_match:') else group_key
            builder = FILTER_BUILDERS.get(filter_type)
            if not builder:
                continue
            conditions = [c for c in (builder(v, ctx) for v in values) if c is not None]
            if len(conditions) == 1:
                query = query.filter(conditions[0])
            elif len(conditions) > 1:
                query = query.filter(or_(*conditions))

        # Apply exclude_sent filter via join table
        if exclude_sent and schedule.exclude_sent:
            from sqlalchemy import exists
            sent_conditions = (
                (ReservationSmsAssignment.reservation_id == Reservation.id) &
                (ReservationSmsAssignment.template_key == schedule.template.template_key) &
                (ReservationSmsAssignment.sent_at.isnot(None))
            )
            if target_date:
                sent_conditions = sent_conditions & (ReservationSmsAssignment.date == target_date)
            query = query.filter(~exists().where(sent_conditions))

        return query.all()

    def auto_assign_for_schedule(self, schedule: TemplateSchedule) -> int:
        """
        Auto-assign ReservationSmsAssignment records for a schedule's targets.
        Includes already-sent reservations so they still get a chip.
        Skips creation if assignment already exists.

        Returns:
            Number of new assignments created
        """
        targets = self.get_targets(schedule, exclude_sent=False)
        template_key = schedule.template.template_key
        created = 0

        for reservation in targets:
            # Determine dates to assign based on target_mode
            dates = get_schedule_dates(schedule, reservation)

            for d in dates:
                existing = self.db.query(ReservationSmsAssignment).filter(
                    ReservationSmsAssignment.reservation_id == reservation.id,
                    ReservationSmsAssignment.template_key == template_key,
                    ReservationSmsAssignment.date == d,
                ).first()
                if not existing:
                    try:
                        self.db.begin_nested()
                        self.db.add(ReservationSmsAssignment(
                            reservation_id=reservation.id,
                            template_key=template_key,
                            assigned_by='schedule',
                            sent_at=None,
                            date=d or '',
                        ))
                        self.db.flush()
                        created += 1
                    except Exception:
                        self.db.rollback()  # Skip duplicate

        if created:
            self.db.commit()

        return created

    def preview_targets(self, schedule: TemplateSchedule) -> List[Dict[str, Any]]:
        """
        Preview targets without sending messages

        Returns:
            List of target information dicts
        """
        targets = self.get_targets(schedule)

        # Batch lookup room assignments from RoomAssignment table (source of truth)
        target_date = self._parse_date_filter(schedule.date_filter or "today")
        res_ids = [r.id for r in targets]
        room_map: dict[int, str] = {}
        if res_ids and target_date:
            assignments = self.db.query(RoomAssignment).filter(
                RoomAssignment.reservation_id.in_(res_ids),
                RoomAssignment.date == target_date,
            ).all()
            room_map = {ra.reservation_id: ra.room_number for ra in assignments}

        return [
            {
                "id": r.id,
                "customer_name": r.customer_name,
                "phone": r.phone,
                "check_in_date": r.check_in_date,
                "check_in_time": r.check_in_time,
                "room_number": room_map.get(r.id) or r.room_number,
            }
            for r in targets
        ]

    def _parse_date_filter(self, date_filter: str) -> str:
        """
        Parse date filter to YYYY-MM-DD format

        Args:
            date_filter: 'today', 'tomorrow', or 'YYYY-MM-DD'

        Returns:
            Date string in YYYY-MM-DD format or None
        """
        if date_filter == 'today':
            return date.today().strftime('%Y-%m-%d')
        elif date_filter == 'tomorrow':
            return (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        elif date_filter and len(date_filter) == 10:  # YYYY-MM-DD
            return date_filter
        return None
