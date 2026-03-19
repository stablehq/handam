"""
SmsSender - Tag-based SMS filtering and sending
Ported from stable-clasp-main/01_sns.js
(Renamed from campaigns/tag_manager.py; TagCampaignManager → SmsSender)
"""
from typing import Dict, Any, Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import logging

from app.db.models import Reservation, ReservationStatus
from app.providers.base import SMSProvider
from app.services.activity_logger import log_activity

logger = logging.getLogger(__name__)


async def send_single_sms(
    db: Session,
    sms_provider,
    reservation: "Reservation",
    template_key: str,
    date: Optional[str] = None,
    created_by: str = "system",
    skip_activity_log: bool = False,
    skip_commit: bool = False,
    custom_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    단건 SMS 발송 공통 함수.
    RoomAssignment 조회 + calculate_template_variables + 렌더링 + 발송.
    발송 결과(성공/실패)를 activity log에 기록합니다.

    Returns: {"success": bool, "message_id": str | None, "error": str | None}
    """
    from app.db.models import RoomAssignment
    from app.templates.renderer import TemplateRenderer
    from app.templates.variables import calculate_template_variables

    if not reservation.phone:
        return {"success": False, "message_id": None, "error": "전화번호가 없습니다"}

    effective_date = date or (
        reservation.check_in_date.strftime("%Y-%m-%d")
        if hasattr(reservation.check_in_date, "strftime")
        else str(reservation.check_in_date)
        if reservation.check_in_date
        else None
    )

    ra = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation.id,
        RoomAssignment.date == effective_date,
    ).first()

    context = calculate_template_variables(
        reservation=reservation,
        db=db,
        date=effective_date,
        custom_vars=custom_vars,
        room_assignment=ra,
    )

    renderer = TemplateRenderer(db)
    message_content = renderer.render(template_key, context)

    result = await sms_provider.send_sms(to=reservation.phone, message=message_content)

    success = bool(result.get("success"))
    if not skip_activity_log:
        log_activity(
            db,
            type="sms_send",
            title=f"SMS → {reservation.customer_name} ({reservation.phone})",
            detail={
                "reservation_id": reservation.id,
                "customer_name": reservation.customer_name,
                "phone": reservation.phone,
                "template_key": template_key,
                "message": message_content,
                "room_number": ra.room_number if ra else None,
                "provider": result.get("provider", "unknown"),
                "message_id": result.get("message_id"),
                "error": result.get("error"),
            },
            status="success" if success else "failed",
            target_count=1,
            success_count=1 if success else 0,
            failed_count=0 if success else 1,
            created_by=created_by,
        )
    if not skip_commit:
        db.commit()

    if success:
        return {"success": True, "message_id": result.get("message_id"), "error": None}
    else:
        return {"success": False, "message_id": None, "error": result.get("error", "SMS 발송 실패")}


class SmsSender:
    """
    Sender for tag-based SMS campaigns

    Ported from: stable-clasp-main/01_sns.js
    """

    def __init__(self, db: Session, sms_provider: SMSProvider):
        self.db = db
        self.sms_provider = sms_provider

    async def send_by_assignment(
        self,
        template_key: str,
        date: str,
        sms_provider,
    ) -> Dict[str, Any]:
        """
        Send SMS to all reservations with unsent assignment for a given template_key and date.

        Args:
            template_key: SMS template key
            date: Date string in YYYY-MM-DD format
            sms_provider: SMS provider instance

        Returns:
            dict with sent_count, failed_count, target_count
        """
        from app.db.models import MessageTemplate, ReservationSmsAssignment

        template = self.db.query(MessageTemplate).filter(
            MessageTemplate.template_key == template_key,
            MessageTemplate.is_active == True,
        ).first()
        if not template:
            raise ValueError(f"Template not found: {template_key}")

        assignments = self.db.query(ReservationSmsAssignment).join(
            Reservation, ReservationSmsAssignment.reservation_id == Reservation.id
        ).filter(
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
            ReservationSmsAssignment.sent_at.is_(None),
            Reservation.check_in_date <= date,
            or_(Reservation.check_out_date > date, Reservation.check_out_date.is_(None)),
            Reservation.status == ReservationStatus.CONFIRMED,
        ).all()

        if not assignments:
            return {"sent_count": 0, "failed_count": 0, "target_count": 0}

        sent_count = 0
        failed_count = 0

        activity_log = log_activity(
            self.db,
            type="sms_template",
            title=f"SMS 발송 ({template_key})",
            target_count=len(assignments),
            success_count=0,
            failed_count=0,
        )
        self.db.commit()

        # Batch-fetch all reservations to avoid N+1 queries
        reservation_ids = [a.reservation_id for a in assignments]
        reservations_by_id = {
            r.id: r
            for r in self.db.query(Reservation).filter(Reservation.id.in_(reservation_ids)).all()
        }

        for assignment in assignments:
            reservation = reservations_by_id.get(assignment.reservation_id)
            if not reservation:
                failed_count += 1
                continue
            try:
                result = await send_single_sms(
                    db=self.db,
                    sms_provider=sms_provider,
                    reservation=reservation,
                    template_key=template_key,
                    date=date,
                    created_by="schedule",
                )
                if result.get("success"):
                    sent_count += 1
                    assignment.sent_at = datetime.now(timezone.utc)
                    self.db.commit()
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to send SMS to reservation #{reservation.id}: {e}")

        activity_log.success_count = sent_count
        activity_log.failed_count = failed_count
        self.db.commit()

        return {
            "sent_count": sent_count,
            "failed_count": failed_count,
            "target_count": len(assignments),
        }
