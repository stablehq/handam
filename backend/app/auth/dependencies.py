from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User, UserRole, UserTenantRole
from app.auth.utils import decode_access_token
from app.api.deps import get_current_tenant_id
import jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보가 유효하지 않습니다",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었습니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_role(*roles: UserRole):
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 없습니다",
            )
        return current_user
    return role_checker


require_superadmin = require_role(UserRole.SUPERADMIN)
require_admin_or_above = require_role(UserRole.SUPERADMIN, UserRole.ADMIN)
require_any_role = require_role(UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.STAFF)


async def verify_tenant_access(
    tenant_id: int = Depends(get_current_tenant_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> int:
    """Verify current user has access to the requested tenant."""
    if current_user.role == UserRole.SUPERADMIN:
        return tenant_id

    mapping = db.query(UserTenantRole).filter(
        UserTenantRole.user_id == current_user.id,
        UserTenantRole.tenant_id == tenant_id,
    ).first()

    if not mapping:
        raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")

    return tenant_id
