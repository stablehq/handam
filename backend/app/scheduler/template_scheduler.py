"""
Template-based schedule execution engine
"""
import json
import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.db.models import TemplateSchedule, Reservation, RoomAssignment, ReservationSmsAssignment, Room
from app.factory import get_sms_provider
from app.templates.renderer import TemplateRenderer
from app.services.sms_tracking import record_sms_sent
from app.services.activity_logger import log_activity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Condition builder functions: (value, ctx) -> condition
# Each returns a SQLAlchemy condition (not applied to query directly).
# Same-type conditions are OR-ed; different types are AND-ed.
# ---------------------------------------------------------------------------

def _get_assigned_ids(ctx):
    """Helper: 해당 날짜에 RoomAssignment가 있는 예약 ID 서브쿼리."""
    target_date = ctx.get("target_date")
    return ctx["db"].query(RoomAssignment.reservation_id).filter(
        RoomAssignment.date == target_date
    ).subquery()


def _condition_by_tag(value, ctx):
    """Return condition for tag filter."""
    return Reservation.tags.like(f'%{value}%')


def _condition_by_assignment(value, ctx):
    """Return condition for assignment status: room / party / unassigned."""
    assigned_ids = _get_assigned_ids(ctx)
    if value == "room":
        return Reservation.id.in_(assigned_ids)
    elif value == "party":
        return and_(
            Reservation.id.notin_(assigned_ids),
            or_(
                Reservation.tags.like('%파티만%'),
                Reservation.naver_room_type.like('%파티만%'),
            )
        )
    elif value == "unassigned":
        return and_(
            Reservation.id.notin_(assigned_ids),
            ~or_(
                Reservation.tags.like('%파티만%'),
                Reservation.naver_room_type.like('%파티만%'),
            )
        )
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


FILTER_BUILDERS = {
    "tag": _condition_by_tag,
    "assignment": _condition_by_assignment,
    "building": _condition_by_building,
    "room": _condition_by_room,
    # 레거시 호환
    "room_assigned": lambda v, ctx: _condition_by_assignment("room", ctx),
    "party_only": lambda v, ctx: _condition_by_assignment("party", ctx),
}


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
                schedule.last_run_at = datetime.now()
                self.db.commit()
                return {"success": True, "sent_count": 0, "message": "No targets found"}

            # Send messages
            sent_count = 0
            failed_count = 0

            target_date = self._parse_date_filter(schedule.date_filter) if schedule.date_filter else None

            for reservation in targets:
                try:
                    # Render template with reservation data
                    context = self._build_template_context(reservation, target_date=target_date)

                    # Always use the schedule's own template (building override removed)
                    template_key = schedule.template.template_key

                    message_content = self.template_renderer.render(
                        template_key,
                        context
                    )

                    # Send SMS
                    result = await self.sms_provider.send_sms(
                        to=reservation.phone,
                        message=message_content
                    )

                    if result.get('success'):
                        sent_count += 1

                        record_sms_sent(
                            self.db,
                            reservation.id,
                            schedule.template.template_key,
                            schedule.template.category,
                            assigned_by='schedule',
                        )

                        self.db.flush()
                        logger.info(f"Sent SMS to {reservation.customer_name} ({reservation.phone})")
                    else:
                        failed_count += 1
                        logger.error(f"Failed to send SMS to {reservation.phone}: {result.get('error')}")

                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error sending SMS to reservation #{reservation.id}: {str(e)}")

            # Update schedule
            schedule.last_run_at = datetime.now()

            # 활동 로그 기록
            log_activity(
                self.db,
                type="sms_template",
                title=f"스케줄 발송: {schedule.schedule_name}",
                target_count=len(targets),
                success_count=sent_count,
                failed_count=failed_count,
                status="success" if failed_count == 0 else ("partial" if sent_count > 0 else "failed"),
                created_by="system",
            )

            self.db.commit()

            logger.info(f"Schedule #{schedule_id} execution completed: {sent_count} sent, {failed_count} failed")

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

        Uses the new ``filters`` JSON column (AND-chained).  Falls back to
        legacy ``target_type`` / ``target_value`` when ``filters`` is empty.

        Args:
            schedule: TemplateSchedule instance
            exclude_sent: When True (default), exclude reservations already sent via this template.

        Returns:
            List of Reservation instances
        """
        query = self.db.query(Reservation).filter(
            Reservation.status == 'confirmed'
        )

        # Safety guard: never send to reservations more than 1 day out
        max_date = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        query = query.filter(Reservation.check_in_date <= max_date)

        # Apply date filter
        target_date = None
        if schedule.date_filter:
            target_date = self._parse_date_filter(schedule.date_filter)
            if target_date:
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

        # Legacy fallback: if filters is empty and target_type is set
        if not filters and schedule.target_type and schedule.target_type != 'all':
            if schedule.target_type == 'tag' and schedule.target_value:
                filters = [{"type": "tag", "value": schedule.target_value}]
            elif schedule.target_type in ('room_assigned', 'party_only'):
                filters = [{"type": schedule.target_type, "value": "true"}]

        # Apply filters: OR within same type, AND between types
        ctx = {"db": self.db, "target_date": target_date}

        # Group filters by type
        filter_groups: dict = defaultdict(list)
        for f in filters:
            filter_groups[f.get("type", "")].append(f.get("value", ""))

        for filter_type, values in filter_groups.items():
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
            query = query.filter(
                ~exists().where(
                    (ReservationSmsAssignment.reservation_id == Reservation.id) &
                    (ReservationSmsAssignment.template_key == schedule.template.template_key) &
                    (ReservationSmsAssignment.sent_at.isnot(None))
                )
            )

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
            existing = self.db.query(ReservationSmsAssignment).filter(
                ReservationSmsAssignment.reservation_id == reservation.id,
                ReservationSmsAssignment.template_key == template_key,
            ).first()
            if not existing:
                self.db.add(ReservationSmsAssignment(
                    reservation_id=reservation.id,
                    template_key=template_key,
                    assigned_by='schedule',
                    sent_at=None,
                ))
                created += 1

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

        return [
            {
                "id": r.id,
                "customer_name": r.customer_name,
                "phone": r.phone,
                "check_in_date": r.check_in_date,
                "check_in_time": r.check_in_time,
                "room_number": r.room_number,
                "tags": r.tags,
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

    def _build_template_context(self, reservation: Reservation, target_date: str = None) -> Dict[str, Any]:
        """
        Build template rendering context from reservation

        Args:
            reservation: Reservation instance
            target_date: Optional date string to look up RoomAssignment

        Returns:
            Context dict with all available variables
        """
        # Look up RoomAssignment for target date if provided
        room_number = reservation.room_number or ""
        room_password = reservation.room_password or ""
        if target_date:
            assignment = self.db.query(RoomAssignment).filter(
                RoomAssignment.reservation_id == reservation.id,
                RoomAssignment.date == target_date,
            ).first()
            if assignment:
                room_number = assignment.room_number or ""
                room_password = assignment.room_password or ""

        # Parse room number for building/room_num
        building = ""
        room_num = ""
        if room_number:
            if len(room_number) >= 2:
                building = room_number[0]
                room_num = room_number[1:]
            else:
                room_num = room_number

        return {
            "customer_name": reservation.customer_name,
            "phone": reservation.phone,
            "building": building,
            "room_num": room_num,
            "naver_room_type": reservation.naver_room_type or "",
            "room_password": room_password,
            "participant_count": str(reservation.party_size or 0),
            "male_count": str(reservation.male_count or 0),
            "female_count": str(reservation.female_count or 0),
        }
