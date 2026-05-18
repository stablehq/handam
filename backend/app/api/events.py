"""
SSE endpoint for real-time event streaming to frontend clients.
"""
import asyncio
import logging
import jwt
from fastapi import APIRouter, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.services.event_bus import subscribe, unsubscribe
from app.auth.utils import decode_access_token
from app.db.database import session_unscoped
from app.db.models import User, UserRole, UserTenantRole
from app.diag_logger import diag

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["events"])


def _validate_token_and_tenant(token: str, tenant_id: int) -> None:
    """Validate JWT token and verify user has access to the given tenant.

    Raises HTTPException on failure.
    SSE/EventSource does not support custom headers, so the token is passed
    as a query parameter.
    """
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었습니다",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 정보가 유효하지 않습니다",
        )

    username: str = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 정보가 유효하지 않습니다",
        )

    # 옵션 C: User / UserTenantRole 은 비-TenantMixin 이라 session_unscoped 사용.
    # 자동 필터 적용 안 됨 — token 검증은 cross-tenant 조회 필요.
    db: Session = session_unscoped()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="인증 정보가 유효하지 않습니다",
            )

        if user.role != UserRole.SUPERADMIN:
            mapping = db.query(UserTenantRole).filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant_id,
            ).first()
            if not mapping:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="해당 펜션에 대한 접근 권한이 없습니다",
                )
    finally:
        db.close()


@router.get("/stream")
async def event_stream(
    token: str = Query(..., description="JWT access token"),
    tenant_id: int = Query(..., description="Tenant ID to subscribe to"),
):
    """
    Server-Sent Events stream. Clients subscribe here to receive real-time
    notifications (e.g. schedule_complete) without polling.

    Authentication is done via query parameters because the EventSource API
    does not support custom request headers.
    """
    _validate_token_and_tenant(token, tenant_id)

    q = subscribe(tenant_id)
    diag("sse.subscribed", level="verbose", tenant_id=tenant_id)

    async def generator():
        try:
            # Send an initial keep-alive comment so the browser confirms the connection
            yield ": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping every 30 s
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(q, tenant_id)
            diag("sse.unsubscribed", level="verbose", tenant_id=tenant_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
