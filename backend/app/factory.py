"""
Provider factory for hot-swapping Mock and Real implementations.
This is the CRITICAL file for demo/production mode switching.
"""
from app.config import settings
from app.providers.base import SMSProvider, ReservationProvider, LLMProvider
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


def get_sms_provider_for_tenant(tenant=None) -> SMSProvider:
    """Tenant-aware SMS provider. Uses tenant's sender number if available."""
    if settings.DEMO_MODE:
        from app.mock.sms import MockSMSProvider
        return MockSMSProvider()
    from app.real.sms import RealSMSProvider
    sender = tenant.aligo_sender if tenant and tenant.aligo_sender else ''
    return RealSMSProvider(
        api_key=settings.ALIGO_API_KEY,
        user_id=settings.ALIGO_USER_ID,
        sender=sender,
        testmode=settings.ALIGO_TESTMODE,
    )


def get_reservation_provider_for_tenant(tenant=None) -> ReservationProvider:
    """Tenant-aware reservation provider. Uses tenant's Naver credentials."""
    if settings.DEMO_MODE:
        from app.mock.reservation import MockReservationProvider
        return MockReservationProvider()
    from app.real.reservation import RealReservationProvider
    business_id = tenant.naver_business_id if tenant else ''
    cookie = tenant.naver_cookie if tenant and tenant.naver_cookie else ''
    return RealReservationProvider(
        business_id=business_id,
        cookie=cookie,
    )


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Get LLM provider - always uses Real (Claude API)"""
    logger.info("🚀 Using RealLLMProvider")
    from app.real.llm import RealLLMProvider
    return RealLLMProvider(api_key=settings.CLAUDE_API_KEY)
