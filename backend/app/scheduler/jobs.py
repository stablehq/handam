"""
APScheduler jobs for automated SMS sending
Ported from stable-clasp-main/03_trigger.js
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone, timedelta
import logging

from app.db.database import SessionLocal
from app.db.models import Tenant
from app.db.tenant_context import current_tenant_id, bypass_tenant_filter
from app.factory import get_reservation_provider_for_tenant
from app.services.room_auto_assign import daily_assign_rooms
from app.config import KST

logger = logging.getLogger(__name__)


def _for_each_tenant(job_fn):
    """Execute a job function for each active tenant with proper context."""
    db = SessionLocal()
    try:
        token_bypass = bypass_tenant_filter.set(True)
        try:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        finally:
            bypass_tenant_filter.reset(token_bypass)
    finally:
        db.close()

    for tenant in tenants:
        token = current_tenant_id.set(tenant.id)
        db = SessionLocal()
        try:
            job_fn(db, tenant)
            db.commit()
        except Exception as e:
            logger.error(f"[{tenant.slug}] Job error: {e}")
            try:
                import sentry_sdk
                sentry_sdk.set_tag("tenant_slug", tenant.slug)
                sentry_sdk.capture_exception(e)
            except ImportError:
                pass
            db.rollback()
        finally:
            db.close()
            current_tenant_id.reset(token)

# Create scheduler instance
scheduler = AsyncIOScheduler()


async def sync_naver_reservations_job():
    """
    [Phase 1 진입점] 5분마다 네이버 예약 동기화.

    전체 흐름:
      Phase 1: 네이버 API 호출 → 예약 데이터 수신
      Phase 2: enrichment(상품명/인원/성별) + DB 저장 (Reservation INSERT/UPDATE)
      Phase 3: ★ 칩 reconcile (1차) — 아직 방 미배정이라 building 필터 칩은 미생성
      Phase 4: 연박 감지 → stay_group 링크
      Phase 5: 자동 객실 배정 → assign_room() 내부에서 ★ 칩 reconcile (2차) → building 필터 통과

    모든 Phase는 sync_naver_to_db() 내부에서 순차 실행됨.
    """
    logger.info("Running Naver reservations sync job (all tenants)")

    from app.services.naver_sync import sync_naver_to_db

    # Fetch all active tenants without tenant context restriction
    token_bypass = bypass_tenant_filter.set(True)
    try:
        db = SessionLocal()
        try:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        finally:
            db.close()
    finally:
        bypass_tenant_filter.reset(token_bypass)

    for tenant in tenants:
        token = current_tenant_id.set(tenant.id)
        db = SessionLocal()
        try:
            reservation_provider = get_reservation_provider_for_tenant(tenant)
            result = await sync_naver_to_db(reservation_provider, db)
            logger.info(f"[{tenant.slug}] Scheduler sync result: {result['message']}")
        except Exception as e:
            logger.error(f"[{tenant.slug}] Error in reservation sync job: {e}")
            db.rollback()
        finally:
            db.close()
            current_tenant_id.reset(token)


async def load_template_schedules():
    """
    Load all active template schedules into APScheduler
    Called on startup — loads ALL tenants' schedules (bypass tenant filter)
    """
    logger.info("Loading template schedules")

    bypass_token = bypass_tenant_filter.set(True)
    try:
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
    finally:
        bypass_tenant_filter.reset(bypass_token)


async def sync_status_log_job():
    """
    6시간 단위 동기화 상태 활동 로그.
    00:00, 06:00, 12:00, 18:00에 실행.
    Iterates over all active tenants.
    """
    from app.services.activity_logger import log_activity

    now = datetime.now(KST)
    current_hour = now.hour
    # 이전 6시간 구간 계산
    period_start = f"{(current_hour - 6) % 24:02d}:00"
    period_end = f"{current_hour:02d}:00"

    def _log_status(db, tenant):
        source_label = "[스테이블] " if tenant.unstable_business_id else ""
        log_activity(
            db,
            type="naver_sync",
            title=f"{source_label}네이버 예약 동기화 : 자동 실행 ({period_start}~{period_end})",
            detail={"period_start": period_start, "period_end": period_end},
            created_by="scheduler",
        )
        logger.info(f"[{tenant.slug}] Sync status log recorded: {period_start}~{period_end}")

    _for_each_tenant(_log_status)


async def detect_consecutive_stays_job():
    """
    Detect and link consecutive stays (연박) for all active tenants.
    Runs 4 times daily (9, 10, 11, 12 KST) as a safety net.
    Primary detection happens inline after each Naver sync.
    """
    logger.info("Running consecutive stay detection job (all tenants)")

    from app.services.consecutive_stay import detect_and_link_consecutive_stays

    def _detect(db, tenant):
        result = detect_and_link_consecutive_stays(db)
        if result["linked"] > 0 or result["unlinked"] > 0:
            logger.info(f"[{tenant.slug}] Consecutive stay detection: {result}")

    _for_each_tenant(_detect)


async def reconcile_today_reservations_job():
    """
    Daily reconciliation: fetch today+tomorrow check-in reservations by STARTDATE filter.
    Catches any reservations missed by the regular 5-min REGDATE sync.
    Runs at 09:55 KST, before daily room assignment at 10:00.
    """
    from app.services.naver_sync import sync_naver_to_db
    from app.services.activity_logger import log_activity

    today = datetime.now(KST).strftime("%Y-%m-%d")
    from datetime import timedelta as _td
    tomorrow = (datetime.now(KST) + _td(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Running daily reconciliation for {today} and {tomorrow} (all tenants)")

    token_bypass = bypass_tenant_filter.set(True)
    try:
        db = SessionLocal()
        try:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        finally:
            db.close()
    finally:
        bypass_tenant_filter.reset(token_bypass)

    for tenant in tenants:
        token = current_tenant_id.set(tenant.id)
        db = SessionLocal()
        try:
            reservation_provider = get_reservation_provider_for_tenant(tenant)
            total_added = 0
            for target_date in [today, tomorrow]:
                result = await sync_naver_to_db(reservation_provider, db, reconcile_date=target_date)
                added = result.get("added", 0)
                total_added += added
                if added > 0:
                    logger.info(f"[{tenant.slug}] Reconcile {target_date}: +{added} reservations")

            if total_added > 0:
                source_label = "[스테이블] " if tenant.unstable_business_id else ""
                log_activity(
                    db,
                    type="naver_reconcile",
                    title=f"{source_label}네이버 예약 대사 : 스케줄 ({today}~{tomorrow})",
                    detail={"today": today, "tomorrow": tomorrow, "added": total_added},
                    target_count=total_added,
                    success_count=total_added,
                    created_by="scheduler",
                )
                db.commit()
                logger.info(f"[{tenant.slug}] Reconciliation complete: {total_added} added")
            else:
                logger.info(f"[{tenant.slug}] Reconciliation: no missing reservations")

            # 언스테이블 reconciliation (USEDATE 기반)
            if tenant.unstable_business_id and tenant.unstable_cookie:
                from app.real.reservation import RealReservationProvider
                unstable_provider = RealReservationProvider(
                    business_id=tenant.unstable_business_id,
                    cookie=tenant.unstable_cookie,
                )
                unstable_added = 0
                for target_date in [today, tomorrow]:
                    result = await sync_naver_to_db(unstable_provider, db, reconcile_date=target_date, source="unstable")
                    added = result.get("added", 0)
                    unstable_added += added
                    if added > 0:
                        logger.info(f"[{tenant.slug}] Unstable reconcile {target_date}: +{added} reservations")
                if unstable_added > 0:
                    log_activity(
                        db,
                        type="naver_reconcile",
                        title=f"[언스테이블] 네이버 예약 대사 : 스케줄 ({today}~{tomorrow})",
                        detail={"source": "unstable", "today": today, "tomorrow": tomorrow, "added": unstable_added},
                        target_count=unstable_added,
                        success_count=unstable_added,
                        created_by="scheduler",
                    )
                    db.commit()
                    logger.info(f"[{tenant.slug}] Unstable reconciliation complete: {unstable_added} added")

        except Exception as e:
            logger.error(f"[{tenant.slug}] Reconciliation error: {e}")
            db.rollback()
        finally:
            db.close()
            current_tenant_id.reset(token)


async def sync_unstable_reservations_job():
    """
    Sync reservations from Unstable Naver Smart Place.
    Runs every 6 hours. Only for tenants with unstable_business_id configured.
    """
    from app.real.reservation import RealReservationProvider
    from app.services.naver_sync import sync_naver_to_db

    logger.info("Running Unstable reservations sync job")

    token_bypass = bypass_tenant_filter.set(True)
    try:
        db = SessionLocal()
        try:
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        finally:
            db.close()
    finally:
        bypass_tenant_filter.reset(token_bypass)

    for tenant in tenants:
        if not tenant.unstable_business_id or not tenant.unstable_cookie:
            continue

        token = current_tenant_id.set(tenant.id)
        db = SessionLocal()
        try:
            provider = RealReservationProvider(
                business_id=tenant.unstable_business_id,
                cookie=tenant.unstable_cookie,
            )
            result = await sync_naver_to_db(provider, db, source="unstable")
            logger.info(f"[{tenant.slug}] Unstable sync result: {result['message']}")
            if result.get("added", 0) > 0:
                from app.services.activity_logger import log_activity
                log_activity(
                    db,
                    type="naver_sync",
                    title=f"[언스테이블] 네이버 예약 동기화 : {result['message']}",
                    detail={"source": "unstable", "added": result["added"], "updated": result["updated"]},
                    target_count=result.get("synced", 0),
                    success_count=result.get("added", 0),
                    created_by="scheduler",
                )
                db.commit()
        except Exception as e:
            logger.error(f"[{tenant.slug}] Error in unstable sync job: {e}")
            db.rollback()
        finally:
            db.close()
            current_tenant_id.reset(token)


async def daily_room_assign_job():
    """
    Daily room auto-assignment for today and tomorrow.
    Only fills missing assignments, never overwrites manual ones.
    Iterates over all active tenants.
    """
    logger.info("Running daily room auto-assignment job (all tenants)")

    def _assign(db, tenant):
        result = daily_assign_rooms(db)
        logger.info(f"[{tenant.slug}] Daily room auto-assignment result: {result}")

    _for_each_tenant(_assign)


def refresh_snapshots_job():
    """Refresh participant snapshots for all tenants (today + tomorrow).
    Called at specific cron times (e.g., 08:50, 11:50).
    """
    from app.templates.variables import refresh_snapshot

    logger.info("[Scheduler] Refreshing participant snapshots...")

    def _job(db, tenant):
        now = datetime.now(KST)
        today_str = now.strftime('%Y-%m-%d')
        tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')

        refreshed = []
        for date_str in [today_str, tomorrow_str]:
            result = refresh_snapshot(db, date_str)
            if result:
                refreshed.append(date_str)

        if refreshed:
            logger.info(f"[Snapshot Refresh] tenant={tenant.slug}: refreshed {', '.join(refreshed)}")

    _for_each_tenant(_job)


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

    # Unstable reservations sync - every 6 hours
    scheduler.add_job(
        sync_unstable_reservations_job,
        trigger=CronTrigger(hour='0,6,12,18', minute=5, timezone='Asia/Seoul'),
        id='sync_unstable_reservations',
        name='언스테이블 예약 동기화 (6시간)',
        replace_existing=True,
    )

    # Daily room auto-assignment - 10am KST (당일+내일)
    scheduler.add_job(
        daily_room_assign_job,
        trigger=CronTrigger(hour=10, minute=1, timezone='Asia/Seoul'),
        id='daily_room_assign',
        name='객실 자동 배정 (오전 10:01)',
        replace_existing=True,
    )

    # Daily reconciliation - 09:55 KST (before room assignment at 10:00)
    scheduler.add_job(
        reconcile_today_reservations_job,
        trigger=CronTrigger(hour=9, minute=55, timezone='Asia/Seoul'),
        id='reconcile_today_reservations',
        name='네이버 예약 대사 (오전 9:55)',
        replace_existing=True,
    )

    # Consecutive stay detection - 4 times daily (09, 10, 11, 12 KST)
    scheduler.add_job(
        detect_consecutive_stays_job,
        trigger=CronTrigger(hour='9,10,11,12', minute=0, timezone='Asia/Seoul'),
        id='detect_consecutive_stays',
        name='연박 감지 (하루 4회)',
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

    # Snapshot refresh - at 08:50 and 11:50 KST
    scheduler.add_job(
        refresh_snapshots_job,
        trigger=CronTrigger(hour=8, minute=50, timezone='Asia/Seoul'),
        id='refresh_snapshots_morning',
        name='참여자 스냅샷 갱신 (08:50)',
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_snapshots_job,
        trigger=CronTrigger(hour=11, minute=50, timezone='Asia/Seoul'),
        id='refresh_snapshots_noon',
        name='참여자 스냅샷 갱신 (11:50)',
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
