"""
FastAPI dependencies for multi-tenant support.
"""
from typing import Optional
from fastapi import Header, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.db.database import get_db, SessionLocal
from app.db.tenant_context import current_tenant_id


async def get_current_tenant_id(
    request: Request,
    x_tenant_id: Optional[int] = Header(None, alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> int:
    """
    Extract tenant_id from X-Tenant-Id header.
    During transition period, defaults to 1 (handam) if header is missing.
    Also verifies the current user has access to the requested tenant.

    Uses Request-based token extraction to avoid circular import with
    auth/dependencies.py (which itself imports get_current_tenant_id).
    """
    from app.db.models import Tenant, User, UserTenantRole, UserRole
    from app.auth.utils import decode_access_token
    import jwt

    if x_tenant_id is None:
        raise HTTPException(status_code=400, detail="X-Tenant-Id 헤더가 필요합니다")

    tenant = db.query(Tenant).filter(
        Tenant.id == x_tenant_id,
        Tenant.is_active == True,
    ).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="유효하지 않은 테넌트입니다")

    # Resolve the current user from the Authorization header if present.
    # Deferred inline to avoid circular import: auth/dependencies.py imports this module.
    current_user = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            payload = decode_access_token(token)
            username = payload.get("sub")
            if username:
                current_user = db.query(User).filter(
                    User.username == username,
                    User.is_active == True,
                ).first()
        except (jwt.PyJWTError, Exception):
            # Invalid/expired token — let downstream auth deps handle the 401.
            pass

    # Verify user has access to this tenant (skip check for SUPERADMIN and unauthenticated).
    if current_user is not None and current_user.role != UserRole.SUPERADMIN:
        mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == current_user.id,
            UserTenantRole.tenant_id == tenant.id,
        ).first()
        if not mapping:
            raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")

    return tenant.id


async def get_current_tenant(
    tenant_id: int = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """Get full Tenant object for endpoints that need tenant settings (e.g., Naver sync).
    Depends on get_current_tenant_id to reuse user-tenant access verification."""
    from app.db.models import Tenant
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.is_active == True,
    ).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="유효하지 않은 테넌트입니다")
    return tenant


def _remap_active_field(data: dict) -> dict:
    """Remap 'active' key to 'is_active' for ORM compatibility."""
    if "active" in data:
        data["is_active"] = data.pop("active")
    return data


async def get_tenant_scoped_db(
    tenant_id: int = Depends(get_current_tenant_id),
):
    """
    DB session with tenant context set.
    Use this instead of get_db() for all tenant-scoped endpoints.

    The ContextVar ensures:
    - before_compile auto-filters SELECT queries
    - before_flush auto-injects tenant_id on INSERT

    Note: async generator avoids ContextVar cross-thread issues
    that occur with sync generators in FastAPI's thread pool.
    """
    current_tenant_id.set(tenant_id)
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
