"""
SmsSender - Tag-based SMS filtering and sending
Ported from stable-clasp-main/01_sns.js
(Renamed from campaigns/tag_manager.py; TagCampaignManager → SmsSender)
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from sqlalchemy import exists
from app.db.models import Reservation, ReservationSmsAssignment
from app.providers.base import SMSProvider
from app.services.sms_tracking import record_sms_sent
from app.services.activity_logger import log_activity

logger = logging.getLogger(__name__)


class SmsSender:
    """
    Sender for tag-based SMS campaigns

    Ported from: stable-clasp-main/01_sns.js
    """

    def __init__(self, db: Session, sms_provider: SMSProvider):
        self.db = db
        self.sms_provider = sms_provider

    def get_targets_by_tag(
        self,
        tag: str,
        exclude_sent: bool = True,
        sms_type: str = 'room',  # 'room' or 'party' (legacy, unused)
        date: Optional[str] = None,  # YYYY-MM-DD
        template_key: Optional[str] = None,  # template key for exclude_sent filter
    ) -> List[Reservation]:
        """
        Get SMS targets filtered by tag

        Args:
            tag: Tag to filter by (supports multi-tags like "1,2,2차만")
            exclude_sent: Whether to exclude already-sent numbers
            sms_type: Type of SMS ('room' or 'party') for marking check
            date: Date filter in YYYY-MM-DD format

        Returns:
            List of Reservation objects matching criteria

        Ported from: stable-clasp-main/01_sns.js:5-33 (collectPhonesByTagAndMark)
        """
        # Multi-tag mapping (from line 8-11)
        multi_tag_map = {
            '1,2,2차만': ['1', '2', '2차만'],
            '2차만': ['2차만']
        }

        # Get target tags
        target_tags = multi_tag_map.get(tag, [tag])

        # Build query
        query = self.db.query(Reservation)

        # Filter by date
        if date:
            query = query.filter(Reservation.check_in_date == date)

        # Filter by tags (check if any target tag is in the tags field)
        # Using SQL LIKE for simplicity (tags stored as comma-separated or JSON)
        tag_conditions = []
        for target_tag in target_tags:
            tag_conditions.append(Reservation.tags.contains(target_tag))

        if tag_conditions:
            from sqlalchemy import or_
            query = query.filter(or_(*tag_conditions))

        # Filter by sent status via ReservationSmsAssignment
        if exclude_sent and template_key:
            query = query.filter(
                ~exists().where(
                    (ReservationSmsAssignment.reservation_id == Reservation.id) &
                    (ReservationSmsAssignment.template_key == template_key) &
                    (ReservationSmsAssignment.sent_at.isnot(None))
                )
            )

        # Filter valid phone numbers (from line 25)
        query = query.filter(Reservation.phone.isnot(None))
        query = query.filter(Reservation.phone != '')

        results = query.all()
        logger.info(f"Found {len(results)} targets for tag '{tag}' date='{date}'")

        return results

    async def send_campaign(
        self,
        tag: str,
        template_key: str,
        variables: Optional[Dict[str, Any]] = None,
        sms_type: str = 'room',
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute tag-based SMS campaign

        Args:
            tag: Tag to target
            template_key: Message template key
            variables: Template variables (optional)
            sms_type: Type of SMS campaign

        Returns:
            dict with sent_count, failed_count, target_count

        Ported from: stable-clasp-main/01_sns.js:62-124 (sendSmsAndMark)
        """
        sent_count = 0
        failed_count = 0
        target_count = 0

        try:
            # Get targets
            targets = self.get_targets_by_tag(tag, exclude_sent=True, sms_type=sms_type, date=date, template_key=template_key)
            target_count = len(targets)

            if not targets:
                logger.warning(f"No targets found for tag '{tag}'")
                log_activity(
                    self.db,
                    type="sms_template",
                    title=f"태그 SMS 발송 ({tag})",
                    target_count=0,
                    success_count=0,
                    failed_count=0,
                )
                self.db.commit()
                return {"sent_count": 0, "failed_count": 0, "target_count": 0}

            # Prepare messages
            messages = []

            for reservation in targets:
                from app.templates.renderer import TemplateRenderer
                from app.templates.variables import calculate_template_variables

                renderer = TemplateRenderer(self.db)

                message_vars = calculate_template_variables(
                    reservation=reservation,
                    db=self.db,
                    date=date,
                    custom_vars=variables
                )

                message = renderer.render(template_key, message_vars)

                messages.append({
                    'to': reservation.phone,
                    'message': message
                })

            # Send bulk SMS (from line 86-124)
            logger.info(f"Sending {len(messages)} SMS messages for campaign '{tag}'")

            result = await self.sms_provider.send_bulk(messages)

            if result.get('success'):
                sent_count = len(messages)

                # Record sent via ReservationSmsAssignment
                for reservation in targets:
                    record_sms_sent(self.db, reservation.id, template_key, tag)

                logger.info(f"Campaign successful: {sent_count} messages sent")

            else:
                failed_count = len(messages)
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Campaign failed: {error_msg}")

            log_activity(
                self.db,
                type="sms_template",
                title=f"태그 SMS 발송 ({tag})",
                target_count=target_count,
                success_count=sent_count,
                failed_count=failed_count,
            )
            self.db.commit()

            return {"sent_count": sent_count, "failed_count": failed_count, "target_count": target_count}

        except Exception as e:
            logger.error(f"Error executing campaign: {e}")
            log_activity(
                self.db,
                type="sms_template",
                title=f"태그 SMS 발송 ({tag}) - 오류",
                target_count=target_count,
                success_count=sent_count,
                failed_count=failed_count,
                status="failed",
            )
            self.db.commit()
            raise

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
        from app.templates.renderer import TemplateRenderer

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
            ReservationSmsAssignment.sent_at.is_(None),
            Reservation.check_in_date == date,
            Reservation.status == 'confirmed',
        ).all()

        if not assignments:
            return {"sent_count": 0, "failed_count": 0, "target_count": 0}

        renderer = TemplateRenderer(self.db)
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

        from app.db.models import RoomAssignment
        from app.templates.variables import calculate_template_variables

        for assignment in assignments:
            reservation = reservations_by_id.get(assignment.reservation_id)
            if not reservation:
                failed_count += 1
                continue
            try:
                # Lookup room assignment for accurate room info
                ra = self.db.query(RoomAssignment).filter(
                    RoomAssignment.reservation_id == reservation.id,
                    RoomAssignment.date == date,
                ).first()
                context = calculate_template_variables(
                    reservation=reservation, db=self.db, date=date, room_assignment=ra,
                )
                message_content = renderer.render(template_key, context)
                result = await sms_provider.send_sms(
                    to=reservation.phone,
                    message=message_content,
                )
                if result.get("success"):
                    sent_count += 1
                    assignment.sent_at = datetime.now()
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
