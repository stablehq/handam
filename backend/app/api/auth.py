from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User, UserRole, Tenant, UserTenantRole
from app.auth.utils import verify_password, hash_password, create_access_token
from app.auth.schemas import LoginRequest, LoginResponse, UserInfo, TenantInfo, UserCreate, UserUpdate
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
        user=UserInfo(
            id=user.id,
            username=user.username,
            name=user.name,
            role=user.role.value,
            active=user.is_active,
            tenants=[TenantInfo(id=t.id, slug=t.slug, name=t.name) for t in tenants],
        ),
    )


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
):
    query = db.query(User)
    if current_user.role == UserRole.ADMIN:
        query = query.filter(User.role == UserRole.STAFF)
    else:
        query = query.filter(User.role != UserRole.SUPERADMIN)
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
):
    target_role = UserRole(request.role)

    if current_user.role == UserRole.ADMIN and target_role != UserRole.STAFF:
        raise HTTPException(status_code=403, detail="admin은 staff 계정만 생성할 수 있습니다")
    if target_role == UserRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="superadmin 계정은 생성할 수 없습니다")

    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다")

    user = User(
        username=request.username,
        hashed_password=hash_password(request.password),
        name=request.name,
        role=target_role,
        is_active=True,
    )
    db.add(user)
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
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

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
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="자기 자신을 삭제할 수 없습니다")

    if ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY.get(current_user.role, 0):
        raise HTTPException(status_code=403, detail="같거나 상위 권한의 사용자를 삭제할 수 없습니다")

    user.is_active = False
    db.commit()

    return {"message": "사용자가 비활성화되었습니다"}
