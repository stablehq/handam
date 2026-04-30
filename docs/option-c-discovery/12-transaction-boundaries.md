# Phase 0 산출물 #12: 트랜잭션 경계 다이어그램

> 옵션 C 후 session 의 lifecycle 이 곧 tenant 컨텍스트 lifecycle. 트랜잭션 경계 정확히 파악.

## 통계

- **db.commit() / session.commit() / db.rollback()**: 97곳 across 20+ 파일
- **begin_nested**: 0건
- **async generator (yield)**: 2곳 (`get_tenant_scoped_db`, `event_stream`)

## 패턴별 분류

### 패턴 A: API endpoint (FastAPI dependency)

```python
# get_tenant_scoped_db (deps.py:95)
async def get_tenant_scoped_db(...):
    token = current_tenant_id.set(tenant_id)
    db = SessionLocal()
    try:
        yield db                          # ← endpoint 핸들러 실행
    finally:
        current_tenant_id.reset(token)
        db.close()                        # ← 트랜잭션 자동 rollback (commit 안 했으면)

# Endpoint 안
@router.post("/...")
async def create_reservation(db: Session = Depends(get_tenant_scoped_db)):
    db.add(...)
    db.commit()                           # ← 명시 commit
    return ...
```

**트랜잭션 경계**: dependency 진입 ~ endpoint 종료. autocommit=False, autoflush=False.

**옵션 C 후**:
```python
async def get_tenant_scoped_db(...):
    db = session_for_tenant(tenant_id)   # session.info 에 tenant 박힘
    try:
        yield db
    finally:
        db.close()
```

ContextVar set/reset 제거. 동작 동일.

### 패턴 B: 스케줄러 잡 (jobs.py)

```python
def _for_each_tenant(job_fn):
    bypass=True 로 tenants 조회
    for tenant in tenants:
        token = current_tenant_id.set(tenant.id)
        db = SessionLocal()
        try:
            job_fn(db, tenant)            # ← 잡 본체 (commit 자체 책임)
        finally:
            db.close()
            current_tenant_id.reset(token)
```

**트랜잭션 경계**: per-tenant SessionLocal() ~ 잡 종료. job_fn 안에서 명시 commit.

**옵션 C 후**: ContextVar 제거 + `session_for_tenant(tenant.id)`.

### 패턴 C: 스케줄러 동적 잡 (schedule_manager.py)

```python
async def execute_job():
    # Phase 1: bypass session — schedule 메타 fetch
    bypass_token = bypass_tenant_filter.set(True)
    db_session = SessionLocal()
    try:
        fresh_schedule = db_session.query(TemplateSchedule)...
        schedule_tenant_id = fresh_schedule.tenant_id
    finally:
        db_session.close()
        bypass_tenant_filter.reset(bypass_token)

    # Phase 2: tenant session — 실제 실행
    token = current_tenant_id.set(schedule_tenant_id)
    db_session = SessionLocal()
    try:
        executor = TemplateScheduleExecutor(db_session, tenant=tenant)
        await executor.execute_schedule(schedule)  # ← 본체 (내부 commit)
    finally:
        db_session.close()
        current_tenant_id.reset(token)
```

**트랜잭션 경계**: 두 개의 분리된 트랜잭션. Phase 1 (read-only bypass) + Phase 2 (tenant 실행).

**옵션 C 후**:
```python
async def execute_job():
    # Phase 1
    with session_bypass() as bypass_db:
        schedule = bypass_db.query(...).filter(id=schedule_id).first()
        schedule_tenant_id = schedule.tenant_id

    # Phase 2
    with session_for_tenant(schedule_tenant_id) as db:
        executor = TemplateScheduleExecutor(db, tenant=tenant)
        await executor.execute_schedule(schedule)
```

ContextManager 사용으로 close 보장 + ContextVar 제거.

### 패턴 D: 백그라운드 task (event_sms_hook.py)

```python
async def _run_event_hook(ids: List[int], tenant_id: int):
    token = current_tenant_id.set(tenant_id)
    db = SessionLocal()
    try:
        # ... 작업
        db.commit()
    finally:
        db.close()
        current_tenant_id.reset(token)
```

**옵션 C 후**: 동일 패턴, session_for_tenant 사용.

### 패턴 E: SSE long-lived (events.py:73-99)

```python
async def event_stream(...):
    db = SessionLocal()
    ...
    async def generator():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            db.close()
    return StreamingResponse(generator(), ...)
```

**트랜잭션 경계**: 매우 long-lived (SSE 연결 유지 동안). connection pool 점유.

**옵션 C 후 위험**:
- session 이 분~시간 동안 살아있음
- 옵션 C 후엔 session 이 tenant 컨텍스트 자체라 OK
- 단, pool_size=5 + max_overflow=10 환경에서 SSE 동시 접속 시 풀 고갈 가능 (현재도 같음)

