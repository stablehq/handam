"""
SmsSender - Tag-based SMS filtering and sending
Ported from stable-clasp-main/01_sns.js
(Renamed from campaigns/tag_manager.py; TagCampaignManager → SmsSender)
"""
from typing import Dict, Any, Optional
from sqlalchemy import and_
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import logging

from app.db.models import Reservation, ReservationStatus
from app.diag_logger import diag
from app.providers.base import SMSProvider
from app.services.activity_logger import log_activity

logger = logging.getLogger(__name__)

# MMS(이미지 첨부) 경로로 발송할 템플릿 키 집합.
# 일반 SMS 경로(sms_provider.send_sms) 대신 sms_provider.send_party_mms 로 라우팅.
# 새 MMS 템플릿 추가 시 이 집합과 provider 메서드만 맞추면 됨.
MMS_TEMPLATES: frozenset[str] = frozenset({"party3_today_mms"})


def find_unreplaced_vars(text: str) -> list[str]:
    """텍스트에서 미치환 {{변수}} 를 찾아 변수명 리스트로 반환."""
    import re
    return re.findall(r'\{\{(\w+)\}\}', text)


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

    [호출부 동기화 주의]
    custom_vars는 MessageTemplate.get_buffer_vars()로 통일되었습니다.
    발송 결과(성공/실패)를 activity log에 기록합니다.

    Returns: {"success": bool, "message_id": str | None, "error": str | None}
    """
    from app.db.models import RoomAssignment
    from app.templates.renderer import TemplateRenderer
    from app.templates.variables import calculate_template_variables

    diag(
        "send_single_sms.enter",
        level="verbose",
        res_id=reservation.id,
        template_key=template_key,
        date=date,
    )

    if not reservation.phone:
        diag(
            "send_single_sms.exit",
            level="verbose",
            res_id=reservation.id,
            template_key=template_key,
            success=False,
            reason="no_phone",
        )
        return {"success": False, "message_id": None, "error": "전화번호가 없습니다"}

    import re
    phone_digits = re.sub(r"[\s\-+().]", "", reservation.phone)
    if not phone_digits.isdigit() or not (9 <= len(phone_digits) <= 15):
        logger.error(
            f"Blocking SMS: invalid phone format. res={reservation.id} phone={reservation.phone!r} template={template_key}"
        )
        diag(
            "sms_sender.blocked_invalid_phone",
            level="critical",
            res_id=reservation.id,
            template_key=template_key,
            phone_preview=reservation.phone[:20],
        )
        from app.services.chip_store import record_failed
        record_failed(
            db,
            reservation_id=reservation.id,
            template_key=template_key,
            error=f"전화번호 형식 오류: {reservation.phone!r}",
            date=str(date) if date else "",
        )
        return {"success": False, "message_id": None, "error": f"전화번호 형식 오류: {reservation.phone!r}"}

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
        template_key=template_key,
    )

    # ★ 3-1a: 템플릿 존재 여부 확인 — renderer.render() 가 없는 템플릿을 에러 문자열로 반환해
    #         그대로 SMS 발송되는 사고 방지.
    renderer = TemplateRenderer(db)
    _template_obj = renderer.get_template(template_key)
    if _template_obj is None:
        logger.error(
            f"Blocking SMS: template not found. res={reservation.id} template={template_key} date={date}"
        )
        diag(
            "sms_sender.blocked_template_missing",
            level="critical",
            res_id=reservation.id,
            template_key=template_key,
            date=effective_date,
        )
        from app.services.chip_store import record_failed
        record_failed(
            db,
            reservation_id=reservation.id,
            template_key=template_key,
            error=f"템플릿 없음: {template_key}",
            date=effective_date or "",
        )
        return {"success": False, "message_id": None, "error": f"템플릿 없음: {template_key}"}

    # ★ 3-1b: 방 정보 변수를 쓰는 템플릿인데 해당 context 값이 비어있으면 차단
    #         템플릿에서 실제 사용하는 변수들을 검사해 빈 값 SMS 방지
    _ROOM_VARS_REQUIRED = ("room_num", "building", "room_password", "prefix_room_password")
    _template_content = _template_obj.content
    used_room_vars = [v for v in _ROOM_VARS_REQUIRED if f"{{{{{v}}}}}" in _template_content]
    missing_room_vars = [v for v in used_room_vars if not context.get(v)]
    if missing_room_vars:
        logger.error(
            f"Blocking SMS: room vars empty {missing_room_vars}. res={reservation.id} template={template_key} date={date}"
        )
        diag(
            "sms_sender.blocked_empty_room",
            level="critical",
            res_id=reservation.id,
            template_key=template_key,
            date=effective_date,
            missing_vars=missing_room_vars,
        )
        from app.services.chip_store import record_failed
        record_failed(
            db,
            reservation_id=reservation.id,
            template_key=template_key,
            error=f"방 정보 누락: {', '.join(missing_room_vars)}",
            date=effective_date or "",
        )
        return {"success": False, "message_id": None, "error": f"방 정보 누락: {', '.join(missing_room_vars)}"}

    message_content = renderer.render(template_key, context)

    # 미치환 변수가 남아있으면 발송 차단
    unreplaced = find_unreplaced_vars(message_content)
    if unreplaced:
        error_msg = f"미치환 변수 발견: {', '.join(unreplaced)}"
        logger.error(f"[{template_key}] {error_msg} - 발송 차단됨 (수신자: {reservation.phone})")
        return {"success": False, "message_id": None, "error": error_msg, "message": message_content}

    is_mms = template_key in MMS_TEMPLATES

    diag(
        "sms_sender.provider_call",
        level="verbose",
        res_id=reservation.id,
        template_key=template_key,
        provider=type(sms_provider).__name__,
        mms=is_mms,
    )

    # LMS 제목: 템플릿에 lms_title 가 설정돼 있으면 provider 에 전달.
    # 빈/None 이면 provider 가 본문 첫 줄을 자동 추출 (Aligo 기본 동작).
    title_kwargs = {"title": _template_obj.lms_title} if _template_obj.lms_title else {}

    if is_mms:
        # MMS 템플릿은 전용 프록시 경로로 라우팅. 프로바이더가 메서드 미구현이면
        # 즉시 실패로 기록 (예: 테스트 mock). 런타임 중에는 Real 만 사용.
        send_party_mms = getattr(sms_provider, "send_party_mms", None)
        if send_party_mms is None:
            result = {
                "success": False,
                "message_id": None,
                "error": f"MMS 미지원 provider: {type(sms_provider).__name__}",
            }
        else:
            result = await send_party_mms(to=reservation.phone, message=message_content, **title_kwargs)
    else:
        result = await sms_provider.send_sms(to=reservation.phone, message=message_content, **title_kwargs)

    success = bool(result.get("success"))
    if not skip_activity_log:
        log_activity(
            db,
            type="sms_send",
            title="SMS 발송 : 칩",
            detail={
                "reservation_id": reservation.id,
                "customer_name": reservation.customer_name,
                "phone": reservation.phone,
                "template_key": template_key,
                "message": message_content,
                "room_number": ra.room.room_number if ra and ra.room else None,
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

    diag(
        "send_single_sms.exit",
        level="verbose",
        res_id=reservation.id,
        template_key=template_key,
        success=success,
    )

    if success:
        return {"success": True, "message_id": result.get("message_id"), "error": None, "message": message_content}
    else:
        return {"success": False, "message_id": None, "error": result.get("error", "SMS 발송 실패"), "message": message_content}


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

        from app.services.filters import stay_coverage_filter
        assignments = self.db.query(ReservationSmsAssignment).join(
            Reservation, and_(
                ReservationSmsAssignment.reservation_id == Reservation.id,
                ReservationSmsAssignment.tenant_id == Reservation.tenant_id,
            )
        ).filter(
            ReservationSmsAssignment.template_key == template_key,
            ReservationSmsAssignment.date == date,
            ReservationSmsAssignment.sent_at.is_(None),
            stay_coverage_filter(date),
            Reservation.status == ReservationStatus.CONFIRMED,
        ).all()

        if not assignments:
            return {"sent_count": 0, "failed_count": 0, "target_count": 0}

        sent_count = 0
        failed_count = 0

        activity_log = log_activity(
            self.db,
            type="sms_send",
            title="SMS 발송 : 템플릿 일괄 발송",
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

        try:
            for assignment in assignments:
                reservation = reservations_by_id.get(assignment.reservation_id)
                if not reservation:
                    failed_count += 1
                    continue
                try:
                    result = await send_single_sms(
                        db=self.db,
                        sms_provider=self.sms_provider,
                        reservation=reservation,
                        template_key=template_key,
                        date=date,
                        created_by="schedule",
                        skip_commit=True,
                        custom_vars=template.get_buffer_vars(),
                    )
                    if result.get("success"):
                        sent_count += 1
                        assignment.sent_at = datetime.now(timezone.utc)
                        assignment.send_status = 'sent'
                        assignment.send_error = None
                        self.db.commit()
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to send SMS to reservation #{reservation.id}: {e}")
        finally:
            activity_log.success_count = sent_count
            activity_log.failed_count = failed_count
            self.db.commit()

        return {
            "sent_count": sent_count,
            "failed_count": failed_count,
            "target_count": len(assignments),
        }
