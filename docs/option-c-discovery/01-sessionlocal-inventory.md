# Phase 0 산출물 #1: SessionLocal() 호출 사이트 인벤토리

> 옵션 C 전환 시 모든 호출이 `session_for_tenant(tid)` 또는 `session_bypass()` 로 전환되어야 함.

## 호출 사이트 전수 (16개)

| # | 파일:라인 | 카테고리 | tenant 결정 | finally close? | async/sync | 옵션 C 전환 패턴 |
|--|--|--|--|--|--|--|
| 1 | `db/database.py:30` | **factory 정의** | - | - | - | sessionmaker 정의. 새 factory 추가 |
| 2 | `db/database.py:35` | dependency `get_db` | 호출자 결정 | ✅ try/finally | sync (FastAPI dep) | **bypass 또는 명시 인자**로 전환. 이 함수 자체는 legacy 호환용으로 유지하거나 deprecate |
| 3 | `db/database.py:384` | `init_db` startup | 전역 (bypass) | ✅ try/finally | sync | `session_bypass()` 사용 |
| 4 | `db/seed.py:54` | seed 스크립트 | 전역 (bypass) | 부분 (try/except) | sync | `session_bypass()` 사용 |
| 5 | `api/deps.py:111` | dependency `get_tenant_scoped_db` | 헤더 X-Tenant-Id | ✅ try/finally | async generator | **`session_for_tenant(tid)` 핵심 진입점** |
| 6 | `api/events.py:49` | SSE long-lived | 헤더 X-Tenant-Id | ✅ try/finally | async generator | `session_for_tenant(tid)` |
| 7 | `scheduler/jobs.py:23` | `_for_each_tenant` 부트스트랩 (tenants 목록) | 전역 (bypass) | ✅ try/finally | sync | `session_bypass()` |
| 8 | `scheduler/jobs.py:35` | `_for_each_tenant` per-tenant | 루프 변수 `tenant.id` | ✅ try/finally | sync | `session_for_tenant(tenant.id)` |
| 9 | `scheduler/jobs.py:77` | `sync_naver_reservations_job` 부트스트랩 | 전역 (bypass) | ✅ try/finally | async | `session_bypass()` |
| 10 | `scheduler/jobs.py:87` | `sync_naver_reservations_job` per-tenant | 루프 변수 | ✅ try/finally | async | `session_for_tenant(tenant.id)` |
| 11 | `scheduler/jobs.py:118` | `load_template_schedules` startup | 전역 (bypass) | ✅ try/finally | sync | `session_bypass()` |
| 12 | `scheduler/jobs.py:223` | `reconcile_today_reservations_job` 부트스트랩 | 전역 (bypass) | ✅ try/finally | async | `session_bypass()` |
| 13 | `scheduler/jobs.py:233` | `reconcile_today_reservations_job` per-tenant | 루프 변수 | ✅ try/finally | async | `session_for_tenant(tenant.id)` |
| 14 | `scheduler/jobs.py:307` | `sync_unstable_reservations_job` 부트스트랩 | 전역 (bypass) | ✅ try/finally | async | `session_bypass()` |
| 15 | `scheduler/jobs.py:324` | `sync_unstable_reservations_job` per-tenant | 루프 변수 | ✅ try/finally | async | `session_for_tenant(tenant.id)` |
| 16 | `scheduler/schedule_manager.py:93` | `execute_job` Phase 1 (bypass session) | 전역 (bypass) | ✅ try/finally | async | `session_bypass()` |
| 17 | `scheduler/schedule_manager.py:153` | `execute_job` Phase 2 (tenant session) | `schedule.tenant_id` | ✅ try/finally | async | `session_for_tenant(schedule_tenant_id)` |
| 18 | `services/event_sms_hook.py:84` | `_run_event_hook` 백그라운드 | 인자 `tenant_id` | ✅ try/finally | async | `session_for_tenant(tenant_id)` |

## 카테고리별 마이그레이션 패턴

### A. tenant context 가 명확한 호출 (대부분)
```python
# 지금
db = SessionLocal()
current_tenant_id.set(tenant_id)
# ... 작업 ...
db.close()

# 옵션 C 후
db = session_for_tenant(tenant_id)
# ... 작업 ...
db.close()
```

### B. 전역/cross-tenant 작업 (init_db, tenants 조회)
```python
# 지금
bypass_token = bypass_tenant_filter.set(True)
db = SessionLocal()
# ... 작업 ...
bypass_tenant_filter.reset(bypass_token)

# 옵션 C 후
db = session_bypass()
# ... 작업 ...
```

### C. FastAPI 의존성 (get_tenant_scoped_db)
```python
# 지금
async def get_tenant_scoped_db(...):
    token = current_tenant_id.set(tenant_id)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        current_tenant_id.reset(token)

# 옵션 C 후
async def get_tenant_scoped_db(...):
    db = session_for_tenant(tenant_id)
    try:
        yield db
    finally:
        db.close()
```

## 위험 신호

### 🟡 db/database.py:35 `get_db()` 미전환 시 위험
일부 endpoint 가 `get_db` 직접 사용 (tenant 격리 없음). 옵션 C 후엔 `session_bypass()` 가 적용되어 모든 row 노출. 이는 **현재도 같은 동작**이지만 옵션 C 가 명시적으로 만듬. `get_db` 사용처 별도 audit 필요 (산출물 #2 와 연계).

### 🟢 finally close 보장 우수
16개 호출 모두 try/finally 또는 with-style 으로 close 보장. 옵션 C 전환 후에도 누수 위험 낮음.

### 🟡 schedule_manager.py:93 + 153 두 번 SessionLocal()
같은 잡 안에서 Phase 1 (bypass) + Phase 2 (tenant) 로 두 세션 생성. 옵션 C 후엔 `session_bypass()` + `session_for_tenant()` 로 명확히 분리. 의도는 동일.

## 호출자 그래프 (key 함수만)

```
get_tenant_scoped_db (deps.py:95)
└── 200+ API endpoints (모든 tenant-scoped 라우트)

_for_each_tenant (jobs.py:21)
├── _log_status (jobs.py:159)
├── _detect (jobs.py:194) - consecutive_stay
├── _assign (jobs.py:379) - daily room assign
└── _job (jobs.py:405) - participant snapshots

sync_naver_reservations_job (jobs.py:69)
└── 직접 for tenant 루프

execute_job (schedule_manager.py:88)
└── TemplateScheduleExecutor.execute_schedule
    └── send_single_sms / record_sms_sent / etc.
```

## 다음 단계 (Phase 1 작업)

1. `db/database.py` 에 두 helper 추가:
   ```python
   def session_for_tenant(tenant_id: int) -> Session: ...
   def session_bypass() -> Session: ...
   ```
2. 위 18개 호출 사이트를 표 우측 컬럼대로 점진 전환
3. 각 전환 후 테스트 통과 확인
4. legacy `SessionLocal()` 직접 호출은 DeprecationWarning 으로 경고 (Phase 6 에서 정의 자체 제거)
