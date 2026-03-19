"""
APScheduler jobs for automated SMS sending
Ported from stable-clasp-main/03_trigger.js
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone
import logging

from app.db.database import SessionLocal
from app.factory import get_reservation_provider, get_sms_provider
from app.scheduler.room_auto_assign import daily_assign_rooms

logger = logging.getLogger(__name__)

# Create scheduler instance
scheduler = AsyncIOScheduler()


async def sync_naver_reservations_job():
    """
    Sync reservations from Naver Smart Place API
    Runs every 10 minutes from 10:10 to 21:59

    Ported from: stable-clasp-main/03_trigger.js:1-16 (processTodayAuto)
    """
    logger.info("Running Naver reservations sync job")

    db = SessionLocal()
    try:
        from app.api.reservations_sync import sync_naver_to_db

        reservation_provider = get_reservation_provider()
        result = await sync_naver_to_db(reservation_provider, db)
        logger.info(f"Scheduler sync result: {result['message']}")

    except Exception as e:
        logger.error(f"Error in reservation sync job: {e}")
        db.rollback()
    finally:
        db.close()


async def load_template_schedules():
    """
    Load all active template schedules into APScheduler
    Called on startup
    """
    logger.info("Loading template schedules")

    db = SessionLocal()
    try:
        from .schedule_manager import ScheduleManager
        schedule_manager = ScheduleManager(scheduler)
        schedule_manager.sync_all_schedules(db)

        logger.info("Template schedules loaded successfully")

    except Exception as e:
        logger.error(f"Error loading template schedules: {e}")
    finally:
        db.close()


async def sync_status_log_job():
    """
    6시간 단위 동기화 상태 활동 로그.
    00:00, 06:00, 12:00, 18:00에 실행.
    """
    from zoneinfo import ZoneInfo
    from app.services.activity_logger import log_activity

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    current_hour = now.hour
    # 이전 6시간 구간 계산
    period_start = f"{(current_hour - 6) % 24:02d}:00"
    period_end = f"{current_hour:02d}:00"

    db = SessionLocal()
    try:
        log_activity(
            db,
            type="sync_status",
            title=f"네이버 동기화 정상 운영 ({period_start}~{period_end})",
            detail={"period_start": period_start, "period_end": period_end},
            created_by="scheduler",
        )
        db.commit()
        logger.info(f"Sync status log recorded: {period_start}~{period_end}")
    except Exception as e:
        logger.error(f"Error logging sync status: {e}")
        db.rollback()
    finally:
        db.close()


async def daily_room_assign_job():
    """
    Daily room auto-assignment for today and tomorrow.
    Only fills missing assignments, never overwrites manual ones.
    """
    logger.info("Running daily room auto-assignment job")

    db = SessionLocal()
    try:
        result = daily_assign_rooms(db)
        logger.info(f"Daily room auto-assignment result: {result}")
    except Exception as e:
        logger.error(f"Error in daily room auto-assignment job: {e}")
        db.rollback()
    finally:
        db.close()


def setup_scheduler():
    """
    Setup all scheduled jobs

    Schedule based on stable-clasp-main/03_trigger.js:
    - Naver sync: Every 5 min, 24h
    - Template schedules: Loaded dynamically from DB
    """
    # Naver reservations sync - every 5 minutes, 24h
    scheduler.add_job(
        sync_naver_reservations_job,
        trigger=CronTrigger(
            minute='*/5',
            timezone='Asia/Seoul'
        ),
        id='sync_naver_reservations',
        name='Sync Naver Reservations',
        replace_existing=True
    )

    # Daily room auto-assignment - 10am KST (당일+내일)
    scheduler.add_job(
        daily_room_assign_job,
        trigger=CronTrigger(hour=10, minute=0, timezone='Asia/Seoul'),
        id='daily_room_assign',
        name='객실 자동 배정 (오전 10시)',
        replace_existing=True,
    )

    # Sync status log - every 6 hours (00, 06, 12, 18)
    scheduler.add_job(
        sync_status_log_job,
        trigger=CronTrigger(hour='0,6,12,18', minute=0, timezone='Asia/Seoul'),
        id='sync_status_log',
        name='동기화 상태 로그 (6시간)',
        replace_existing=True,
    )

    # Load template schedules on startup
    scheduler.add_job(
        load_template_schedules,
        trigger='date',
        run_date=datetime.now(timezone.utc),
        id='load_template_schedules',
        name='Load Template Schedules',
        replace_existing=True
    )

    logger.info("Scheduler jobs configured")


def start_scheduler():
    """Start the scheduler"""
    setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    """Stop the scheduler"""
    scheduler.shutdown()
    logger.info("Scheduler stopped")


def get_job_info():
    """Get information about scheduled jobs"""
    jobs = scheduler.get_jobs()
    return [
        {
            'id': job.id,
            'name': job.name,
            'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
            'trigger': str(job.trigger)
        }
        for job in jobs
    ]
