"""
Settings API - Runtime configuration management
Handles Naver cookie updates, connection status checks, etc.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from app.config import settings
from app.real.reservation import RealReservationProvider
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Runtime cookie storage (survives without restart, but resets on server restart)
_runtime_cookie: str | None = None


def get_naver_cookie() -> str:
    """Get the current Naver cookie (runtime override or .env)"""
    return _runtime_cookie if _runtime_cookie is not None else settings.NAVER_COOKIE


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
async def get_naver_status():
    """Get current Naver cookie status and validate it"""
    cookie = get_naver_cookie()
    source = "runtime" if _runtime_cookie is not None else "env"

    status = NaverCookieStatus(
        has_cookie=bool(cookie),
        cookie_length=len(cookie),
        cookie_preview=cookie[:50] + "..." if len(cookie) > 50 else cookie,
        is_valid=None,
        source=source,
        business_id=settings.NAVER_BUSINESS_ID,
    )

    # Test the cookie by making a lightweight API call
    if cookie:
        try:
            provider = RealReservationProvider(
                business_id=settings.NAVER_BUSINESS_ID,
                cookie=cookie,
            )
            reservations = await provider.sync_reservations()
            # If we get here without error, cookie is valid
            status.is_valid = True
            logger.info(f"Naver cookie validation: OK ({len(reservations)} reservations)")
        except Exception as e:
            status.is_valid = False
            logger.warning(f"Naver cookie validation failed: {e}")

    return status


@router.post("/naver/cookie")
async def update_naver_cookie(req: NaverCookieRequest):
    """Update Naver cookie at runtime (no restart needed)"""
    global _runtime_cookie

    if not req.cookie.strip():
        return {"success": False, "message": "Cookie cannot be empty"}

    old_source = "runtime" if _runtime_cookie is not None else "env"
    _runtime_cookie = req.cookie.strip()

    # Validate the new cookie
    try:
        provider = RealReservationProvider(
            business_id=settings.NAVER_BUSINESS_ID,
            cookie=_runtime_cookie,
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
async def clear_naver_cookie():
    """Clear runtime cookie override (falls back to .env)"""
    global _runtime_cookie
    _runtime_cookie = None
    return {"success": True, "message": "Runtime cookie cleared. Using .env cookie."}


@router.get("/naver/bookmarklet")
async def get_bookmarklet():
    """Return the bookmarklet JavaScript code for one-click cookie update"""
    # The bookmarklet reads cookies from the current page and sends them to our server
    return {
        "code": "javascript:void(fetch('{SERVER_URL}/api/settings/naver/cookie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookie:document.cookie})}).then(r=>r.json()).then(d=>alert(d.message)).catch(e=>alert('Error: '+e)))",
        "instructions": [
            "1. 아래 코드를 브라우저 즐겨찾기(북마크)로 추가하세요",
            "2. {SERVER_URL} 부분을 실제 서버 주소로 바꾸세요 (예: http://localhost:8000)",
            "3. 네이버 스마트플레이스 (new.smartplace.naver.com)에 로그인한 상태에서",
            "4. 추가한 즐겨찾기를 클릭하면 자동으로 쿠키가 서버에 전송됩니다",
        ],
    }
