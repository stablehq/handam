"""옵션 C session-bound tenant 격리 검증 (Phase 6 최종판).

검증 항목:
- session.info['tenant_id'] 로 자동 격리
- session.info['bypass_tenant'] 로 cross-tenant 조회
- 컨텍스트 없으면 RuntimeError (fail-closed)
- 동일 세션에서 INSERT 시 tenant_id 자동 주입
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Tenant, Reservation, ReservationStatus
from app.db.tenant_context import _resolve_tenant_context


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


def _seed_two_tenants(session):
    """tenant=1, tenant=2 각각 reservation 1건씩 만든다."""
    session.add(Tenant(id=1, slug="t1", name="Tenant 1"))
    session.add(Tenant(id=2, slug="t2", name="Tenant 2"))
    session.flush()
    session.add(Reservation(
        tenant_id=1, customer_name="alice", phone="01011111111",
        check_in_date="2026-05-01", check_in_time="15:00",
        status=ReservationStatus.CONFIRMED,
    ))
    session.add(Reservation(
        tenant_id=2, customer_name="bob", phone="01022222222",
        check_in_date="2026-05-01", check_in_time="15:00",
        status=ReservationStatus.CONFIRMED,
    ))
    session.commit()


# ──────────────────────────────────────────────────────────────────
# _resolve_tenant_context 직접 검증
# ──────────────────────────────────────────────────────────────────


def test_resolve_session_info_tenant(session_factory):
    """session.info['tenant_id'] 가 정확히 반환됨."""
    s = session_factory()
    s.info['tenant_id'] = 1
    try:
        tid, bypass = _resolve_tenant_context(s)
        assert tid == 1
        assert bypass is False
    finally:
        s.close()


def test_resolve_session_info_bypass(session_factory):
    """session.info['bypass_tenant']=True → bypass 활성."""
    s = session_factory()
    s.info['bypass_tenant'] = True
    try:
        tid, bypass = _resolve_tenant_context(s)
        assert tid is None
        assert bypass is True
    finally:
        s.close()


def test_resolve_empty_session(session_factory):
    """session.info 비어있으면 (None, False) — fail-closed 신호."""
    s = session_factory()
    try:
        tid, bypass = _resolve_tenant_context(s)
        assert tid is None
        assert bypass is False
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────────
# before_compile (auto-filter) 동작 검증
# ──────────────────────────────────────────────────────────────────


def test_query_filtered_by_session_info(session_factory):
    """session.info=1 → tenant=1 결과만 반환."""
    seed_session = session_factory()
    seed_session.info['bypass_tenant'] = True
    _seed_two_tenants(seed_session)
    seed_session.close()

    s = session_factory()
    s.info['tenant_id'] = 1
    try:
        results = s.query(Reservation).all()
        assert all(r.tenant_id == 1 for r in results)
        assert len(results) == 1
        assert results[0].customer_name == "alice"
    finally:
        s.close()


def test_query_bypass_returns_all_tenants(session_factory):
    """session.info bypass=True → 모든 tenant 결과."""
    seed_session = session_factory()
    seed_session.info['bypass_tenant'] = True
    _seed_two_tenants(seed_session)
    seed_session.close()

    s = session_factory()
    s.info['bypass_tenant'] = True
    try:
        results = s.query(Reservation).all()
        assert len(results) == 2
    finally:
        s.close()


def test_query_no_context_raises(session_factory):
    """session.info 없으면 RuntimeError (fail-closed)."""
    s = session_factory()
    try:
        with pytest.raises(RuntimeError, match="without tenant context"):
            s.query(Reservation).all()
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────────
# before_flush (auto-inject tenant_id) 검증
# ──────────────────────────────────────────────────────────────────


def test_flush_injects_tenant_id_from_session_info(session_factory):
    """session.info=1 으로 INSERT → tenant_id 자동 주입."""
    bypass_session = session_factory()
    bypass_session.info['bypass_tenant'] = True
    bypass_session.add(Tenant(id=1, slug="t1", name="Tenant 1"))
    bypass_session.commit()
    bypass_session.close()

    s = session_factory()
    s.info['tenant_id'] = 1
    try:
        res = Reservation(
            customer_name="auto",
            phone="01099999999",
            check_in_date="2026-05-01",
            check_in_time="15:00",
            status=ReservationStatus.CONFIRMED,
        )
        s.add(res)
        s.flush()
        assert res.tenant_id == 1
    finally:
        s.close()


def test_two_sessions_isolated(session_factory):
    """두 session 이 각자 다른 tenant 컨텍스트 — 동일 query 다른 결과."""
    seed_session = session_factory()
    seed_session.info['bypass_tenant'] = True
    _seed_two_tenants(seed_session)
    seed_session.close()

    s1 = session_factory()
    s1.info['tenant_id'] = 1
    s2 = session_factory()
    s2.info['tenant_id'] = 2
    try:
        r1 = s1.query(Reservation).all()
        r2 = s2.query(Reservation).all()
        assert all(r.tenant_id == 1 for r in r1)
        assert all(r.tenant_id == 2 for r in r2)
        assert {r.customer_name for r in r1} == {"alice"}
        assert {r.customer_name for r in r2} == {"bob"}
    finally:
        s1.close()
        s2.close()