→ **별도 audit 필요** (실제 SSE 가 db 를 어떻게 사용하는지 정밀 확인).

## 트랜잭션 commit 분포 (파일별)

| 파일 | commit 수 | 카테고리 |
|--|--|--|
| `api/reservations.py` | 다수 | API endpoint |
| `api/rooms.py` | 다수 | API endpoint |
| `api/templates.py` | 다수 | API endpoint |
| `api/template_schedules.py` | 다수 | API endpoint |
| `api/buildings.py` | 다수 | API endpoint |
| `api/auth.py` | 다수 | API endpoint |
| `api/event_sms.py` | 다수 | API endpoint |
| `api/onsite_auction.py` | 다수 | API endpoint |
| `api/onsite_sales.py` | 다수 | API endpoint |
| `api/daily_host.py` | 다수 | API endpoint |
| `api/party_checkin.py` | 다수 | API endpoint |
| `api/party_hosts.py` | 다수 | API endpoint |
| `api/settings.py` | 다수 | API endpoint |
| `scheduler/template_scheduler.py` | 여러개 | 스케줄러 잡 본체 |
| `scheduler/jobs.py` | 여러개 | 스케줄러 잡 본체 |
| `scheduler/schedule_manager.py` | 여러개 | 동적 잡 |
| `services/sms_sender.py` | 여러개 | SMS 발송 |
| `services/naver_sync.py` | 여러개 | naver sync 잡 |
| `db/database.py` | 일부 | init_db |
| `db/seed.py` | 일부 | seed |

## 위험 신호

### 🔴 [Critical] 옵션 C 후 close() 시점 ContextVar 정리는 자동
현재: db.close() 후 별도로 `current_tenant_id.reset(token)` 호출 필요.
옵션 C 후: db.close() 만 하면 끝 (session.info 는 자동 정리).

→ **트랜잭션 경계가 더 단순해지고 누수 위험 감소**.

### 🟠 [High] schedule_manager Phase 1 → Phase 2 두 트랜잭션
현재 두 ContextVar 조작 (bypass set/reset + tenant set/reset). 옵션 C 후 두 session factory 호출로 단순화.

### 🟠 [High] 같은 잡 안 여러 commit
`naver_sync.py` 가 tenant 1건 처리 도중 여러 commit. 도중 실패 시 일부만 commit 된 상태로 남을 수 있음. 옵션 C 와 무관한 기존 위험.

### 🟡 [Medium] async generator yield 후 트랜잭션 잔존
`get_tenant_scoped_db` yield 후 endpoint 가 long-running 이면 트랜잭션 길어짐. autoflush=False 라 의도적 commit 만. OK.

### 🟢 [Safe] begin_nested 미사용
SAVEPOINT 패턴 없음. 단순 commit/rollback 만. 옵션 C 와 무관.

## 옵션 C 후 트랜잭션 경계 변화

| 변화 | 영향 |
|--|--|
| db.close() 시점에 자동 tenant 정리 | 누수 위험 감소 ✅ |
| ContextVar reset 코드 제거 | 트랜잭션 정리 단순화 ✅ |
| session.info 가 트랜잭션 lifecycle 동안 유지 | tenant 정보 안정 ✅ |
| begin_nested savepoint 사용 시 동작 | 변화 없음 (사용 안 함) |
| nested session (드물지만 가능) | session.info 별도 — 분리 |

## 트랜잭션 충돌 시나리오

### 시나리오 A: 한 잡 안에서 두 session 사용 (schedule_manager)
- Phase 1 (bypass) session 과 Phase 2 (tenant) session 분리
- Phase 1 commit 후 Phase 2 진입 — 정상
- **옵션 C 후**: 각 session 이 독립 info — 충돌 없음

### 시나리오 B: 백그라운드 task 가 main task 의 session 공유
- 검색 결과: 그런 패턴 0건. 모두 새 SessionLocal() 호출.
- **옵션 C 후**: 각 task 가 새 session_for_tenant — 격리 자동.

### 시나리오 C: SSE event_stream 도중 publish 호출
- event_stream 의 db 와 publish 의 db 는 별개 (publish 는 db 인자 안 받음, in-memory queue 만 조작)
- **옵션 C 후**: 동일 — db 무관.

## Phase 별 변경 매핑

### Phase 1 (호환 shim)
- session_for_tenant / session_bypass factory 추가
- 기존 SessionLocal() 호출은 그대로 (legacy)
- before_flush/before_compile 가 session.info 우선

### Phase 2 (API)
- `get_tenant_scoped_db` 만 session_for_tenant 사용
- 200+ endpoint 자동 영향

### Phase 3 (스케줄러)
- `_for_each_tenant`, `execute_job`, sync 잡 6개 변환

### Phase 4 (service)
- 백그라운드 task 1곳 (`_run_event_hook`)
- service 함수 시그니처 점진 변경

### Phase 6 (cleanup)
- ContextVar 정의 + reset 코드 제거
