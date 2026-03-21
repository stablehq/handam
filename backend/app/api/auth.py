import jwt
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from typing import Optional
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User, UserRole, Tenant, UserTenantRole
from app.auth.utils import verify_password, hash_password, create_access_token, create_refresh_token, decode_refresh_token
from app.auth.schemas import LoginRequest, LoginResponse, UserInfo, TenantInfo, UserCreate, UserUpdate, RefreshRequest, RefreshResponse
from app.auth.dependencies import get_current_user, require_admin_or_above
from app.rate_limit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

ROLE_HIERARCHY = {
    UserRole.SUPERADMIN: 3,
    UserRole.ADMIN: 2,
    UserRole.STAFF: 1,
}


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(request: Request, login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == login_data.username).first()
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비활성화된 계정입니다",
        )

    token = create_access_token(data={"sub": user.username})
    refresh = create_refresh_token(data={"sub": user.username})

    # Get accessible tenants
    if user.role == UserRole.SUPERADMIN:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    else:
        tenants = (
            db.query(Tenant)
            .join(UserTenantRole, UserTenantRole.tenant_id == Tenant.id)
            .filter(UserTenantRole.user_id == user.id, Tenant.is_active == True)
            .all()
        )

    return LoginResponse(
        access_token=token,
        refresh_token=refresh,
        user=UserInfo(
            id=user.id,
            username=user.username,
            name=user.name,
            role=user.role.value,
            active=user.is_active,
            tenants=[TenantInfo(id=t.id, slug=t.slug, name=t.name) for t in tenants],
        ),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    """Issue new access + refresh tokens using a valid refresh token"""
    try:
        payload = decode_refresh_token(req.refresh_token)
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="리프레시 토큰이 만료되었습니다. 다시 로그인해주세요")
    except (jwt.PyJWTError, Exception):
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")

    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="유효하지 않은 사용자입니다")

    new_access = create_access_token(data={"sub": username})
    new_refresh = create_refresh_token(data={"sub": username})

    return RefreshResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Get accessible tenants
    if current_user.role == UserRole.SUPERADMIN:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    else:
        tenants = (
            db.query(Tenant)
            .join(UserTenantRole, UserTenantRole.tenant_id == Tenant.id)
            .filter(UserTenantRole.user_id == current_user.id, Tenant.is_active == True)
            .all()
        )

    return UserInfo(
        id=current_user.id,
        username=current_user.username,
        name=current_user.name,
        role=current_user.role.value,
        active=current_user.is_active,
        tenants=[TenantInfo(id=t.id, slug=t.slug, name=t.name) for t in tenants],
    )


@router.get("/users", response_model=list[UserInfo])
async def list_users(
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db),
    x_tenant_id: Optional[int] = Header(None, alias="X-Tenant-Id"),
):
    query = db.query(User)
    if current_user.role == UserRole.ADMIN:
        # ADMIN: tenant_id required, must verify membership
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-Id 헤더가 필요합니다")
        admin_mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == current_user.id,
            UserTenantRole.tenant_id == x_tenant_id,
        ).first()
        if not admin_mapping:
            raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")
        query = query.filter(User.role == UserRole.STAFF)
        query = query.join(UserTenantRole, UserTenantRole.user_id == User.id).filter(
            UserTenantRole.tenant_id == x_tenant_id
        )
    else:
        # SUPERADMIN: optional tenant filter
        query = query.filter(User.role != UserRole.SUPERADMIN)
        if x_tenant_id:
            query = query.join(UserTenantRole, UserTenantRole.user_id == User.id).filter(
                UserTenantRole.tenant_id == x_tenant_id
            )

    users = query.order_by(User.created_at.desc()).all()
    return [
        UserInfo(
            id=u.id, username=u.username, name=u.name,
            role=u.role.value, active=u.is_active,
        )
        for u in users
    ]


