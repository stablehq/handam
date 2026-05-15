"""
APScheduler jobs for automated SMS sending
Ported from stable-clasp-main/03_trigger.js
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone, timedelta
import asyncio
import logging

from app.db.database import SessionLocal, session_for_tenant, session_bypass
from app.db.models import Tenant
# 옵션 C (Phase 6): ContextVar 제거됨
from app.diag_logger import diag
from app.factory import get_reservation_provider_for_tenant
from app.services.room_auto_assign import daily_assign_rooms
from app.config import KST, today_kst

logger = logging.getLogger(__name__)


def _for_each_tenant(job_fn):
    """Execute a job function for each active tenant with proper context.

    옵션 C (Phase 6): session_bypass() + session_for_tenant() 만 사용.
    session.info 가 tenant 컨텍스트를 들고 다님.
    """
    db = session_bypass()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    finally:
        db.close()

    for tenant in tenants:
        db = session_for_tenant(tenant.id)
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

    옵션 C (Phase 3): tenants 목록은 session_bypass(), per-tenant 작업은 session_for_tenant().
    """
    logger.info("Running Naver reservations sync job (all tenants)")
    diag("job.sync_naver_reservations.enter", level="verbose")

    from app.services.naver_sync import sync_naver_to_db

    # tenants 목록 — cross-tenant 조회
    db = session_bypass()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    finally:
        db.close()

    for tenant in tenants:
        db = session_for_tenant(tenant.id)
        try:
            reservation_provider = get_reservation_provider_for_tenant(tenant)
            result = await sync_naver_to_db(reservation_provider, db)
            logger.info(f"[{tenant.slug}] Scheduler sync result: {result['message']}")
        except asyncio.CancelledError:
            logger.info(f"[{tenant.slug}] Naver sync cancelled (shutdown)")
            db.rollback()
            raise
        except Exception as e:
            logger.error(f"[{tenant.slug}] Error in reservation sync job: {e}")
            diag(
                "job.sync_naver_reservations.tenant_failed",
                level="critical",
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                error=str(e),
            )
            db.rollback()
        finally:
            db.close()

    diag("job.sync_naver_reservations.exit", level="verbose", tenants=len(tenants))


async def load_template_schedules():
    """
    Load all active template schedules into APScheduler
    Called on startup — loads ALL tenants' schedules (bypass tenant filter).

    옵션 C (Phase 3): session_bypass() 사용 — 모든 tenant 스케줄 cross-tenant 조회.
    """
    logger.info("Loading template schedules")

    db = session_bypass()
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
    diag("job.detect_consecutive_stays.enter", level="verbose")

    from app.services.consecutive_stay import detect_and_link_consecutive_stays

    totals = {"linked": 0, "unlinked": 0, "groups": 0, "tenants": 0}

    def _detect(db, tenant):
        try:
            result = detect_and_link_consecutive_stays(db)
        except Exception as e:
            diag(
                "job.detect_consecutive_stays.tenant_failed",
                level="critical",
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                error=str(e),
            )
            return
        totals["tenants"] += 1
        totals["linked"] += result.get("linked", 0)
        totals["unlinked"] += result.get("unlinked", 0)
        totals["groups"] += result.get("groups", 0)
        if result["linked"] > 0 or result["unlinked"] > 0:
            logger.info(f"[{tenant.slug}] Consecutive stay detection: {result}")

    _for_each_tenant(_detect)

    diag(
        "job.detect_consecutive_stays.exit",
        level="verbose",
        tenants=totals["tenants"],
        linked=totals["linked"],
        unlinked=totals["unlinked"],
        groups=totals["groups"],
    )


