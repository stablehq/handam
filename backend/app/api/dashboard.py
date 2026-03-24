"""
Dashboard statistics API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.api.deps import get_tenant_scoped_db
from app.db.models import Reservation, ActivityLog, ReservationStatus, User
from app.auth.dependencies import get_current_user
from datetime import datetime
from app.config import KST

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get dashboard statistics"""

    # Today's new reservations (created today)
    # tenant_id 필터는 before_compile hook이 select_from(Reservation)에서 자동 적용
    today_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    today_reservations = db.query(func.count()).select_from(Reservation).filter(
        Reservation.created_at >= today_start,
    ).scalar() or 0

    # Recent reservations (last 5)
    recent_reservations = (
        db.query(Reservation).order_by(Reservation.created_at.desc()).limit(5).all()
    )

    # Campaign stats — today's sends (from ActivityLog)
    # tenant_id 필터는 before_compile hook이 select_from(ActivityLog)에서 자동 적용
    today_campaign_sent = int(db.query(func.coalesce(func.sum(ActivityLog.success_count), 0)).select_from(ActivityLog).filter(
        ActivityLog.activity_type == "sms_send",
        ActivityLog.created_at >= today_start,
    ).scalar() or 0)

    # Gender stats (7 days: today + 6 days forward) — 일별 SUM
    from datetime import timedelta
    today = datetime.now(KST).date()
    gender_daily = []
    for i in range(7):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        # tenant_id 필터는 before_compile hook이 select_from(Reservation)에서 자동 적용
        row = db.query(
            func.coalesce(func.sum(Reservation.male_count), 0).label("male"),
            func.coalesce(func.sum(Reservation.female_count), 0).label("female"),
        ).select_from(Reservation).filter(
            Reservation.check_in_date == d_str,
            Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]),
        ).first()
        gender_daily.append({
            "date": d_str,
            "male": int(row.male),
            "female": int(row.female),
        })

    # Naver sync status — from APScheduler job info (no DB query)
    from app.scheduler.jobs import scheduler as apscheduler
    from datetime import timedelta
    sync_job = apscheduler.get_job('sync_naver_reservations')
    if sync_job and sync_job.next_run_time:
        next_run = sync_job.next_run_time
        last_run = next_run - timedelta(minutes=5)
        naver_sync = {
            "last_sync_at": last_run.isoformat(),
            "next_sync_at": next_run.isoformat(),
            "status": "success",
        }
    else:
        naver_sync = {
            "last_sync_at": None,
            "next_sync_at": None,
            "status": None,
        }

    return {
        "totals": {
            "today_reservations": today_reservations,
        },
        "campaigns": {
            "today_sent": today_campaign_sent,
        },
        "gender_stats": {
            "daily": gender_daily,
        },
        "naver_sync": naver_sync,
        "recent_reservations": [
            {
                "id": res.id,
                "customer_name": res.customer_name,
                "phone": res.phone,
                "check_in_date": res.check_in_date,
                "check_in_time": res.check_in_time,
                "status": res.status.value,
            }
            for res in recent_reservations
        ],
    }


@router.get("/today-schedules")
async def get_today_schedules(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get today's schedule timeline for dashboard display"""
    from app.db.models import TemplateSchedule

    now = datetime.now(KST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current_hour = now.hour
    current_minute = now.minute

    schedules = db.query(TemplateSchedule).filter(
        TemplateSchedule.is_active == True,
    ).all()

    timeline = []

    for s in schedules:
        template_name = s.template.name if s.template else s.schedule_name

        if s.schedule_type == 'daily':
            h = s.hour or 0
            m = s.minute or 0
            done = (current_hour > h) or (current_hour == h and current_minute >= m)
            sent_log = db.query(ActivityLog).filter(
                ActivityLog.activity_type == "sms_send",
                ActivityLog.created_at >= today_start,
                or_(
                    ActivityLog.detail.contains(f'"schedule_id": {s.id}'),
                    ActivityLog.detail.contains(f'"schedule_id":{s.id}'),
                    ActivityLog.title.contains(s.schedule_name),
                ),
            ).first()
            status = "완료" if sent_log else ("대기" if not done else "미발송")
            result = f"성공 {sent_log.success_count}건" if sent_log else "-"
            timeline.append({
                "schedule_name": s.schedule_name,
                "template_name": template_name,
                "time": f"{h:02d}:{m:02d}",
                "status": status,
                "result": result,
                "sort_key": h * 60 + m,
            })

        elif s.schedule_type == 'interval':
            start_h = s.active_start_hour if s.active_start_hour is not None else 0
            end_h = s.active_end_hour if s.active_end_hour is not None else 24
            interval = s.interval_minutes or 60
            done = current_hour >= end_h
            in_progress = start_h <= current_hour < end_h
            sent_count = db.query(ActivityLog).filter(
                ActivityLog.activity_type == "sms_send",
                ActivityLog.created_at >= today_start,
                or_(
                    ActivityLog.detail.contains(f'"schedule_id": {s.id}'),
                    ActivityLog.detail.contains(f'"schedule_id":{s.id}'),
                    ActivityLog.title.contains(s.schedule_name),
                ),
            ).count()
            status = "완료" if done else ("진행중" if in_progress else "대기")
            result = f"{sent_count}건" if sent_count > 0 else "-"
            timeline.append({
                "schedule_name": s.schedule_name,
                "template_name": template_name,
                "time": f"{start_h:02d}:00~{end_h:02d}:00 ({interval}분 간격)",
                "status": status,
                "result": result,
                "sort_key": start_h * 60,
            })

        elif s.schedule_type == 'hourly':
            start_h = s.active_start_hour if s.active_start_hour is not None else 0
            end_h = s.active_end_hour if s.active_end_hour is not None else 24
            m = s.minute or 0
            done = current_hour >= end_h
            in_progress = start_h <= current_hour < end_h
            sent_count = db.query(ActivityLog).filter(
                ActivityLog.activity_type == "sms_send",
                ActivityLog.created_at >= today_start,
                or_(
                    ActivityLog.detail.contains(f'"schedule_id": {s.id}'),
                    ActivityLog.detail.contains(f'"schedule_id":{s.id}'),
                    ActivityLog.title.contains(s.schedule_name),
                ),
            ).count()
            status = "완료" if done else ("진행중" if in_progress else "대기")
            result = f"{sent_count}건" if sent_count > 0 else "-"
            timeline.append({
                "schedule_name": s.schedule_name,
                "template_name": template_name,
                "time": f"{start_h:02d}:00~{end_h:02d}:00 (매시 {m}분)",
                "status": status,
                "result": result,
                "sort_key": start_h * 60,
            })

    timeline.sort(key=lambda x: x["sort_key"])
    for item in timeline:
        del item["sort_key"]

    return timeline
