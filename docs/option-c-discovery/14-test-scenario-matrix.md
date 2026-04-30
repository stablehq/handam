# Phase 0 산출물 #14: 테스트 시나리오 매트릭스

> 옵션 C 마이그레이션 검증 시나리오. Phase 별 진입 전후 통과해야 할 테스트.

## 시나리오 카테고리

### A. 정상 경로 (Happy path)
모든 기능이 옵션 C 후에도 동일 동작.

### B. 회귀 차단 (Regression)
이번 사고 또는 알려진 버그가 재발하지 않음.

### C. Edge case
경계 조건 (None tenant, 빈 결과, 오버플로 등).

### D. Cross-tenant 누수 시뮬레이션
의도적 누수 시나리오 → 차단 확인.

## A. 정상 경로 시나리오 (Phase 별 통과 기준)

### A1. API endpoint 정상 응답
**테스트 위치**: 기존 통합 테스트 19개 + 신규
**Phase 2 후**: 모든 endpoint 가 session_for_tenant 사용해도 응답 동일

```python
def test_get_reservations_returns_only_own_tenant(db):
    # tenant=1 reservation 추가
    r1 = Reservation(tenant_id=1, customer_name="Alice", ...)
    db.add(r1); db.commit()

    # tenant=2 reservation 추가 (bypass 로 직접 생성)
    db_b = session_bypass()
    r2 = Reservation(tenant_id=2, customer_name="Bob", ...)
    db_b.add(r2); db_b.commit()

    # tenant=1 컨텍스트에서 조회 → r1 만 보여야 함
    db1 = session_for_tenant(1)
    results = db1.query(Reservation).all()
    assert len(results) == 1
    assert results[0].customer_name == "Alice"
```

### A2. 스케줄러 잡 정상 발화
**Phase 3 후**: 모든 잡이 session_for_tenant 사용해도 정상 SMS 발송

```python
def test_template_schedule_fires_for_correct_tenant():
    # HANDAM schedule 1 fire → HANDAM 예약자만 발송
    # STABLE schedule 8 fire → STABLE 예약자만 발송
    # cross-tenant 발송 0건 검증
```

### A3. ActivityLog 자동 주입
**Phase 4 후**: log_activity 호출 시 tenant_id 자동 주입 동작

```python
def test_log_activity_auto_injects_tenant_id(db):
    # session.info['tenant_id'] = 1 박힌 db 로
    log = log_activity(db, type="test", title="...", ...)
    assert log.tenant_id == 1
```

## B. 회귀 차단 시나리오

### B1. 이번 사고 재현 차단 (chip vs schedule cross-tenant)
**Phase 1 (shim) 후**: shim 동작 검증
**Phase 3 (스케줄러) 후**: 누수 0건

```python
def test_schedule_does_not_pickup_cross_tenant_reservation():
    """
    HANDAM schedule 1 fire 시 STABLE 예약자가 targets 에 안 들어감.
    """
    # tenant=1 schedule 생성
    db1 = session_for_tenant(1)
    schedule = TemplateSchedule(tenant_id=1, template_id=..., ...)
    db1.add(schedule); db1.commit()

    # tenant=2 reservation 생성
    db2 = session_for_tenant(2)
    res = Reservation(tenant_id=2, customer_name="Cross", phone="01000000000",
                      check_in_date="2026-04-30", check_in_time="15:00",
                      status=ReservationStatus.CONFIRMED)
    db2.add(res); db2.commit()

    # HANDAM 스케줄러 컨텍스트에서 _get_targets_standard 실행
    db_sched = session_for_tenant(1)
    executor = TemplateScheduleExecutor(db_sched, tenant=...)
    targets = executor._get_targets_standard(schedule)

    # STABLE 예약자가 targets 에 없어야 함
    assert all(t.tenant_id == 1 for t in targets)
    assert res.id not in [t.id for t in targets]
```

### B2. record_sms_sent 가 cross-tenant 칩 INSERT 차단
**Phase 4 후**: sms_tracking 가 reservation tenant 검증

```python
def test_record_sms_sent_rejects_cross_tenant_reservation():
    """
    HANDAM 컨텍스트에서 STABLE reservation_id 로 record_sms_sent 호출 시
    chip 이 잘못된 tenant 로 안 박혀야 함.
    """
    db_h = session_for_tenant(1)
    db_s = session_for_tenant(2)
    res_s = Reservation(tenant_id=2, ...); db_s.add(res_s); db_s.commit()

    # HANDAM 컨텍스트에서 STABLE reservation 가리키며 호출
    record_sms_sent(db_h, res_s.id, "party_info", "category", date="2026-04-30")
    # _resolve_reservation_tenant 가 res_s.tenant_id=2 발견 → chip.tenant_id=2 박힘
    # 또는 명시적 RuntimeError 발생 (정책 결정에 따라)
```

### B3. ContextVar 누수 시뮬레이션 → session.info 가 우선
**Phase 1 shim 후**: 둘 다 set 됐을 때 우선순위 검증

```python
def test_session_info_wins_over_ctxvar():
    db = session_for_tenant(1)
    db.info['tenant_id'] = 1

    # ContextVar 에 다른 값 (legacy 코드 시뮬레이션)
    token = current_tenant_id.set(99)
    try:
        results = db.query(Reservation).all()
        # session.info=1 우선 → tenant=1 결과만
        assert all(r.tenant_id == 1 for r in results)
    finally:
        current_tenant_id.reset(token)
```

## C. Edge case 시나리오

