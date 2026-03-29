"""
Schedule manager for APScheduler and DB synchronization
"""
import logging
from datetime import datetime, timezone as tz

from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy.orm import Session

from app.db.models import TemplateSchedule, Tenant
from app.db.tenant_context import current_tenant_id
from app.scheduler.template_scheduler import TemplateScheduleExecutor

logger = logging.getLogger(__name__)


class ScheduleManager:
    """Manage template schedules with APScheduler"""

    def __init__(self, scheduler: AsyncIOScheduler):
        self.scheduler = scheduler

    def sync_all_schedules(self, db: Session):
        """
        Sync all active template schedules from DB to APScheduler

        Args:
            db: Database session
        """
        logger.info("Syncing all template schedules to APScheduler")

        # Get all active schedules
        schedules = db.query(TemplateSchedule).filter(
            TemplateSchedule.is_active == True
        ).all()

        # Remove existing template schedule jobs
        existing_jobs = self.scheduler.get_jobs()
        for job in existing_jobs:
            if job.id.startswith('template_schedule_'):
                self.scheduler.remove_job(job.id)
                logger.info(f"Removed existing job: {job.id}")

        # Add all active schedules (skip expired ones)
        for schedule in schedules:
            # Auto-deactivate expired schedules
            if schedule.expires_at and datetime.now(tz.utc) >= schedule.expires_at:
                schedule.is_active = False
                db.commit()
                logger.info(f"Schedule #{schedule.id} expired during sync, deactivated")
                continue
            try:
                self.add_schedule_job(schedule, db)
                logger.info(f"Added schedule #{schedule.id}: {schedule.schedule_name}")
            except Exception as e:
                logger.error(f"Failed to add schedule #{schedule.id}: {str(e)}")

        logger.info(f"Sync completed: {len(schedules)} schedules loaded")

    def add_schedule_job(self, schedule: TemplateSchedule, db: Session):
        """
        Add a schedule to APScheduler

        Args:
            schedule: TemplateSchedule instance
            db: Database session for updating next_run
        """
        job_id = f"template_schedule_{schedule.id}"

        # Create trigger based on schedule_type
        trigger = self._create_trigger(schedule)

        if not trigger:
            logger.error(f"Failed to create trigger for schedule #{schedule.id}")
            return

        # Capture only schedule ID to avoid detached instance errors
        schedule_id_captured = schedule.id

        # Create executor function
        async def execute_job():
            from app.db.database import SessionLocal
            db_session = SessionLocal()
            try:
                # Re-fetch schedule from fresh session
                fresh_schedule = db_session.query(TemplateSchedule).filter(
                    TemplateSchedule.id == schedule_id_captured
                ).first()
                if not fresh_schedule:
                    logger.error(f"Schedule #{schedule_id_captured} not found")
                    return

                # Check expiry
                if fresh_schedule.expires_at and datetime.now(tz.utc) >= fresh_schedule.expires_at:
                    fresh_schedule.is_active = False
                    db_session.commit()
                    try:
                        self.scheduler.remove_job(f"template_schedule_{schedule_id_captured}")
                    except JobLookupError:
                        pass
                    logger.info(f"Schedule #{schedule_id_captured} expired, deactivated")
                    return

                # Check active hours for hourly/interval schedules
                if fresh_schedule.active_start_hour is not None and fresh_schedule.active_end_hour is not None:
                    from zoneinfo import ZoneInfo
                    local_tz = ZoneInfo(fresh_schedule.timezone or "Asia/Seoul")
                    now_hour = datetime.now(local_tz).hour
                    start_h = fresh_schedule.active_start_hour
                    end_h = fresh_schedule.active_end_hour
                    if start_h <= end_h:
                        if not (start_h <= now_hour < end_h):
                            logger.info(
                                f"Skipping schedule #{schedule_id_captured}: outside active hours "
                                f"({start_h}-{end_h}, current={now_hour})"
                            )
                            return
                    else:
                        if end_h <= now_hour < start_h:
                            logger.info(
                                f"Skipping schedule #{schedule_id_captured}: outside active hours "
                                f"({start_h}-{end_h}, current={now_hour})"
                            )
                            return
            finally:
                db_session.close()

            db_session = SessionLocal()
            token = None
            try:
                # Re-fetch schedule to get tenant_id for provider selection
                exec_schedule = db_session.query(TemplateSchedule).filter(
                    TemplateSchedule.id == schedule_id_captured
                ).first()
                tenant = None
                if exec_schedule and exec_schedule.tenant_id:
                    tenant = db_session.query(Tenant).filter(
                        Tenant.id == exec_schedule.tenant_id
                    ).first()
                # Set tenant context so queries are auto-filtered
                if tenant:
                    token = current_tenant_id.set(tenant.id)
                executor = TemplateScheduleExecutor(db_session, tenant=tenant)
                await executor.execute_schedule(schedule_id_captured)
            finally:
                if token is not None:
                    current_tenant_id.reset(token)
                db_session.close()

        # Add job to scheduler
        job = self.scheduler.add_job(
            execute_job,
            trigger=trigger,
            id=job_id,
            name=schedule.schedule_name,
            replace_existing=True
        )

        # Update next_run in database
        if job.next_run_time:
            schedule.next_run_at = job.next_run_time
            db.commit()

        logger.info(f"Added job {job_id}, next run: {job.next_run_time}")

    def remove_schedule_job(self, schedule_id: int):
        """
        Remove a schedule from APScheduler

        Args:
            schedule_id: Template schedule ID
        """
        job_id = f"template_schedule_{schedule_id}"

        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job {job_id}")
        except Exception as e:
            logger.warning(f"Failed to remove job {job_id}: {str(e)}")

    def update_schedule_job(self, schedule: TemplateSchedule, db: Session):
        """
        Update an existing schedule job

        Args:
            schedule: Updated TemplateSchedule instance
            db: Database session
        """
        # Remove old job and add new one
        self.remove_schedule_job(schedule.id)

        if schedule.is_active:
            self.add_schedule_job(schedule, db)
        else:
            logger.info(f"Schedule #{schedule.id} is inactive, not adding to scheduler")

    def _create_trigger(self, schedule: TemplateSchedule):
        """
        Create APScheduler trigger based on schedule configuration

        Args:
            schedule: TemplateSchedule instance

        Returns:
            CronTrigger or IntervalTrigger instance
        """
        timezone = schedule.timezone or "Asia/Seoul"

        if schedule.schedule_type == 'daily':
            # Daily at specific time
            return CronTrigger(
                hour=schedule.hour,
                minute=schedule.minute,
                timezone=timezone
            )

        elif schedule.schedule_type == 'weekly':
            # Weekly on specific days at specific time
            if not schedule.day_of_week:
                logger.error(f"Weekly schedule #{schedule.id} missing day_of_week")
                return None

            # Convert 'mon,tue,wed' to 'mon-wed' or '0-2' format
            days = schedule.day_of_week.lower()

            return CronTrigger(
                day_of_week=days,
                hour=schedule.hour,
                minute=schedule.minute,
                timezone=timezone
            )

        elif schedule.schedule_type == 'hourly':
            # Every hour at specific minute
            return CronTrigger(
                minute=schedule.minute,
                timezone=timezone
            )

        elif schedule.schedule_type == 'interval':
            # Every N minutes using CronTrigger for precise hour range control
            if not schedule.interval_minutes:
                logger.error(f"Interval schedule #{schedule.id} missing interval_minutes")
                return None

            # Build minute spec: */N
            minute_spec = f'*/{schedule.interval_minutes}'

            # Build hour spec from active hours
            start_h = schedule.active_start_hour
            end_h = schedule.active_end_hour
            if start_h is not None and end_h is not None and start_h < end_h:
                hour_spec = f'{start_h}-{end_h - 1}'
            else:
                hour_spec = '*'

            return CronTrigger(
                minute=minute_spec,
                hour=hour_spec,
                timezone=timezone,
            )

        else:
            logger.error(f"Unknown schedule_type: {schedule.schedule_type}")
            return None


    def get_all_jobs(self) -> list:
        """
        Get all scheduled jobs info

        Returns:
            List of job info dicts
        """
        jobs = self.scheduler.get_jobs()
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger)
            }
            for job in jobs
        ]
