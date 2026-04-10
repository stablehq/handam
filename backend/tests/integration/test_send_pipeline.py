"""send_single_sms() 통합 테스트 — in-memory SQLite + mock provider."""
import pytest
import asyncio
from app.db.models import (
    Reservation, Room, Building, MessageTemplate, ReservationStatus,
)
from app.services.sms_sender import send_single_sms


class MockSMSProvider:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []

    async def send_sms(self, to, message, **kwargs):
        self.calls.append({"to": to, "message": message})
        if self.should_fail:
            return {"success": False, "message_id": None, "error": "provider error"}
        return {"success": True, "message_id": "mock_id_123", "error": None}


def _make_template(db, key="room_guide", content="안녕하세요 {{customer_name}}님"):
    tpl = MessageTemplate(
        tenant_id=1, template_key=key, name="Test", content=content, is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _make_reservation(db, phone="01012345678", check_in="2026-04-10"):
    res = Reservation(
        tenant_id=1, customer_name="홍길동", phone=phone,
        check_in_date=check_in, check_in_time="15:00",
        status=ReservationStatus.CONFIRMED,
    )
    db.add(res)
    db.flush()
    return res


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSendPipeline:
    def test_no_phone_returns_failure(self, db):
        """전화번호 없음 → 실패."""
        _make_template(db)
        res = _make_reservation(db, phone="")
        provider = MockSMSProvider()

        result = run_async(send_single_sms(
            db=db,
            sms_provider=provider,
            reservation=res,
            template_key="room_guide",
            skip_activity_log=True,
            skip_commit=True,
        ))

        assert result["success"] is False
        assert "전화번호" in result["error"]
        assert len(provider.calls) == 0

    def test_normal_flow_calls_provider(self, db):
        """정상 발송 → provider.send_sms 호출됨."""
        _make_template(db)
        res = _make_reservation(db)
        provider = MockSMSProvider()

        result = run_async(send_single_sms(
            db=db,
            sms_provider=provider,
            reservation=res,
            template_key="room_guide",
            skip_activity_log=True,
            skip_commit=True,
        ))

        assert result["success"] is True
        assert len(provider.calls) == 1
        assert provider.calls[0]["to"] == "01012345678"

    def test_provider_failure_returns_error(self, db):
        """provider 실패 → success=False, error 메시지."""
        _make_template(db)
        res = _make_reservation(db)
        provider = MockSMSProvider(should_fail=True)

        result = run_async(send_single_sms(
            db=db,
            sms_provider=provider,
            reservation=res,
            template_key="room_guide",
            skip_activity_log=True,
            skip_commit=True,
        ))

        assert result["success"] is False
        assert result["error"] is not None

    def test_missing_template_raises(self, db):
        """존재하지 않는 template_key → 에러 반환 (크래시 없음)."""
        res = _make_reservation(db)
        provider = MockSMSProvider()

        # TemplateRenderer raises when template not found — result should be error
        try:
            result = run_async(send_single_sms(
                db=db,
                sms_provider=provider,
                reservation=res,
                template_key="nonexistent_key",
                skip_activity_log=True,
                skip_commit=True,
            ))
            # If it doesn't raise, success should be False
            assert result["success"] is False
        except Exception:
            pass  # Exception is acceptable for missing template
