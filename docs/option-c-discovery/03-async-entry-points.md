# Phase 0 산출물 #3: 비동기/스케줄러 진입점 인벤토리

> 옵션 C 의 핵심: 모든 진입점에서 session_for_tenant() / session_bypass() 명시 호출. 진입점 누락 = 누수 잠재.

## APScheduler 정적 잡 (jobs.py:setup_scheduler 안 — 12개 add_job)

| 잡 ID | 함수 | trigger | tenant 결정 | 잡 진입 시점 SessionLocal? |
|--|--|--|--|--|
| `sync_naver_reservations` | `sync_naver_reservations_job` | every 5min interval | `_for_each_tenant` 패턴 (per-tenant 루프) | bootstrap session_bypass + per-tenant session_for_tenant |
| `daily_room_assign` | `daily_room_assign_job` | daily 10:00 KST | `_for_each_tenant` | 동일 |
| `daily_status_log` | `_log_status_job` (래퍼) | every 6h (00,06,12,18) | `_for_each_tenant` | 동일 |
| `consecutive_stay_detect` | `_detect_consecutive_stays_job` | every 1h | `_for_each_tenant` | 동일 |
| `participant_snapshot_morning` | `refresh_snapshots_job` | cron 08:50 | `_for_each_tenant` | 동일 |
| `refresh_snapshots_morning_late` | `refresh_snapshots_job` | cron 09:50 | 동일 | 동일 |
| `participant_snapshot_noon` | `refresh_snapshots_job` | cron 11:50 | 동일 | 동일 |
| `refresh_snapshots_night` | `refresh_snapshots_job` | cron 22:50 | 동일 | 동일 |
| `template_schedules_load` | template_schedules.load | startup once | bypass | session_bypass |
| `reconcile_today_reservations` | `reconcile_today_reservations_job` | cron 09:55 | 직접 for-loop | 동일 |
| `sync_unstable_reservations` | `sync_unstable_reservations_job` | every 6h | 직접 for-loop | 동일 |
| `compute_gender_stats` | `_assign_job` 래퍼 | daily | `_for_each_tenant` | 동일 |

## APScheduler 동적 잡 (schedule_manager.py:168 add_job)

| 잡 ID 패턴 | 함수 | tenant 결정 | 호출 시점 |
|--|--|--|--|
| `template_schedule_{schedule_id}` | `execute_job` (closure) | Phase 1: bypass session 으로 schedule fetch → schedule.tenant_id | 매 schedule 마다 동적 등록 |

**핵심 위험 지점**: `execute_job` 의 Phase 1 (bypass) → Phase 2 (tenant) 전환이 ContextVar 누수 root cause.

## 외부 API 트리거 (api/scheduler.py:108)

| 위치 | 함수 | 잡 종류 |
|--|--|--|
| `api/scheduler.py:108` | manual trigger 엔드포인트 | API 호출자 컨텍스트 (current_tenant_id 설정됨) |

## asyncio.create_task (1개)

| 위치 | 함수 | tenant 결정 |
|--|--|--|
| `services/event_sms_hook.py:52` | `loop.create_task(_run_event_hook(ids, tenant_id))` | 인자 명시 ✅ |

→ 명시 인자 전달 패턴. 옵션 C 후엔 추가로 `_run_event_hook` 가 `session_for_tenant(tenant_id)` 사용.

## `_for_each_tenant` 호출 (4개)

```python
# jobs.py:21 정의
def _for_each_tenant(job_fn):
    bypass=True 로 tenants 조회 →
    for tenant in tenants:
        current_tenant_id.set(tenant.id)  # ← 옵션 C 에서 제거
        db = SessionLocal()                # ← session_for_tenant(tenant.id) 로 변경
        try:
            job_fn(db, tenant)
        finally:
            db.close()
            current_tenant_id.reset(token)  # ← 제거
```

호출자 4곳:
- `_log_status_job` (jobs.py:159)
- `_detect_consecutive_stays_job` (jobs.py:194)
- `daily_room_assign_job` (jobs.py:379)
- `_assign_job` (gender_stats) (jobs.py:405)

