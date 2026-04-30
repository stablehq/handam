"""옵션 C session factory 단위/통합 테스트.

검증 항목:
- session_for_tenant(tid) 가 session.info 에 tenant_id 박음
- session_bypass() 가 session.info 에 bypass 박음
- session_unscoped() 가 session.info 비어있음
- session_for_tenant(None) → ValueError
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import database as db_module
from app.db.models import Base


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch):
    """SessionLocal 을 in-memory SQLite 로 교체 — 운영 DB 영향 0."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    InMemorySession = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", InMemorySession)
    yield
    engine.dispose()


def test_session_for_tenant_sets_info():
    """session_for_tenant(1) → session.info['tenant_id'] == 1"""
    s = db_module.session_for_tenant(1)
    try:
        assert s.info.get('tenant_id') == 1
        assert 'bypass_tenant' not in s.info
    finally:
        s.close()


def test_session_for_tenant_with_different_id():
    """다른 tenant_id 로 호출하면 다른 값 박힘"""
    s1 = db_module.session_for_tenant(1)
    s2 = db_module.session_for_tenant(2)
    try:
        assert s1.info.get('tenant_id') == 1
        assert s2.info.get('tenant_id') == 2
    finally:
        s1.close()
        s2.close()


def test_session_for_tenant_rejects_none():
    """tenant_id=None 호출 시 ValueError 발생"""
    with pytest.raises(ValueError, match="tenant_id must not be None"):
        db_module.session_for_tenant(None)


def test_session_bypass_sets_flag():
    """session_bypass() → session.info['bypass_tenant'] == True"""
    s = db_module.session_bypass()
    try:
        assert s.info.get('bypass_tenant') is True
        assert 'tenant_id' not in s.info
    finally:
        s.close()


def test_session_unscoped_has_no_info():
    """session_unscoped() → session.info 가 비어있음 (legacy 호환)"""
    s = db_module.session_unscoped()
    try:
        assert s.info.get('tenant_id') is None
        assert s.info.get('bypass_tenant') is None
    finally:
        s.close()


def test_factory_returns_independent_sessions():
    """factory 호출마다 독립 session 객체 반환"""
    s1 = db_module.session_for_tenant(1)
    s2 = db_module.session_for_tenant(1)
    try:
        assert s1 is not s2
        # info 도 독립 dict
        s1.info['custom'] = 'a'
        assert 'custom' not in s2.info
    finally:
        s1.close()
        s2.close()