async def reconcile_today_reservations_job():
    """
    Daily reconciliation: fetch today+tomorrow check-in reservations by STARTDATE filter.
    Catches any reservations missed by the regular 5-min REGDATE sync.
    Runs at 09:55 KST, before daily room assignment at 10:00.

    옵션 C (Phase 3): tenants 목록 session_bypass(), per-tenant session_for_tenant().
    """
    from app.services.naver_sync import sync_naver_to_db
    from app.services.activity_logger import log_activity

    today = today_kst()
    from datetime import timedelta as _td
    tomorrow = (datetime.now(KST) + _td(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Running daily reconciliation for {today} and {tomorrow} (all tenants)")

    db = session_bypass()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    finally:
        db.close()

    for tenant in tenants:
        db = session_for_tenant(tenant.id)
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

        except asyncio.CancelledError:
            logger.info(f"[{tenant.slug}] Reconciliation cancelled (shutdown)")
            db.rollback()
            raise
        except Exception as e:
            logger.error(f"[{tenant.slug}] Reconciliation error: {e}")
            db.rollback()
        finally:
            db.close()


async def sync_unstable_reservations_job():
    """
    Sync reservations from Unstable Naver Smart Place.
    Runs every 6 hours. Only for tenants with unstable_business_id configured.

    옵션 C (Phase 3): tenants 목록 session_bypass(), per-tenant session_for_tenant().
    """
    from app.real.reservation import RealReservationProvider
    from app.services.naver_sync import sync_naver_to_db

    logger.info("Running Unstable reservations sync job")

    db = session_bypass()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    finally:
        db.close()

    diag("job.sync_unstable_reservations.enter", level="verbose",
         tenant_count=len(tenants))

    sync_results = []
    for tenant in tenants:
        if not tenant.unstable_business_id or not tenant.unstable_cookie:
            continue

        db = session_for_tenant(tenant.id)
        try:
            provider = RealReservationProvider(
                business_id=tenant.unstable_business_id,
                cookie=tenant.unstable_cookie,
            )
            result = await sync_naver_to_db(provider, db, source="unstable")
            sync_results.append({
                "tenant_id": tenant.id,
                "added": result.get("added", 0),
                "updated": result.get("updated", 0),
                "synced": result.get("synced", 0),
            })
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
        except asyncio.CancelledError:
            logger.info(f"[{tenant.slug}] Unstable sync cancelled (shutdown)")
            db.rollback()
            raise
        except Exception as e:
            logger.error(f"[{tenant.slug}] Error in unstable sync job: {e}")
            diag("job.sync_unstable_reservations.tenant_failed", level="critical",
                 tenant_id=tenant.id, error=str(e)[:200])
            db.rollback()
        finally:
            db.close()

    diag("job.sync_unstable_reservations.exit", level="critical",
         active_tenants=len(sync_results),
         total_added=sum(r["added"] for r in sync_results),
         total_updated=sum(r["updated"] for r in sync_results),
         total_synced=sum(r["synced"] for r in sync_results))


async def daily_room_assign_job():
    """
    Daily room auto-assignment for today and tomorrow.
    Only fills missing assignments, never overwrites manual ones.
    Iterates over all active tenants.
    """
    logger.info("Running daily room auto-assignment job (all tenants)")
    diag("job.daily_room_assign.enter", level="verbose")

    def _assign(db, tenant):
        result = daily_assign_rooms(db)
        logger.info(f"[{tenant.slug}] Daily room auto-assignment result: {result}")

    _for_each_tenant(_assign)
    diag("job.daily_room_assign.exit", level="verbose")


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
        replace_existing=True,
        coalesce=True,           # missed fire 누적 시 1번만 catch-up
        misfire_grace_time=60,   # 60초 이내 늦은 fire 허용
        max_instances=1,
    )

    # Unstable reservations sync — 피크(15~20시)는 10분 간격, 그 외엔 00:05 / 12:05 하루 2회
    scheduler.add_job(
        sync_unstable_reservations_job,
        trigger=CronTrigger(hour='15-20', minute='*/10', timezone='Asia/Seoul'),
        id='sync_unstable_reservations_peak',
        name='언스테이블 예약 동기화 (피크 15~20시, 10분 간격)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=120,  # 10분 간격 — 2분까지 허용
        max_instances=1,
    )
    scheduler.add_job(
        sync_unstable_reservations_job,
        trigger=CronTrigger(hour='0,12', minute=5, timezone='Asia/Seoul'),
        id='sync_unstable_reservations_offpeak',
        name='언스테이블 예약 동기화 (오프피크 00:05·12:05)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,  # 하루 2회 — 5분까지 허용
        max_instances=1,
    )

    # Daily room auto-assignment - 10am KST (당일+내일)
    scheduler.add_job(
        daily_room_assign_job,
        trigger=CronTrigger(hour=10, minute=1, timezone='Asia/Seoul'),
        id='daily_room_assign',
        name='객실 자동 배정 (오전 10:01)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,  # 하루 1회 — 5분까지 허용
        max_instances=1,
    )

    # Daily reconciliation - 09:55 KST (before room assignment at 10:00)
    scheduler.add_job(
        reconcile_today_reservations_job,
        trigger=CronTrigger(hour=9, minute=55, timezone='Asia/Seoul'),
        id='reconcile_today_reservations',
        name='네이버 예약 대사 (오전 9:55)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,  # 하루 1회 — 5분까지 허용
        max_instances=1,
    )

    # Consecutive stay detection - 4 times daily (09, 10, 11, 12 KST)
    scheduler.add_job(
        detect_consecutive_stays_job,
        trigger=CronTrigger(hour='9,10,11,12', minute=0, timezone='Asia/Seoul'),
        id='detect_consecutive_stays',
        name='연박 감지 (하루 4회)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,  # 하루 4회 — 5분까지 허용
        max_instances=1,
    )

    # Sync status log - every 6 hours (00, 06, 12, 18)
    scheduler.add_job(
        sync_status_log_job,
        trigger=CronTrigger(hour='0,6,12,18', minute=0, timezone='Asia/Seoul'),
        id='sync_status_log',
        name='동기화 상태 로그 (6시간)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,  # 6시간마다 — 5분까지 허용
        max_instances=1,
    )

    # Snapshot refresh - 4 times daily KST (08:50, 09:50, 11:50, 22:50)
    scheduler.add_job(
        refresh_snapshots_job,
        trigger=CronTrigger(hour=8, minute=50, timezone='Asia/Seoul'),
        id='refresh_snapshots_morning',
        name='참여자 스냅샷 갱신 (08:50)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
        max_instances=1,
    )
    scheduler.add_job(
        refresh_snapshots_job,
        trigger=CronTrigger(hour=9, minute=50, timezone='Asia/Seoul'),
        id='refresh_snapshots_morning_late',
        name='참여자 스냅샷 갱신 (09:50)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
        max_instances=1,
    )
    scheduler.add_job(
        refresh_snapshots_job,
        trigger=CronTrigger(hour=11, minute=50, timezone='Asia/Seoul'),
        id='refresh_snapshots_noon',
        name='참여자 스냅샷 갱신 (11:50)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
        max_instances=1,
    )
    scheduler.add_job(
        refresh_snapshots_job,
        trigger=CronTrigger(hour=22, minute=50, timezone='Asia/Seoul'),
        id='refresh_snapshots_night',
        name='참여자 스냅샷 갱신 (22:50)',
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
        max_instances=1,
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
