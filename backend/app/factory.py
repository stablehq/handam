"""
Provider factory for creating tenant-aware provider instances.

SMS and Reservation providers are always Real (no mock).
"""
from app.config import settings
from app.providers.base import SMSProvider, ReservationProvider
import logging

logger = logging.getLogger(__name__)


def get_sms_provider_for_tenant(tenant=None) -> SMSProvider:
    """Tenant-aware SMS provider. Always Real; testmode controlled by tenant DB setting."""
    from app.real.sms import RealSMSProvider
    sender = tenant.aligo_sender if tenant and tenant.aligo_sender else ''
    testmode = tenant.aligo_testmode if tenant else True
    if not testmode and not settings.ALIGO_API_KEY:
        logger.warning("[SMS] testmode=False but ALIGO_API_KEY is empty — SMS will fail")
    return RealSMSProvider(
        api_key=settings.ALIGO_API_KEY,
        user_id=settings.ALIGO_USER_ID,
        sender=sender,
        testmode=testmode,
    )


def get_reservation_provider_for_tenant(tenant=None) -> ReservationProvider:
    """Tenant-aware reservation provider. Always Real; no-op if cookie is empty."""
    from app.real.reservation import RealReservationProvider
    business_id = tenant.naver_business_id if tenant else ''
    cookie = tenant.naver_cookie if tenant and tenant.naver_cookie else ''
    return RealReservationProvider(
        business_id=business_id,
        cookie=cookie,
    )


