"""tenant_context 자동 격리 통합 테스트 — in-memory SQLite (옵션 C)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base, Tenant, Reservation, ReservationStatus


class TestTenantIsolation:
    def test_query_returns_only_own_tenant_data(self, db):
        """tenant=1 컨텍스트에서 조회 시 테넌트 1 데이터만 반환."""
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
        """tenant 컨텍스트 없이 테넌트 모델 조회 → RuntimeError (옵션 C: session.info 비어있음)."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionFactory = sessionmaker(bind=engine)
        session = SessionFactory()

        try:
            with pytest.raises(RuntimeError, match="SECURITY"):
                session.query(Reservation).all()
        finally:
            session.close()
            engine.dispose()

    def test_bypass_allows_cross_tenant_query(self, db):
        """session.info['bypass_tenant']=True 면 RuntimeError 없이 조회 가능."""
        r1 = Reservation(
            tenant_id=1, customer_name="bypass_guest", phone="01033333333",
            check_in_date="2026-04-12", check_in_time="15:00",
            status=ReservationStatus.CONFIRMED,
        )
        db.add(r1)
        db.flush()

        # 옵션 C: 새 bypass session 으로 cross-tenant 조회
        SessionFactory = sessionmaker(bind=db.bind)
        bypass = SessionFactory()
        bypass.info['bypass_tenant'] = True
        try:
            results = bypass.query(Reservation).all()
            assert isinstance(results, list)
        finally:
            bypass.close()
