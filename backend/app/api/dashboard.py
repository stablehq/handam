"""
Dashboard statistics API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.database import get_db
from app.db.models import Message, Reservation, CampaignLog, GenderStat, MessageDirection, ReservationStatus, User
from app.auth.dependencies import get_current_user
from datetime import datetime

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get dashboard statistics"""

    # Total reservations
    total_reservations = db.query(Reservation).count()

    # Reservations by status
    reservations_by_status = (
        db.query(Reservation.status, func.count(Reservation.id))
        .group_by(Reservation.status)
        .all()
    )

    # Total messages
    total_messages = db.query(Message).count()
    inbound_messages = (
        db.query(Message).filter(Message.direction == MessageDirection.INBOUND).count()
    )
    outbound_messages = (
        db.query(Message).filter(Message.direction == MessageDirection.OUTBOUND).count()
    )

    # Auto-response stats
    rule_responses = db.query(Message).filter(Message.response_source == "rule").count()
    llm_responses = db.query(Message).filter(Message.response_source == "llm").count()
    manual_responses = db.query(Message).filter(Message.response_source == "manual").count()

    # Auto-response rate
    auto_responses = rule_responses + llm_responses
    auto_response_rate = (
        (auto_responses / inbound_messages * 100) if inbound_messages > 0 else 0
    )

    # Messages needing review
    needs_review = db.query(Message).filter(Message.needs_review == True).count()

    # Recent reservations (last 5)
    recent_reservations = (
        db.query(Reservation).order_by(Reservation.created_at.desc()).limit(5).all()
    )

    # Recent messages (last 5)
    recent_messages = db.query(Message).order_by(Message.created_at.desc()).limit(5).all()

    # Campaign stats
    total_campaigns = db.query(CampaignLog).count()
    total_campaign_sent = db.query(func.sum(CampaignLog.sent_count)).scalar() or 0

    # Gender stats (today)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_gender = db.query(GenderStat).filter(GenderStat.date == today_str).first()

    return {
        "totals": {
            "reservations": total_reservations,
            "messages": total_messages,
            "inbound_messages": inbound_messages,
            "outbound_messages": outbound_messages,
        },
        "reservations_by_status": {
            status.value: count for status, count in reservations_by_status
        },
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
            "male_count": today_gender.male_count if today_gender else 0,
            "female_count": today_gender.female_count if today_gender else 0,
            "total_participants": today_gender.total_participants if today_gender else 0,
        },
        "recent_reservations": [
            {
                "id": res.id,
                "customer_name": res.customer_name,
                "phone": res.phone,
                "date": res.date,
                "time": res.time,
                "status": res.status.value,
            }
            for res in recent_reservations
        ],
        "recent_messages": [
            {
                "id": msg.id,
                "direction": msg.direction.value,
                "from_": msg.from_,
                "message": msg.message[:50] + "..." if len(msg.message) > 50 else msg.message,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in recent_messages
        ],
    }