@router.post("/users", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreate,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db),
    x_tenant_id: Optional[int] = Header(None, alias="X-Tenant-Id"),
):
    target_role = UserRole(request.role)

    if current_user.role == UserRole.ADMIN and target_role != UserRole.STAFF:
        raise HTTPException(status_code=403, detail="admin은 staff 계정만 생성할 수 있습니다")
    if target_role == UserRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="superadmin 계정은 생성할 수 없습니다")

    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다")

    # ADMIN must have access to the target tenant
    if current_user.role == UserRole.ADMIN:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-Id 헤더가 필요합니다")
        admin_mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == current_user.id,
            UserTenantRole.tenant_id == x_tenant_id,
        ).first()
        if not admin_mapping:
            raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")

    user = User(
        username=request.username,
        hashed_password=hash_password(request.password),
        name=request.name,
        role=target_role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    # 현재 테넌트에 자동 매핑
    if x_tenant_id:
        db.add(UserTenantRole(user_id=user.id, tenant_id=x_tenant_id))

    db.commit()
    db.refresh(user)

    return UserInfo(
        id=user.id, username=user.username, name=user.name,
        role=user.role.value, active=user.is_active,
    )


@router.put("/users/{user_id}", response_model=UserInfo)
async def update_user(
    user_id: int,
    request: UserUpdate,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db),
    x_tenant_id: Optional[int] = Header(None, alias="X-Tenant-Id"),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    # ADMIN은 같은 테넌트 소속 유저만 수정 가능
    if current_user.role == UserRole.ADMIN:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-Id 헤더가 필요합니다")
        # Verify ADMIN belongs to this tenant
        admin_mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == current_user.id,
            UserTenantRole.tenant_id == x_tenant_id,
        ).first()
        if not admin_mapping:
            raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")
        # Verify target user belongs to this tenant
        mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == user_id,
            UserTenantRole.tenant_id == x_tenant_id,
        ).first()
        if not mapping:
            raise HTTPException(status_code=403, detail="해당 펜션 소속이 아닌 사용자입니다")

    if ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY.get(current_user.role, 0):
        raise HTTPException(status_code=403, detail="같거나 상위 권한의 사용자를 수정할 수 없습니다")

    if request.username is not None:
        if request.username != user.username:
            existing = db.query(User).filter(User.username == request.username).first()
            if existing:
                raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다")
            user.username = request.username
    if request.name is not None:
        user.name = request.name
    if request.password is not None:
        user.hashed_password = hash_password(request.password)
    if request.role is not None:
        new_role = UserRole(request.role)
        if current_user.role == UserRole.ADMIN and new_role != UserRole.STAFF:
            raise HTTPException(status_code=403, detail="admin은 staff 역할만 설정할 수 있습니다")
        if new_role == UserRole.SUPERADMIN:
            raise HTTPException(status_code=403, detail="superadmin 역할을 부여할 수 없습니다")
        user.role = new_role
    if request.active is not None:
        user.is_active = request.active

    db.commit()
    db.refresh(user)

    return UserInfo(
        id=user.id, username=user.username, name=user.name,
        role=user.role.value, active=user.is_active,
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db),
    x_tenant_id: Optional[int] = Header(None, alias="X-Tenant-Id"),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="자기 자신을 삭제할 수 없습니다")

    # ADMIN은 같은 테넌트 소속 유저만 삭제 가능
    if current_user.role == UserRole.ADMIN:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-Id 헤더가 필요합니다")
        admin_mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == current_user.id,
            UserTenantRole.tenant_id == x_tenant_id,
        ).first()
        if not admin_mapping:
            raise HTTPException(status_code=403, detail="해당 펜션에 대한 접근 권한이 없습니다")
        mapping = db.query(UserTenantRole).filter(
            UserTenantRole.user_id == user_id,
            UserTenantRole.tenant_id == x_tenant_id,
        ).first()
        if not mapping:
            raise HTTPException(status_code=403, detail="해당 펜션 소속이 아닌 사용자입니다")

    if ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY.get(current_user.role, 0):
        raise HTTPException(status_code=403, detail="같거나 상위 권한의 사용자를 삭제할 수 없습니다")

    user.is_active = False
    db.commit()

    return {"message": "사용자가 비활성화되었습니다"}
