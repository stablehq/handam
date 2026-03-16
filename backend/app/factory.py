"""
Provider factory for hot-swapping Mock and Real implementations.
This is the CRITICAL file for demo/production mode switching.
"""
from app.config import settings
from app.providers.base import SMSProvider, ReservationProvider, LLMProvider
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_sms_provider() -> SMSProvider:
    """Get SMS provider - DEMO_MODE only affects SMS (uses mock to prevent real sends)"""
    if settings.DEMO_MODE:
        logger.info("🎭 Using MockSMSProvider (DEMO_MODE=true — SMS only)")
        from app.mock.sms import MockSMSProvider
        return MockSMSProvider()
    else:
        logger.info("🚀 Using RealSMSProvider (DEMO_MODE=false)")
        from app.real.sms import RealSMSProvider
        return RealSMSProvider(
            api_key=settings.SMS_API_KEY, api_secret=settings.SMS_API_SECRET
        )


def get_reservation_provider() -> ReservationProvider:
    """Get reservation provider - always uses Real (Naver API)"""
    logger.info("🚀 Using RealReservationProvider")
    from app.real.reservation import RealReservationProvider
    from app.config import get_naver_cookie
    return RealReservationProvider(
        business_id=settings.NAVER_BUSINESS_ID,
        cookie=get_naver_cookie(),
    )


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Get LLM provider - always uses Real (Claude API)"""
    logger.info("🚀 Using RealLLMProvider")
    from app.real.llm import RealLLMProvider
    return RealLLMProvider(api_key=settings.CLAUDE_API_KEY)