→ `_for_each_tenant` 함수 자체를 옵션 C 화 하면 4 잡 모두 자동 보호.

## 직접 `for tenant in tenants` 루프 (4개)

| 위치 | 잡 함수 | session 생성 | 옵션 C 변경 |
|--|--|--|--|
| `jobs.py:33` | `_for_each_tenant` 본체 | per-tenant SessionLocal | 위와 같음 |
| `jobs.py:85` | `sync_naver_reservations_job` | per-tenant | session_for_tenant 적용 |
| `jobs.py:231` | `reconcile_today_reservations_job` | per-tenant | 동일 |
| `jobs.py:319` | `sync_unstable_reservations_job` | per-tenant | 동일 |

## 위험 신호

### 🔴 [Critical] APScheduler `AsyncIOExecutor` ContextVar 격리 부재
```
backend/venv/.../apscheduler/executors/asyncio.py:46
    f = self._eventloop.create_task(coro)  # context= 인자 없음
```
**옵션 C 의 본질적 가치는 이 문제를 우회**. session 자체가 tenant 정보를 들고 있으므로 ContextVar 누수 영향 받지 않음.

### 🟠 [High] `execute_job` 의 Phase 1 → Phase 2 전환
현재: `bypass=True` set → `bypass.reset` → `current_tenant_id.set` → `current_tenant_id.reset`. 4번 ContextVar 조작. 옵션 C 후엔:
```python
async def execute_job():
    # Phase 1: bypass session
    with session_bypass() as bypass_db:
        schedule = bypass_db.query(TemplateSchedule).filter(id=schedule_id).first()
        schedule_tenant_id = schedule.tenant_id

    # Phase 2: tenant session
    with session_for_tenant(schedule_tenant_id) as db:
        executor = TemplateScheduleExecutor(db, tenant=tenant)
        await executor.execute_schedule(schedule)
```

### 🟠 [High] `event_sms_hook.py:52` create_task 가 tenant_id 인자 받지만 내부에서 ContextVar set
```python
task = loop.create_task(_run_event_hook(ids, tenant_id))
```
인자로 tenant 받는데 `_run_event_hook` 안에서 다시 `current_tenant_id.set(tenant_id)` 함. 옵션 C 후엔 set 제거하고 `session_for_tenant(tenant_id)` 만 사용.

### 🟢 [Low] FastAPI 요청은 starlette 이 task 격리
각 요청이 별도 task. 옵션 C 후엔 session 자체가 tenant 들고 있어 격리 강화. 추가 작업 없음.

## Phase 별 변경 매핑

### Phase 3 변경 대상 (스케줄러)
1. `_for_each_tenant` 자체를 session 기반으로 재작성 (1곳)
2. `sync_naver_reservations_job` 의 직접 for-loop (1곳)
3. `reconcile_today_reservations_job` 직접 for-loop (1곳)
4. `sync_unstable_reservations_job` 직접 for-loop (1곳)
5. `execute_job` (schedule_manager.py:88) Phase 1+2 (1곳)
6. `_run_event_hook` (event_sms_hook.py:83) (1곳)

→ 총 6 진입점 변경. 각각 독립적으로 마이그레이션 가능.

### Phase 2 변경 대상 (API)
1. `get_tenant_scoped_db` (deps.py:95) 1곳
2. SSE `/events` 엔드포인트 (events.py:49) 1곳

→ 총 2 진입점.

### Phase 1 (호환 shim) — 진입점 변경 0
새 `session_for_tenant` / `session_bypass` factory 만 추가. 진입점들은 Phase 2~3 에서 점진 전환.

## 검증 시나리오 (Phase 3 후)

각 진입점별 통합 테스트 필요:
- 정상 잡 발화 → 1 tenant 로 격리 확인
- bypass 잡 → 모든 tenant row 보임
- cross-tenant SMS 시도 시뮬레이션 → 차단 확인
