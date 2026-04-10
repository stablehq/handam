"""verify_tenant_access() 통합 테스트 — in-memory SQLite."""
import pytest
from fastapi import HTTPException
from app.db.models import User, UserRole, UserTenantRole, Tenant
from app.auth.dependencies import verify_tenant_access
from app.db.tenant_context import current_tenant_id


def _make_user(db, role=UserRole.ADMIN, username="testuser"):
    from app.auth.utils import hash_password
    user = User(
        username=username,
        hashed_password=hash_password("password"),
        name=username,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_tenant(db, tenant_id=2, slug="tenant2"):
    # Only add if not already present
    existing = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if existing:
        return existing
    t = Tenant(id=tenant_id, slug=slug, name=f"Tenant {tenant_id}")
    db.add(t)
    db.flush()
    return t


def _grant_access(db, user_id, tenant_id):
    mapping = UserTenantRole(user_id=user_id, tenant_id=tenant_id)
    db.add(mapping)
    db.flush()
    return mapping


import asyncio


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestVerifyTenantAccess:
    def test_superadmin_can_access_any_tenant(self, db):
        """SUPERADMIN → 어떤 테넌트도 접근 가능."""
        user = _make_user(db, role=UserRole.SUPERADMIN, username="superadmin")
        _make_tenant(db, tenant_id=2)

        result = run_async(verify_tenant_access(
            tenant_id=2,
            current_user=user,
            db=db,
        ))
        assert result == 2

    def test_admin_with_mapping_allowed(self, db):
        """ADMIN + 테넌트 매핑 있음 → 접근 허용."""
        user = _make_user(db, role=UserRole.ADMIN, username="admin_mapped")
        _make_tenant(db, tenant_id=3, slug="tenant3")
        _grant_access(db, user.id, 3)

        result = run_async(verify_tenant_access(
            tenant_id=3,
            current_user=user,
            db=db,
        ))
        assert result == 3

    def test_admin_without_mapping_denied(self, db):
        """ADMIN + 테넌트 매핑 없음 → 403 Forbidden."""
        user = _make_user(db, role=UserRole.ADMIN, username="admin_no_map")
        _make_tenant(db, tenant_id=4, slug="tenant4")

        with pytest.raises(HTTPException) as exc:
            run_async(verify_tenant_access(
                tenant_id=4,
                current_user=user,
                db=db,
            ))
        assert exc.value.status_code == 403

    def test_staff_without_mapping_denied(self, db):
        """STAFF + 매핑 없음 → 403."""
        user = _make_user(db, role=UserRole.STAFF, username="staff_user")
        _make_tenant(db, tenant_id=5, slug="tenant5")

        with pytest.raises(HTTPException) as exc:
            run_async(verify_tenant_access(
                tenant_id=5,
                current_user=user,
                db=db,
            ))
        assert exc.value.status_code == 403

    def test_superadmin_can_access_own_tenant(self, db):
        """SUPERADMIN → tenant_id=1(conftest 기본)도 접근 가능."""
        user = _make_user(db, role=UserRole.SUPERADMIN, username="sa2")

        result = run_async(verify_tenant_access(
            tenant_id=1,
            current_user=user,
            db=db,
        ))
        assert result == 1
