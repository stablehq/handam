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

    # Campaign stats (from ActivityLog)
    campaign_q = db.query(ActivityLog).filter(ActivityLog.activity_type == "sms_template")
    if tid is not None:
        campaign_q = campaign_q.filter(ActivityLog.tenant_id == tid)
    total_campaigns = campaign_q.count()
    campaign_sent_q = db.query(func.sum(ActivityLog.success_count)).select_from(ActivityLog).filter(ActivityLog.activity_type == "sms_template")
    if tid is not None:
        campaign_sent_q = campaign_sent_q.filter(ActivityLog.tenant_id == tid)
    total_campaign_sent = campaign_sent_q.scalar() or 0

    # Gender stats (today) — 실시간 SUM 계산
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    gender_q = db.query(
        func.coalesce(func.sum(Reservation.male_count), 0).label("total_male"),
        func.coalesce(func.sum(Reservation.female_count), 0).label("total_female"),
    ).select_from(Reservation).filter(
        Reservation.check_in_date == today_str,
        Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]),
    )
    if tid is not None:
        gender_q = gender_q.filter(Reservation.tenant_id == tid)
    gender_result = gender_q.first()
    total_male = int(gender_result.total_male)
    total_female = int(gender_result.total_female)

    return {
        "totals": {
            "reservations": total_reservations,
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
            "total_campaigns": total_campaigns,
            "total_sent": int(total_campaign_sent),
        },
        "gender_stats": {
            "male_count": total_male,
            "female_count": total_female,
            "participant_count": total_male + total_female,
        },
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
