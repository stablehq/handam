"""
Dashboard statistics API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.api.deps import get_tenant_scoped_db
from app.db.models import Message, Reservation, ActivityLog, MessageDirection, ReservationStatus, User
from app.db.tenant_context import current_tenant_id
from app.auth.dependencies import get_current_user
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Get dashboard statistics"""

    tid = current_tenant_id.get()

    # Message stats (single query with CASE WHEN)
    msg_q = db.query(
        func.count().label("total"),
        func.count(case((Message.direction == MessageDirection.INBOUND, 1))).label("inbound"),
        func.count(case((Message.direction == MessageDirection.OUTBOUND, 1))).label("outbound"),
        func.count(case((Message.response_source == "rule", 1))).label("rule"),
        func.count(case((Message.response_source == "llm", 1))).label("llm"),
        func.count(case((Message.response_source == "manual", 1))).label("manual"),
        func.count(case((Message.needs_review == True, 1))).label("needs_review"),
    ).select_from(Message)
    if tid is not None:
        msg_q = msg_q.filter(Message.tenant_id == tid)
    msg_stats = msg_q.one()

    total_messages = msg_stats.total
    inbound_messages = msg_stats.inbound
    outbound_messages = msg_stats.outbound
    rule_responses = msg_stats.rule
    llm_responses = msg_stats.llm
    manual_responses = msg_stats.manual
    needs_review = msg_stats.needs_review

    # Auto-response rate
    auto_responses = rule_responses + llm_responses
    auto_response_rate = (
        (auto_responses / inbound_messages * 100) if inbound_messages > 0 else 0
    )

    # Reservation stats (single query with CASE WHEN)
    res_q = db.query(
        func.count().label("total"),
        func.count(case((Reservation.status == ReservationStatus.PENDING, 1))).label("pending"),
        func.count(case((Reservation.status == ReservationStatus.CONFIRMED, 1))).label("confirmed"),
        func.count(case((Reservation.status == ReservationStatus.CANCELLED, 1))).label("cancelled"),
        func.count(case((Reservation.status == ReservationStatus.COMPLETED, 1))).label("completed"),
    ).select_from(Reservation)
    if tid is not None:
        res_q = res_q.filter(Reservation.tenant_id == tid)
    res_stats = res_q.one()

    total_reservations = res_stats.total

    # Today's new reservations (created today)
    today_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    today_res_q = db.query(func.count()).select_from(Reservation).filter(
        Reservation.created_at >= today_start,
    )
    if tid is not None:
        today_res_q = today_res_q.filter(Reservation.tenant_id == tid)
    today_reservations = today_res_q.scalar() or 0

    reservations_by_status = {
        ReservationStatus.PENDING.value: res_stats.pending,
        ReservationStatus.CONFIRMED.value: res_stats.confirmed,
        ReservationStatus.CANCELLED.value: res_stats.cancelled,
        ReservationStatus.COMPLETED.value: res_stats.completed,
    }

    # Recent reservations (last 5)
    recent_reservations = (
        db.query(Reservation).order_by(Reservation.created_at.desc()).limit(5).all()
    )

    # Recent messages (last 5)
    recent_messages = db.query(Message).order_by(Message.created_at.desc()).limit(5).all()

    # Campaign stats — today's sends (from ActivityLog)
    today_campaign_q = db.query(func.count()).select_from(ActivityLog).filter(
        ActivityLog.activity_type == "sms_template",
        ActivityLog.created_at >= today_start,
    )
    if tid is not None:
        today_campaign_q = today_campaign_q.filter(ActivityLog.tenant_id == tid)
    today_campaigns = today_campaign_q.scalar() or 0
    today_sent_q = db.query(func.coalesce(func.sum(ActivityLog.success_count), 0)).select_from(ActivityLog).filter(
        ActivityLog.activity_type == "sms_template",
        ActivityLog.created_at >= today_start,
    )
    if tid is not None:
        today_sent_q = today_sent_q.filter(ActivityLog.tenant_id == tid)
    today_campaign_sent = int(today_sent_q.scalar() or 0)

    # Gender stats (7 days: today + 6 days forward) — 일별 SUM
    from datetime import timedelta
    today = datetime.now(KST).date()
    gender_daily = []
    for i in range(7):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        gq = db.query(
            func.coalesce(func.sum(Reservation.male_count), 0).label("male"),
            func.coalesce(func.sum(Reservation.female_count), 0).label("female"),
        ).select_from(Reservation).filter(
            Reservation.check_in_date == d_str,
            Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]),
        )
        if tid is not None:
            gq = gq.filter(Reservation.tenant_id == tid)
        row = gq.first()
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
            "reservations": total_reservations,
            "today_reservations": today_reservations,
            "messages": total_messages,
            "inbound_messages": inbound_messages,
            "outbound_messages": outbound_messages,
        },
        "reservations_by_status": reservations_by_status,
        "auto_response": {
            "rule_responses": rule_responses,
            "llm_responses": llm_responses,
            "manual_responses": manual_responses,
            "auto_response_rate": round(auto_response_rate, 1),
            "needs_review": needs_review,
        },
        "campaigns": {
            "today_campaigns": today_campaigns,
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
        "recent_messages": [
            {
                "id": msg.id,
                "direction": msg.direction.value,
                "from_": msg.from_,
                "content": msg.content[:50] + "..." if len(msg.content) > 50 else msg.content,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in recent_messages
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
                ActivityLog.activity_type == "sms_template",
                ActivityLog.created_at >= today_start,
                ActivityLog.title.contains(s.schedule_name),
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
                ActivityLog.activity_type == "sms_template",
                ActivityLog.created_at >= today_start,
                ActivityLog.title.contains(s.schedule_name),
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
                ActivityLog.activity_type == "sms_template",
                ActivityLog.created_at >= today_start,
                ActivityLog.title.contains(s.schedule_name),
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
