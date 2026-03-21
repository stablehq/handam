"""
Abstract provider interfaces using Protocol (PEP 544).
This allows hot-swapping between Mock and Real implementations.
"""
from typing import Protocol, Any, Dict, List, Optional
from datetime import datetime


class SMSProvider(Protocol):
    """SMS sending/receiving abstraction

    Mock과 Real의 유일한 차이는 실제 API 호출 여부.
    반환값 형태, 메서드 시그니처, 에러 처리는 완전히 동일해야 합니다.
    """

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        """Send SMS message

        Returns: {
            "success": bool,       # 발송 성공 여부
            "message_id": str,     # 메시지 고유 ID
            "to": str,             # 수신 번호
            "message": str,        # 발송 내용
            "timestamp": str,      # ISO 8601 타임스탬프
            "provider": str,       # "mock" 또는 "real"
            "error": str | None,   # 실패 시 에러 메시지
        }
        """
        ...

    async def send_bulk(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """Send bulk SMS messages

        Returns: {
            "success": bool,       # 전체 발송 성공 여부
            "total": int,          # 전체 대상 수
            "sent": int,           # 성공 건수
            "failed": int,         # 실패 건수
            "timestamp": str,      # ISO 8601 타임스탬프
            "provider": str,       # "mock" 또는 "real"
            "error": str | None,   # 실패 시 에러 메시지
        }
        """
        ...

    async def simulate_receive(self, from_: str, to: str, message: str) -> Dict[str, Any]:
        """Simulate receiving SMS (for demo/test)

        Returns: {
            "success": bool,
            "message_id": str,
            "from_": str,
            "to": str,
            "message": str,
            "timestamp": str,
            "provider": str,
        }
        """
        ...


class ReservationProvider(Protocol):
    """Reservation sync abstraction (Naver Booking)"""

    async def sync_reservations(self, date: Any = None) -> List[Dict[str, Any]]:
        """Fetch reservations from external source"""
        ...

    async def get_reservation_details(self, reservation_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed reservation info"""
        ...

    async def fetch_by_checkin_date(self, target_date: str) -> List[Dict[str, Any]]:
        """Fetch reservations by check-in date for reconciliation"""
        ...


class LLMProvider(Protocol):
    """LLM (Claude) abstraction for auto-response generation"""

    async def generate_response(
        self, message: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate response to customer message.
        Returns: {
            "response": str,
            "confidence": float (0-1),
            "needs_review": bool
        }
        """
        ...

