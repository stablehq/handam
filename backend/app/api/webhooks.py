"""
Webhook endpoints for SMS and external integrations
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import get_tenant_scoped_db
from app.db.models import Message, MessageDirection, MessageStatus, User
from app.auth.dependencies import get_current_user
from app.factory import get_sms_provider
from app.router.message_router import message_router
from datetime import datetime, timezone
import logging

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


class SMSReceiveRequest(BaseModel):
    from_: str
    to: str
    message: str


@router.post("/sms/receive")
async def receive_sms(request: SMSReceiveRequest, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """
    Webhook for receiving SMS (simulated in demo mode).
    Saves inbound message, runs auto-response pipeline, and auto-sends if confident.
    """
    sms_provider = get_sms_provider()

    # Simulate SMS reception
    result = await sms_provider.simulate_receive(
        from_=request.from_, to=request.to, message=request.message
    )

    # Save inbound message to DB
    msg = Message(
        message_id=result["message_id"],
        direction=MessageDirection.INBOUND,
        from_=request.from_,
        to=request.to,
        content=request.message,
        status=MessageStatus.RECEIVED,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    logger.info(f"SMS received and saved to DB: {msg.id}")

    # Auto-response pipeline
    auto_result = await message_router.generate_auto_response(request.message)

    # Store auto-response metadata on inbound message
    msg.auto_response = auto_result["response"]
    msg.auto_response_confidence = auto_result["confidence"]
    msg.needs_review = auto_result["needs_review"]
    msg.response_source = auto_result["source"]
    db.commit()

    response = {
        "success": True,
        "message_id": msg.id,
        "result": result,
        "auto_response": {
            "response": auto_result["response"],
            "confidence": auto_result["confidence"],
            "needs_review": auto_result["needs_review"],
            "source": auto_result["source"],
            "sent": False,
        },
    }

    # Auto-send if no review needed
    if not auto_result["needs_review"]:
        await sms_provider.send_sms(to=request.from_, message=auto_result["response"])

        outbound_msg = Message(
            message_id=f"auto_{msg.id}_{int(datetime.now(timezone.utc).timestamp())}",
            direction=MessageDirection.OUTBOUND,
            from_=request.to,
            to=request.from_,
            content=auto_result["response"],
            status=MessageStatus.SENT,
            response_source=auto_result["source"],
            auto_response_confidence=auto_result["confidence"],
        )
        db.add(outbound_msg)
        db.commit()
        db.refresh(outbound_msg)

        response["auto_response"]["sent"] = True
        response["outbound_message"] = {
            "id": outbound_msg.id,
            "message": outbound_msg.content,
        }
        logger.info(f"Auto-response sent: {outbound_msg.id} (source={auto_result['source']})")
    else:
        logger.info(f"Auto-response needs review (confidence={auto_result['confidence']:.2f})")

    return response


# TODO: Implement Naver Smart Place Webhook for real-time reservation updates
#
# Currently, reservations are synced every 10 minutes via scheduler.
# For real-time updates, implement Naver Booking webhook endpoint.
#
# Implementation steps:
# 1. Register webhook URL with Naver Smart Place API
#    - Endpoint: POST /webhooks/naver/booking
#    - Verify webhook signature for security
#
# 2. Handle reservation events:
#    - booking.created: New reservation
#    - booking.updated: Reservation modified
#    - booking.cancelled: Reservation cancelled
#    - booking.confirmed: Reservation confirmed
#
# 3. Process webhook payload:
#    @router.post("/naver/booking")
#    async def receive_naver_booking_webhook(
#        request: Request,
#        db: Session = Depends(get_tenant_scoped_db)
#    ):
#        # Verify webhook signature
#        signature = request.headers.get("X-Naver-Signature")
#        payload = await request.json()
#        if not verify_naver_signature(payload, signature):
#            raise HTTPException(status_code=401, detail="Invalid signature")
#
#        event_type = payload.get("event_type")
#        booking_data = payload.get("booking")
#
#        # Find or create reservation
#        reservation = db.query(Reservation).filter_by(
#            naver_booking_id=booking_data["id"]
#        ).first()
#
#        if event_type == "booking.created":
#            # Create new reservation
#            pass
#        elif event_type == "booking.updated":
#            # Update existing reservation
#            pass
#        elif event_type == "booking.cancelled":
#            # Mark as cancelled
#            pass
#
#        return {"status": "success", "event": event_type}
#
# 4. Benefits:
#    - Real-time updates (no 10-minute delay)
#    - Reduced API calls (webhook push vs polling)
#    - Better user experience
#
# 5. Keep scheduler as backup:
#    - Run less frequently (every 1 hour) as safety net
#    - Catches any missed webhook events
#
# References:
# - Naver Smart Place Booking API docs
# - Webhook security best practices
# - app/scheduler/jobs.py:sync_naver_reservations_job (current polling implementation)
