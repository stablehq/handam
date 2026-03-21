"""
Settings API - Runtime configuration management
Handles Naver cookie updates, connection status checks, etc.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.real.reservation import RealReservationProvider
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.api.deps import get_current_tenant, get_tenant_scoped_db
from app.db.models import User, Tenant
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class NaverCookieRequest(BaseModel):
    cookie: str


class NaverCookieStatus(BaseModel):
    has_cookie: bool
    cookie_length: int
    cookie_preview: str
    is_valid: bool | None = None
    source: str  # "runtime" or "env"
    business_id: str


@router.get("/naver/status", response_model=NaverCookieStatus)
async def get_naver_status(
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get current Naver cookie status and validate it"""
    # Use tenant's own settings only — no fallback to global config
    cookie = tenant.naver_cookie or ""
    business_id = tenant.naver_business_id or ""
    source = "tenant_db" if tenant.naver_cookie else "none"

    status = NaverCookieStatus(
        has_cookie=bool(cookie),
        cookie_length=len(cookie),
        cookie_preview=cookie[:10] + "***" + cookie[-5:] if len(cookie) > 20 else "***",
        is_valid=None,
        source=source,
        business_id=business_id,
    )

    # Test the cookie by making a lightweight API call
    if cookie:
        try:
            provider = RealReservationProvider(
                business_id=business_id,
                cookie=cookie,
            )
            reservations = await provider.sync_reservations()
            status.is_valid = True
            logger.info(f"Naver cookie validation: OK ({len(reservations)} reservations)")
        except Exception as e:
            status.is_valid = False
            logger.warning(f"Naver cookie validation failed: {e}")

    return status


@router.post("/naver/cookie")
async def update_naver_cookie(
    req: NaverCookieRequest,
    current_user: User = Depends(require_admin_or_above),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Update Naver cookie — saves to Tenant table + runtime"""
    if not req.cookie.strip():
        return {"success": False, "message": "Cookie cannot be empty"}

    cookie = req.cookie.strip()
    business_id = tenant.naver_business_id or ''

    # Save to Tenant table (persistent across restarts)
    tenant.naver_cookie = cookie
    db.commit()

    # Validate the new cookie
    try:
        provider = RealReservationProvider(
            business_id=business_id,
            cookie=cookie,
        )
        reservations = await provider.sync_reservations()
        logger.info(f"New Naver cookie set and validated: {len(reservations)} reservations found")
        return {
            "success": True,
            "message": f"Cookie updated. {len(reservations)}건의 예약을 확인했습니다.",
            "reservation_count": len(reservations),
        }
    except Exception as e:
        logger.warning(f"New cookie set but validation failed: {e}")
        return {
            "success": True,
            "message": "Cookie saved but validation failed. Check if cookie is correct.",
            "warning": str(e),
        }


@router.delete("/naver/cookie")
async def clear_naver_cookie(
    current_user: User = Depends(require_admin_or_above),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Clear Naver cookie from Tenant table + runtime"""
    tenant.naver_cookie = None
    db.commit()
    return {"success": True, "message": "Cookie cleared."}


@router.get("/naver/bookmarklet")
async def get_bookmarklet(current_user: User = Depends(require_admin_or_above)):
    """Return the bookmarklet JavaScript code for one-click cookie update (DEPRECATED)"""
    return {
        "deprecated": True,
        "message": "Bookmarklet 방식은 보안상 더 이상 지원되지 않습니다. 프론트엔드 설정 페이지에서 쿠키를 수동 입력해주세요.",
        "code": "javascript:void(fetch('{SERVER_URL}/api/settings/naver/cookie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookie:document.cookie})}).then(r=>r.json()).then(d=>alert(d.message)).catch(e=>alert('Error: '+e)))",
        "instructions": [
            "⚠️ DEPRECATED: 이 방식은 인증 토큰 없이 동작하지 않습니다.",
            "프론트엔드 설정 페이지에서 네이버 쿠키를 직접 붙여넣기 해주세요.",
        ],
    }
