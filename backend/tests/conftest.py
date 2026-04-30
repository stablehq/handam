"""통합 테스트용 in-memory SQLite fixture (옵션 C)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Tenant


@pytest.fixture
def db():
    """In-memory SQLite 세션. 각 테스트마다 초기화. 옵션 C: session.info 에 tenant 박음."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    # 옵션 C: bypass session 으로 tenant 생성 (Tenant 는 비-TenantMixin)
    bypass = SessionFactory()
    bypass.info['bypass_tenant'] = True
    tenant = Tenant(id=1, slug="test", name="Test Tenant")
    bypass.add(tenant)
    bypass.commit()
    bypass.close()

    # 본 테스트용 session — tenant=1 컨텍스트
    session = SessionFactory()
    session.info['tenant_id'] = 1

    yield session

    session.close()
    engine.dispose()
