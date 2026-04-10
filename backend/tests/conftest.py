"""통합 테스트용 in-memory SQLite fixture."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Tenant
from app.db.tenant_context import current_tenant_id


@pytest.fixture
def db():
    """In-memory SQLite 세션. 각 테스트마다 초기화."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # 테스트용 테넌트 생성 + ContextVar 설정
    tenant = Tenant(id=1, slug="test", name="Test Tenant")
    session.add(tenant)
    session.commit()
    token = current_tenant_id.set(1)

    yield session

    current_tenant_id.reset(token)
    session.close()
    engine.dispose()
