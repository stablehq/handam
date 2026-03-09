"""
APScheduler jobs for automated SMS sending
Ported from stable-clasp-main/03_trigger.js
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

from ..db.database import SessionLocal
from ..factory import get_reservation_provider, get_sms_provider, get_storage_provider
from ..notifications.service import NotificationService
from ..analytics.gender_analyzer import GenderAnalyzer

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
        from ..api.reservations_sync import sync_naver_to_db

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


async def extract_gender_stats_job():
    """
    Extract gender statistics from Google Sheets
    Runs every hour during party hours
    """
    logger.info("Running gender stats extraction job")

    db = SessionLocal()
    try:
        storage_provider = get_storage_provider()
        analyzer = GenderAnalyzer(db, storage_provider)

        today = datetime.now()
        stat = await analyzer.extract_gender_stats(today)

        if stat:
            logger.info(f"Gender stats extracted: M={stat.male_count}, F={stat.female_count}")

            # Log balance analysis
            balance = analyzer.calculate_party_balance(stat)
            logger.info(f"Party balance: {balance['recommendation']}")
        else:
            logger.warning("No gender stats extracted")

    except Exception as e:
        logger.error(f"Error in gender stats job: {e}")
    finally:
        db.close()


def setup_scheduler():
    """
    Setup all scheduled jobs

    Schedule based on stable-clasp-main/03_trigger.js:
    - Naver sync: Every 10 min, 10:10-21:59
    - Gender stats: Every hour, 10:00-22:00
    - Template schedules: Loaded dynamically from DB
    """
    # Naver reservations sync - every 5 minutes from 10:00 to 21:59
    scheduler.add_job(
        sync_naver_reservations_job,
        trigger=CronTrigger(
            hour='10-21',
            minute='*/5',
            timezone='Asia/Seoul'
        ),
        id='sync_naver_reservations',
        name='Sync Naver Reservations',
        replace_existing=True
    )

    # Gender stats extraction - hourly
    scheduler.add_job(
        extract_gender_stats_job,
        trigger=CronTrigger(
            hour='10-22',
            minute='0',
            timezone='Asia/Seoul'
        ),
        id='extract_gender_stats',
        name='Extract Gender Stats',
        replace_existing=True
    )

    # Load template schedules on startup
    scheduler.add_job(
        load_template_schedules,
        trigger='date',
        run_date=datetime.now(),
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
