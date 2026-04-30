# Phase 0 산출물 #5: 테스트 인프라 영향도 인벤토리

## 현재 테스트 구조

```
backend/tests/
├── __init__.py
├── conftest.py             # ★ db fixture (in-memory SQLite + ContextVar set)
├── unit/                   # 단위 테스트 9개
└── integration/            # 통합 테스트 19개
```

## conftest.py 의존성

```python
@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(id=1, slug="test", name="Test Tenant")
    session.add(tenant)
    session.commit()
    token = current_tenant_id.set(1)        # ← ContextVar 의존
    yield session
    current_tenant_id.reset(token)
    session.close()
```

## ContextVar 직접 사용 테스트 (4 파일)

| 파일 | 사용 | 옵션 C 후 변경 |
|--|--|--|
| `conftest.py` | `current_tenant_id.set(1)` 으로 fixture 셋업 | `session = session_for_tenant(1)` factory 사용 |
| `test_tenant_isolation.py` | `current_tenant_id` / `bypass_tenant_filter` 직접 조작해 격리 검증 | session 기반 격리 시나리오로 재작성 |
| `test_surcharge_variables.py` | `current_tenant_id` import (조작 여부 확인 필요) | 동일 |
| `test_verify_tenant_access.py` | `current_tenant_id` import | 동일 |

## 통합 테스트 19개 영향도

### 직접 영향 (db fixture 사용 시 자동 영향) — 19개 모두
모든 통합 테스트가 `db` fixture 사용. conftest 변경 시 동시 영향.

| 테스트 | 카테고리 | 영향도 |
|--|--|--|
| `test_tenant_isolation.py` | 격리 가드 | **🔴 핵심 — 옵션 C 시나리오로 재작성** |
| `test_verify_tenant_access.py` | 접근 검증 | 🔴 동일 |
| `test_chip_reconcile_ab_alignment.py` | chip 라이프사이클 | 🟠 conftest 변경에 자동 적응 (영향 적음) |
| `test_reconcile_chips_schedule.py` | chip reconcile | 🟠 동일 |
| `test_reservation_matches.py` | filter logic | 🟢 fixture 만 영향 |
| `test_party3_mms.py` | MMS | 🟢 동일 |
| `test_reconcile_dates_extension.py` | date logic | 🟢 동일 |
| `test_date_target_compound_migration.py` | date target v2 | 🟢 동일 |
| `test_get_targets_event.py` | scheduler target | 🟠 옵션 C 후 schedule.tenant_id 변경 |
| `test_get_targets_standard.py` | 동일 | 🟠 동일 |
| `test_get_targets_custom.py` | 동일 | 🟠 동일 |
| `test_last_night_null_checkout.py` | edge case | 🟢 |
| `test_room_password_reuse.py` | 비밀번호 | 🟢 |
| `test_last_day_filter.py` | filter | 🟢 |
| `test_reconcile_dates.py` | date reconcile | 🟢 |
| `test_structural_filters.py` | filter logic | 🟢 |
| `test_first_night_group_dedup.py` | dedup | 🟢 |
| `test_surcharge_variables.py` | surcharge | 🟠 ContextVar 직접 사용 |
| `test_send_pipeline.py` | SMS pipeline | 🟠 send 로직 ContextVar 의존 |

## 단위 테스트 9개 영향도

대부분 ORM/DB 의존 없는 순수 함수 테스트. 영향 미미:

| 테스트 | 영향도 |
|--|--|
| `test_naver_process_raw_data.py` | 🟢 None (외부 데이터 변환) |
| `test_split_multi_room.py` | 🟢 None |
| `test_password_display.py` | 🟢 None |
| `test_unreplaced_vars.py` | 🟢 None |
| `test_resolve_date_target.py` | 🟢 None |
| `test_refresh_token.py` | 🟢 None |
| `test_schedule_dates.py` | 🟢 None |
| `test_apply_buffers.py` | 🟢 None |
| `test_detect_msg_type.py` | 🟢 None |

## 누락된 테스트 영역 (옵션 C 후 추가 필요)

### A. session factory 단위 테스트 (Phase 1 작업)
```
test_session_factory.py (신규)
- session_for_tenant(1) → session.info['tenant_id'] == 1
- session_bypass() → session.info['bypass_tenant'] == True
- session.query(Reservation) 자동 필터 검증
- session.add(Reservation) 자동 tenant_id 주입 검증
```

### B. 호환 shim 동작 테스트 (Phase 1 작업)
```
test_session_compat_shim.py (신규)
- ContextVar 만 set 한 상태 → before_compile 동작 (legacy fallback)
- session.info 만 set 한 상태 → before_compile 동작 (신규)
- 둘 다 set 했는데 다른 값 → diag log 발화 + session.info 우선
- 둘 다 None → RuntimeError
```

### C. cross-tenant 누수 회귀 테스트 (각 Phase)
```
test_cross_tenant_leak_regression.py (신규)
- 옵션 C 후 record_sms_sent 가 잘못된 reservation_id 받으면 RuntimeError
- 옵션 C 후 _get_targets_standard 가 cross-tenant 결과 0건
- 옵션 C 후 chip_reconciler 가 cross-tenant 스케줄 strip
- 동시 실행 시뮬레이션 (asyncio.gather) → 격리 유지
```

### D. lazy-load + session 종료 후 회귀 (Phase 4 후)
```
test_lazy_load_after_session_close.py (신규)
- 객체 detach 후 lazy attribute 접근 → DetachedInstanceError 또는 새 session
- response model 변환 시점에 lazy load 발생 안 하는지
```

## 우선순위

1. **Phase 1 시작 전**: A (session factory) + B (compat shim) 테스트 작성
2. **Phase 4 후**: C (cross-tenant 회귀) + D (lazy-load) 테스트 추가
3. **Phase 6 후**: 기존 19개 통합 테스트 + ContextVar 직접 사용 4 파일 정리

## conftest.py 옵션 C 변경안

```python
"""통합 테스트용 in-memory SQLite fixture (옵션 C)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Tenant


@pytest.fixture
def db():
    """In-memory SQLite 세션. 각 테스트마다 초기화."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()

    # Tenant 생성 (bypass 필요 — Tenant 자체는 TenantMixin 아님)
    tenant = Tenant(id=1, slug="test", name="Test Tenant")
    session.add(tenant)
    session.commit()

    # 옵션 C: session.info 에 tenant 박음 (ContextVar 안 씀)
    session.info['tenant_id'] = 1

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def db_bypass():
    """전역 작업용 bypass 세션."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    session.info['bypass_tenant'] = True
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def db_factory():
    """동적 tenant 생성 fixture (cross-tenant 테스트용)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    def _create(tenant_id: int):
        session = SessionFactory()
        session.info['tenant_id'] = tenant_id
        return session

    yield _create
    engine.dispose()
```

## 위험 신호

### 🟡 [Medium] 기존 19개 통합 테스트 회귀 가능
conftest 변경 후 일부 테스트가 ContextVar 직접 의존 시 깨짐. 사전에 모든 테스트 grep 으로 ContextVar 사용 확인 필요.

### 🟡 [Medium] 옵션 C 후 새 테스트 작성 시간
A + B + C + D 신규 테스트 약 4~6시간 소요 예상.

### 🟢 [Low] SQLite 한계
SQLite 는 RLS 미지원이지만 옵션 C 는 RLS 의존 안 하므로 무관.
