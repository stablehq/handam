"""
Dashboard statistics API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
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

    # Gender stats (7 days: today + 6 days forward) — 연박자 중간일도 포함
    from datetime import timedelta
    from sqlalchemy import or_
    today = datetime.now(KST).date()
    date_strs = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    gender_daily = []
    for d in date_strs:
        row = db.query(
            func.coalesce(func.sum(Reservation.male_count), 0).label("male"),
            func.coalesce(func.sum(Reservation.female_count), 0).label("female"),
        ).select_from(Reservation).filter(
            Reservation.check_in_date <= d,
            or_(Reservation.check_out_date > d, Reservation.check_out_date.is_(None)),
            Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]),
        ).first()
        gender_daily.append({
            "date": d,
            "male": int(row.male) if row else 0,
            "female": int(row.female) if row else 0,
        })

    # Naver sync status — from last ActivityLog + APScheduler next run
    from app.scheduler.jobs import scheduler as apscheduler
    last_sync_log = (
        db.query(ActivityLog)
        .filter(ActivityLog.activity_type == "naver_sync")
        .order_by(ActivityLog.created_at.desc())
        .first()
    )
    sync_job = apscheduler.get_job('sync_naver_reservations')
    next_sync_at = sync_job.next_run_time.isoformat() if sync_job and sync_job.next_run_time else None

    if last_sync_log:
        error_detail = None
        if last_sync_log.status == "failed" and last_sync_log.detail:
            detail = last_sync_log.detail if isinstance(last_sync_log.detail, dict) else {}
            error_msg = detail.get("error", "")
            if "cookie" in error_msg.lower() or "401" in error_msg or "403" in error_msg:
                error_detail = "네이버 쿠키가 만료되었을 수 있습니다. 설정에서 쿠키를 갱신하세요."
            else:
                error_detail = error_msg or "동기화 실패"
        naver_sync = {
            "last_sync_at": last_sync_log.created_at.isoformat() if last_sync_log.created_at else None,
            "next_sync_at": next_sync_at,
            "status": last_sync_log.status,
            "error": error_detail,
        }
    else:
        naver_sync = {
            "last_sync_at": None,
            "next_sync_at": next_sync_at,
            "status": None,
            "error": None,
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

    # 오늘 SMS 발송 로그를 한 번에 조회 (N+1 방지)
    all_logs = db.query(ActivityLog).filter(
        ActivityLog.activity_type == "sms_send",
        ActivityLog.created_at >= today_start,
    ).all()

    # schedule_id 기준 매핑 (detail JSON 내 schedule_id로 정확 매칭)
    import json
    logs_by_schedule: dict = {}
    for s in schedules:
        matched = []
        for log in all_logs:
            try:
                detail = json.loads(log.detail) if isinstance(log.detail, str) else (log.detail or {})
            except (json.JSONDecodeError, TypeError):
                detail = {}
            if detail.get("schedule_id") == s.id:
                matched.append(log)
        logs_by_schedule[s.id] = matched

    timeline = []

    for s in schedules:
        template_name = s.template.name if s.template else s.schedule_name
        s_logs = logs_by_schedule.get(s.id, [])
        first_log = s_logs[0] if s_logs else None
        log_count = len(s_logs)

        if s.schedule_type == 'daily':
            h = s.hour or 0
            m = s.minute or 0
            done = (current_hour > h) or (current_hour == h and current_minute >= m)
            if first_log:
                if first_log.status == "failed":
                    status = "실패"
                    result = f"실패 {first_log.failed_count}건"
                elif first_log.status == "partial":
                    status = "완료"
                    result = f"성공 {first_log.success_count}건 / 실패 {first_log.failed_count}건"
                else:
                    status = "완료"
                    result = f"성공 {first_log.success_count}건"
            else:
                status = "대기" if not done else "미발송"
                result = "-"
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
            status = "완료" if done else ("진행중" if in_progress else "대기")
            total_success = sum(l.success_count or 0 for l in s_logs)
            total_failed = sum(l.failed_count or 0 for l in s_logs)
            if log_count > 0:
                result = f"성공 {total_success}건" if total_failed == 0 else f"성공 {total_success}건 / 실패 {total_failed}건"
            else:
                result = "-"
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
            status = "완료" if done else ("진행중" if in_progress else "대기")
            total_success = sum(l.success_count or 0 for l in s_logs)
            total_failed = sum(l.failed_count or 0 for l in s_logs)
            if log_count > 0:
                result = f"성공 {total_success}건" if total_failed == 0 else f"성공 {total_success}건 / 실패 {total_failed}건"
            else:
                result = "-"
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
