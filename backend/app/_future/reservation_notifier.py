"""
Reservation status change SMS notification system
"""
from sqlalchemy import event
from app.db.models import Reservation, ReservationStatus
from app.factory import get_sms_provider
import asyncio
import logging

logger = logging.getLogger(__name__)


# SMS templates for different reservation statuses
SMS_TEMPLATES = {
    ReservationStatus.PENDING: "[예약 접수] {customer_name}님, 예약이 접수되었습니다. {date} {time} - 확인 후 문자 드리겠습니다.",
    ReservationStatus.CONFIRMED: "[예약 확정] {customer_name}님, 예약이 확정되었습니다. {date} {time}에 방문 부탁드립니다.",
    ReservationStatus.CANCELLED: "[예약 취소] {customer_name}님, 예약이 취소되었습니다. 감사합니다.",
    ReservationStatus.COMPLETED: "[방문 감사] {customer_name}님, 이용해 주셔서 감사합니다.",
}


def send_sms_sync(phone: str, message: str):
    """Synchronous wrapper for async SMS sending"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    sms_provider = get_sms_provider()
    loop.run_until_complete(sms_provider.send_sms(to=phone, message=message))


@event.listens_for(Reservation, "after_insert")
def reservation_created(mapper, connection, target):
    """Send SMS notification when reservation is created"""
    template = SMS_TEMPLATES.get(target.status, "")
    if template:
        message = template.format(
            customer_name=target.customer_name, date=target.date, time=target.time
        )
        logger.info(f"🔔 Sending SMS notification for new reservation: {target.id}")
        send_sms_sync(target.phone, message)


@event.listens_for(Reservation, "after_update")
def reservation_updated(mapper, connection, target):
    """Send SMS notification when reservation status changes"""
    # Check if status was changed
    history = target.__dict__.get("_sa_instance_state").attrs.status.history
    if history.has_changes():
        template = SMS_TEMPLATES.get(target.status, "")
        if template:
            message = template.format(
                customer_name=target.customer_name, date=target.date, time=target.time
            )
            logger.info(f"🔔 Sending SMS notification for reservation update: {target.id}")
            send_sms_sync(target.phone, message)
