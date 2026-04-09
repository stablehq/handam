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
    import re as _re
    cleaned = _re.sub(r'\s+', ' ', req.cookie).strip()
    if not cleaned:
        return {"success": False, "message": "Cookie cannot be empty"}

    cookie = cleaned
    business_id = tenant.naver_business_id or ''

    # Save to Tenant table (persistent across restarts)
    tenant.naver_cookie = cookie
    # tenant는 get_current_tenant(get_db 세션)에서 왔으므로 tenant 세션을 커밋
    from sqlalchemy import inspect as sa_inspect
    tenant_session = sa_inspect(tenant).session
    if tenant_session:
        tenant_session.commit()
    else:
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
    from sqlalchemy import inspect as sa_inspect
    tenant_session = sa_inspect(tenant).session
    if tenant_session:
        tenant_session.commit()
    else:
        db.commit()
    return {"success": True, "message": "Cookie cleared."}


# ── Unstable Naver Settings ──────────────────────────────────────


class UnstableSettingsRequest(BaseModel):
    business_id: str | None = None
    cookie: str | None = None


@router.get("/unstable/status", response_model=NaverCookieStatus)
async def get_unstable_status(
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get unstable Naver cookie status and validate it"""
    cookie = tenant.unstable_cookie or ""
    business_id = tenant.unstable_business_id or ""
    source = "tenant_db" if tenant.unstable_cookie else "none"

    status = NaverCookieStatus(
        has_cookie=bool(cookie),
        cookie_length=len(cookie),
        cookie_preview=cookie[:10] + "***" + cookie[-5:] if len(cookie) > 20 else "***",
        is_valid=None,
        source=source,
        business_id=business_id,
    )

    if cookie and business_id:
        try:
            provider = RealReservationProvider(
                business_id=business_id,
                cookie=cookie,
            )
            reservations = await provider.sync_reservations()
            status.is_valid = True
            logger.info(f"Unstable cookie validation: OK ({len(reservations)} reservations)")
        except Exception as e:
            status.is_valid = False
            logger.warning(f"Unstable cookie validation failed: {e}")

    return status


@router.post("/unstable/settings")
async def update_unstable_settings(
    req: UnstableSettingsRequest,
    current_user: User = Depends(require_admin_or_above),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Update unstable Naver business_id and/or cookie"""
    updated = []

    if req.business_id is not None:
        tenant.unstable_business_id = req.business_id.strip() or None
        updated.append("business_id")

    if req.cookie is not None:
        # 개행/탭/연속 공백 제거 (브라우저 복사 시 혼입되는 공백 정리)
        import re as _re
        cleaned = _re.sub(r'\s+', ' ', req.cookie).strip()
        tenant.unstable_cookie = cleaned or None
        updated.append("cookie")

    if not updated:
        return {"success": False, "message": "변경할 항목이 없습니다."}

    # tenant는 get_current_tenant(get_db 세션)에서 왔으므로
    # tenant가 속한 세션을 직접 커밋해야 변경이 반영됨
    from sqlalchemy import inspect as sa_inspect
    tenant_session = sa_inspect(tenant).session
    if tenant_session:
        tenant_session.commit()
    else:
        db.commit()

    # Validate if both business_id and cookie are present
    business_id = tenant.unstable_business_id or ""
    cookie = tenant.unstable_cookie or ""

    if cookie and business_id:
        try:
            provider = RealReservationProvider(
                business_id=business_id,
                cookie=cookie,
            )
            reservations = await provider.sync_reservations()
            logger.info(f"Unstable settings updated and validated: {len(reservations)} reservations")
            return {
                "success": True,
                "message": f"설정 저장 완료. {len(reservations)}건의 예약을 확인했습니다.",
                "reservation_count": len(reservations),
            }
        except Exception as e:
            logger.warning(f"Unstable settings saved but validation failed: {e}")
            return {
                "success": True,
                "message": "설정이 저장되었지만 연결 테스트에 실패했습니다.",
                "warning": str(e),
            }

    return {"success": True, "message": f"설정 저장 완료 ({', '.join(updated)})"}


@router.post("/unstable/sync")
async def sync_unstable_reservations(
    current_user: User = Depends(require_admin_or_above),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Manually trigger unstable Naver reservation sync"""
    if not tenant.unstable_business_id or not tenant.unstable_cookie:
        return {"success": False, "message": "언스테이블 Business ID와 쿠키를 먼저 설정해주세요."}

    from app.real.reservation import RealReservationProvider
    from app.services.naver_sync import sync_naver_to_db

    try:
        provider = RealReservationProvider(
            business_id=tenant.unstable_business_id,
            cookie=tenant.unstable_cookie,
        )
        result = await sync_naver_to_db(provider, db, source="unstable")
        return {
            "success": True,
            "message": result["message"],
            "added": result["added"],
            "updated": result["updated"],
        }
    except Exception as e:
        logger.error(f"Unstable manual sync failed: {e}")
        return {"success": False, "message": f"동기화 실패: {str(e)}"}


# ── Custom Highlight Colors ──────────────────────────────────────

class CustomHighlightColorsRequest(BaseModel):
    colors: list[str]  # list of hex color strings e.g. ["#FF5733"]


@router.get("/highlight-colors")
async def get_highlight_colors(
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get custom highlight colors for this tenant"""
    import json
    colors = []
    if tenant.custom_highlight_colors:
        try:
            colors = json.loads(tenant.custom_highlight_colors)
        except (json.JSONDecodeError, TypeError):
            colors = []
    return {"colors": colors}


@router.put("/highlight-colors")
async def update_highlight_colors(
    req: CustomHighlightColorsRequest,
    current_user: User = Depends(require_admin_or_above),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_tenant_scoped_db),
):
    """Update custom highlight colors for this tenant"""
    import json
    import re
    valid_colors = [c for c in req.colors if re.match(r'^#[0-9A-Fa-f]{6}$', c)]
    # tenant is from a different session (get_db), so merge into tenant-scoped session
    merged_tenant = db.merge(tenant)
    merged_tenant.custom_highlight_colors = json.dumps(valid_colors)
    db.commit()
    return {"success": True, "colors": valid_colors}



