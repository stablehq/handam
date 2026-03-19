"""
Provider factory for hot-swapping Mock and Real implementations.
This is the CRITICAL file for demo/production mode switching.
"""
from app.config import settings
from app.providers.base import SMSProvider, ReservationProvider, LLMProvider
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


def get_sms_provider() -> SMSProvider:
    """Get SMS provider - DEMO_MODE only affects SMS (uses mock to prevent real sends)
    # Deprecated: use get_sms_provider_for_tenant() instead
    """
    if settings.DEMO_MODE:
        logger.info("Using MockSMSProvider (DEMO_MODE=true — SMS only)")
        from app.mock.sms import MockSMSProvider
        return MockSMSProvider()
    else:
        logger.info("Using RealSMSProvider (DEMO_MODE=false)")
        from app.real.sms import RealSMSProvider
        return RealSMSProvider(
            api_key=settings.ALIGO_API_KEY,
            user_id=settings.ALIGO_USER_ID,
            sender=settings.ALIGO_SENDER,
            testmode=settings.ALIGO_TESTMODE,
        )


def get_reservation_provider() -> ReservationProvider:
    """Get reservation provider - always uses Real (Naver API)
    # Deprecated: use get_reservation_provider_for_tenant() instead
    """
    logger.info("Using RealReservationProvider")
    from app.real.reservation import RealReservationProvider
    from app.config import get_naver_cookie
    return RealReservationProvider(
        business_id=settings.NAVER_BUSINESS_ID,
        cookie=get_naver_cookie(),
    )


def get_sms_provider_for_tenant(tenant=None) -> SMSProvider:
    """Tenant-aware SMS provider. Uses tenant's sender number if available."""
    if settings.DEMO_MODE:
        from app.mock.sms import MockSMSProvider
        return MockSMSProvider()
    from app.real.sms import RealSMSProvider
    sender = (tenant.aligo_sender if tenant and tenant.aligo_sender else
              getattr(settings, 'ALIGO_SENDER', ''))
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
    business_id = (tenant.naver_business_id if tenant else
                   getattr(settings, 'NAVER_BUSINESS_ID', ''))
    cookie = (tenant.naver_cookie if tenant and tenant.naver_cookie else
              getattr(settings, 'NAVER_COOKIE', ''))
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
