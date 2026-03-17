"""
Schedule manager for APScheduler and DB synchronization
"""
import logging
from datetime import datetime
from typing import Optional
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from app.db.models import TemplateSchedule
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

        # Add all active schedules
        for schedule in schedules:
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

                # Check active hours for hourly/interval schedules
                if fresh_schedule.active_start_hour is not None and fresh_schedule.active_end_hour is not None:
                    from zoneinfo import ZoneInfo
                    tz = ZoneInfo(fresh_schedule.timezone or "Asia/Seoul")
                    now_hour = datetime.now(tz).hour
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
            try:
                executor = TemplateScheduleExecutor(db_session)
                await executor.execute_schedule(schedule_id_captured)
            finally:
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

    def get_schedule_info(self, schedule_id: int) -> Optional[dict]:
        """
        Get APScheduler job info for a schedule

        Args:
            schedule_id: Template schedule ID

        Returns:
            Job info dict or None
        """
        job_id = f"template_schedule_{schedule_id}"

        try:
            job = self.scheduler.get_job(job_id)
            if job:
                return {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                }
        except Exception as e:
            logger.error(f"Error getting job info for {job_id}: {str(e)}")

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