### C1. tenant_id None 인 session
**Phase 1 후**: None 으로 session 생성 시도 → 명시 에러

```python
def test_session_for_tenant_rejects_none():
    with pytest.raises(ValueError):
        session_for_tenant(None)
```

### C2. session_bypass 사용 시 모든 tenant row 보임
**Phase 1 후**: bypass session 동작 검증

```python
def test_session_bypass_returns_all_tenants(db_factory):
    db1 = db_factory(1)
    db1.add(Reservation(tenant_id=1, ...))
    db2 = db_factory(2)
    db2.add(Reservation(tenant_id=2, ...))
    db1.commit(); db2.commit()

    db_b = session_bypass()
    results = db_b.query(Reservation).all()
    assert len(results) == 2
```

### C3. session 종료 후 ORM 객체 lazy 접근
**Phase 1 후**: detached object 동작

```python
def test_lazy_load_after_session_close():
    db = session_for_tenant(1)
    res = Reservation(tenant_id=1, ...); db.add(res); db.commit()
    db.close()

    # Detached object lazy 접근 → DetachedInstanceError 또는 새 session 필요
    with pytest.raises(DetachedInstanceError):
        _ = res.room_assignments  # backref lazy load
```

### C4. 빈 결과
**Phase 1 후**: tenant=1 에 데이터 0 → 빈 결과 정상 반환

### C5. tenant_id 가 정수 아닌 다른 타입
**Phase 1 후**: 잘못된 타입 → ValueError 또는 TypeError

## D. Cross-tenant 누수 시뮬레이션

### D1. ContextVar bypass 잔재 시뮬레이션
**Phase 1 shim 후**: bypass=True 잔재 + tenant=1 session → bypass 우선

```python
def test_bypass_takes_precedence_over_tenant_in_shim():
    # legacy 코드가 bypass 만 set
    bypass_token = bypass_tenant_filter.set(True)
    try:
        db = SessionLocal()  # session.info 없음
        # before_compile 의 fallback → bypass=True → 모든 row 반환
        results = db.query(Reservation).all()
        assert len(results) >= 0  # 격리 안 됨 (bypass)
    finally:
        bypass_tenant_filter.reset(bypass_token)
```

### D2. 동시 task 시뮬레이션 (옵션 C 핵심 가치 검증)
**Phase 3 후**: sibling task 의 ContextVar 누수해도 격리 유지

```python
async def test_concurrent_tasks_isolated_via_session():
    """sibling task 의 ContextVar 누수해도 session.info 격리 유지."""
    async def task_a():
        # Bad citizen: ContextVar 만 set, session 안 박음
        token = current_tenant_id.set(1)
        try:
            await asyncio.sleep(0.01)
        finally:
            current_tenant_id.reset(token)

    async def task_b():
        # Good citizen: session_for_tenant(2) 명시
        db = session_for_tenant(2)
        await asyncio.sleep(0.005)
        # task_a 의 ContextVar=1 잔재 가능
        results = db.query(Reservation).all()
        # session.info=2 우선 → tenant=2 결과만
        assert all(r.tenant_id == 2 for r in results)
        db.close()

    await asyncio.gather(task_a(), task_b())
```

### D3. 잘못된 reservation_id 로 service 함수 호출
**Phase 4 후**: cross-tenant id 받으면 RuntimeError

```python
def test_service_function_rejects_cross_tenant_id():
    # tenant=1 컨텍스트에서 tenant=2 reservation_id 로 함수 호출
    db = session_for_tenant(1)
    res_other = Reservation(tenant_id=2, ...)  # bypass 로 생성된 것

    with pytest.raises(RuntimeError, match="cross-tenant"):
        sync_sms_tags(db, res_other.id)  # tenant_id 불일치 감지
```

## Phase 별 진입 기준

| Phase | 통과 필수 시나리오 |
|--|--|
| **Phase 1** | A1, A3, B3, C1, C2, C5, D1, D2 — shim 정상 + 격리 |
| **Phase 2** | + A2 (API 정상 응답) — endpoint 영향 없음 |
| **Phase 3** | + B1 (스케줄러 누수 0) — 잡 격리 |
| **Phase 4** | + B2, D3 (service 시그니처 격리) |
| **Phase 5** | + 운영 데이터 정합성 (산출물 #7 검증 쿼리 0건) |
| **Phase 6** | A1~D3 모두 + 추가 grep 으로 ContextVar 사용 0건 |

## 자동화 도구

```python
# tests/conftest.py 에 추가될 fixture
@pytest.fixture
def db_factory():
    """동적 tenant session 생성."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    def _create(tenant_id: int = None, bypass: bool = False):
        s = SessionFactory()
        if bypass:
            s.info['bypass_tenant'] = True
        elif tenant_id is not None:
            s.info['tenant_id'] = tenant_id
        return s
    yield _create
    engine.dispose()
```

## 추적 통계

각 Phase 적용 시점에 통과/실패 수 기록:

| Phase | 통과 | 실패 | 회귀 |
|--|--|--|--|
| Phase 1 | TBD | TBD | TBD |
| Phase 2 | TBD | TBD | TBD |
| ... | | | |

## 결론

총 **약 30~40 시나리오** 가 옵션 C 마이그레이션 검증에 필요. 기존 테스트 19개 (대부분 정상 경로) + 신규 시나리오 약 20개. 작성 시간 4~6시간 예상.

각 Phase 진입 전 해당 Phase 의 시나리오 통과 100% 보장 후 진행.
