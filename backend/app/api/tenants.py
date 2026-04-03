"""Tenant management API endpoints"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from app.db.database import get_db
from app.db.models import Tenant, User, UserTenantRole, UserRole
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


class TenantResponse(BaseModel):
    id: int
    slug: str
    name: str
    is_active: bool
    has_unstable: bool = False

    class Config:
        from_attributes = True


@router.get("", response_model=List[TenantResponse])
async def get_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get tenants accessible to current user"""
    if current_user.role == UserRole.SUPERADMIN:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    else:
        tenants = (
            db.query(Tenant)
            .join(UserTenantRole, UserTenantRole.tenant_id == Tenant.id)
            .filter(
                UserTenantRole.user_id == current_user.id,
                Tenant.is_active == True,
            )
            .all()
        )
    return [
        TenantResponse(
            id=t.id, slug=t.slug, name=t.name, is_active=t.is_active,
            has_unstable=bool(t.unstable_business_id),
        )
        for t in tenants
    ]
