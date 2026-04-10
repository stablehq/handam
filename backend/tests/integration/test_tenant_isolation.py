"""tenant_context 자동 격리 통합 테스트 — in-memory SQLite."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base, Tenant, Reservation, ReservationStatus
from app.db.tenant_context import current_tenant_id, bypass_tenant_filter


class TestTenantIsolation:
    def test_query_returns_only_own_tenant_data(self, db):
        """tenant_id=1 컨텍스트에서 조회 시 테넌트 1 데이터만 반환."""
        # tenant_id=1 reservation (conftest db fixture already sets tid=1)
        r1 = Reservation(
            tenant_id=1, customer_name="tenant1_guest", phone="01011111111",
            check_in_date="2026-04-10", check_in_time="15:00",
            status=ReservationStatus.CONFIRMED,
        )
        db.add(r1)
        db.flush()

        results = db.query(Reservation).all()
        ids = [r.id for r in results]
        assert r1.id in ids
        # All results should belong to tenant 1
        for r in results:
            assert r.tenant_id == 1

    def test_insert_auto_assigns_tenant_id(self, db):
        """tenant_id 미지정 INSERT → 현재 테넌트 자동 주입."""
        res = Reservation(
            customer_name="auto_tenant", phone="01022222222",
            check_in_date="2026-04-11", check_in_time="15:00",
            status=ReservationStatus.CONFIRMED,
        )
        db.add(res)
        db.flush()

        assert res.tenant_id == 1

    def test_query_without_tenant_context_raises(self):
        """테넌트 컨텍스트 없이 테넌트 모델 조회 → RuntimeError."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Add a tenant so FK is satisfied
        tenant = Tenant(id=99, slug="isolated", name="Isolated Tenant")
        session.add(tenant)
        session.commit()

        # Set tenant_id to None (no context)
        token = current_tenant_id.set(None)
        bypass_token = bypass_tenant_filter.set(False)
        try:
            with pytest.raises(RuntimeError, match="SECURITY"):
                session.query(Reservation).all()
        finally:
            current_tenant_id.reset(token)
            bypass_tenant_filter.reset(bypass_token)
            session.close()
            engine.dispose()

    def test_bypass_allows_cross_tenant_query(self, db):
        """bypass_tenant_filter=True면 RuntimeError 없이 조회 가능."""
        r1 = Reservation(
            tenant_id=1, customer_name="bypass_guest", phone="01033333333",
            check_in_date="2026-04-12", check_in_time="15:00",
            status=ReservationStatus.CONFIRMED,
        )
        db.add(r1)
        db.flush()

        token_tid = current_tenant_id.set(None)
        token_bypass = bypass_tenant_filter.set(True)
        try:
            # Should not raise
            results = db.query(Reservation).all()
            assert isinstance(results, list)
        finally:
            current_tenant_id.reset(token_tid)
            bypass_tenant_filter.reset(token_bypass)
