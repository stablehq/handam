# Phase 0 산출물 #13: 동시성 / race condition 시나리오

> 옵션 C 가 ContextVar 누수를 차단하지만 다른 동시성 위험 잔존 여부 검증.

## 동시성 인프라 현황

| 항목 | 발견 | 영향 |
|--|--|--|
| APScheduler max_instances 명시 | **0건** (default=1) | 동일 잡 동시 실행 불가 — 안전 |
| asyncio.Semaphore | 1곳 (`real/reservation.py:198`, naver API 동시성 10) | 외부 API 호출 제한 — 옵션 C 무관 |
| asyncio.gather | 1곳 (위와 같은 위치) | 동일 |
| SELECT FOR UPDATE | 4곳 (room_assignment / onsite_auction / daily_host) | 동일 row 동시 수정 락 |
| BackgroundTasks | 0건 | FastAPI BackgroundTasks 미사용 |
| In-memory cache | 1곳 (event_bus._queues) | 격리됨 (tenant_id 키) |

## 시나리오 분석

### S1. APScheduler 잡 misfire / overlap
**현재**: max_instances 명시 안 함 → 기본 1. 같은 잡이 이전 실행이 안 끝났는데 다음 트리거 시 — 새 트리거 무시됨 (misfire warning).

**옵션 C 후**: 변화 없음. 잡당 단일 실행이라 동시성 race 없음.

**위험**: 🟢 안전.

### S2. 다른 잡끼리 동시 실행 (event loop 안)
**현재**: 한 이벤트 루프에서 잡 A 가 await 동안 잡 B 트리거 → 둘이 인터리브 실행. ContextVar 누수 발생 (이번 사고 root cause).

**옵션 C 후**: 잡마다 새 session 생성 + session.info 에 tenant 박힘. ContextVar 미사용 → 인터리브해도 누수 0.

**위험**: 🟢 안전 (옵션 C 의 핵심 가치).

### S3. 같은 잡이 여러 tenant loop 도중 다른 잡 트리거
예: `sync_naver_reservations_job` 가 tenant 1 → tenant 2 순회 중간에 schedule 1 (HANDAM) 트리거.

**현재**: ContextVar 잔재로 누수 (이번 사고).

**옵션 C 후**: 각 잡이 자체 session 으로 격리. tenant 2 sync 진행 중 schedule 1 잡이 시작해도 — schedule 1 의 새 session 은 schedule.tenant_id=1 로 명시 박힘. 누수 0.

**위험**: 🟢 안전.

### S4. SELECT FOR UPDATE + 동시 트랜잭션
**위치**:
- `room_assignment.py:278` (방 배정 — 일반실 충돌 방지)
- `room_assignment.py:958` (X3 충돌 체크)
- `api/onsite_auction.py:63` (현장 옥션 락)
- `api/daily_host.py:55` (일별 호스트 락)

**현재**: 같은 row 두 트랜잭션이 동시 접근 시 — 한쪽 락 얻고, 다른쪽 대기 → 정상.

**옵션 C 후**: 변화 없음. session 격리는 row 락과 별개.

**위험**: 🟢 안전.

### S5. asyncio.Semaphore 동시 외부 API 호출
**위치**: `real/reservation.py:198` — naver user_info fetch 10 동시.

**현재**: 동일 tenant 컨텍스트 안에서 10 task 동시 실행. ContextVar 가 task 간 자동 inherit 되어 모두 같은 tenant.

**옵션 C 후**: tenant 가 호출자 인자로 명시되거나 외부 API 라 tenant 무관. 영향 없음.

**위험**: 🟢 안전.

### S6. async generator cancel (FastAPI request 도중 취소)
**위치**: `get_tenant_scoped_db` (deps.py:95)

**현재**: yield 후 finally 블록이 실행되어 reset/close 보장. asyncio task cancel 시에도 finally 실행됨.

**옵션 C 후**: 동일 — finally 에서 db.close() 만. ContextVar reset 없으므로 더 단순.

**위험**: 🟢 안전.

### S7. SSE event_stream 중간 disconnect
**위치**: `events.py:99`

**현재**: client disconnect 시 generator GC + finally 에서 db.close() 호출. unsubscribe 도 호출됨 (q 해제).

**옵션 C 후**: 동일.

**위험**: 🟡 medium — long-lived connection 이라 db.close() 가 늦게 호출되면 connection pool 점유. 별도 검증.

### S8. 같은 session 을 여러 task 가 공유
**위치**: 검색 결과 0건. 모든 task 가 자체 SessionLocal() 사용.

**옵션 C 후**: 동일.

**위험**: 🟢 안전.

### S9. 동일 트랜잭션 안 두 번 commit
**검색**: `naver_sync.py` 등 여러 곳에서 한 함수 안 여러 commit. 트랜잭션 분리 의도.

**옵션 C 후**: 변화 없음. session 인터페이스 동일.

**위험**: 🟢 안전.

### S10. background task 가 외부 ORM 객체 받음
**검색**: 0건 (event_sms_hook 만 ID 받음).

**위험**: 🟢 안전.

## 잠재 새 위험 (옵션 C 도입으로)

### N1. session.info 가 task 간 inherit 되지 않음
ContextVar 는 asyncio task 가 자동 inherit. session.info 는 객체 attribute라 inherit 무관 — task 가 같은 session 객체 공유하면 같은 info 읽음.

**그런 시나리오 있나?**: 검색 결과 task 간 session 공유 0건. 안전.

### N2. 같은 session 에 여러 tenant 전환
가능: `session.info['tenant_id'] = 1` → 작업 → `session.info['tenant_id'] = 2` → 작업.

**현재 그런 패턴?**: 없음. 단, 옵션 C 후 도입 가능. **policy 명문화 필요**: "session.info['tenant_id'] 는 immutable. 다른 tenant 면 새 session 만들어야 함."

### N3. session.info 직렬화 / 다른 프로세스 전달
session 객체 자체가 multi-process 전달 안 됨 (SQLAlchemy session 은 thread-local). 안전.

## 위험 점수

| 시나리오 | 현재 위험도 | 옵션 C 후 |
|--|--|--|
| APScheduler misfire | 🟢 | 🟢 |
| 잡 인터리브 ContextVar 누수 | 🔴 (이번 사고) | 🟢 (해결) |
| Cross-tenant ContextVar 누수 | 🔴 | 🟢 |
| SELECT FOR UPDATE 락 | 🟢 | 🟢 |
| async generator cancel | 🟢 | 🟢 |
| SSE long-lived | 🟡 | 🟡 (변화 없음) |
| session 간 task 공유 | 🟢 (없음) | 🟢 |
| 동일 session tenant 전환 | 🟢 (없음) | 🟡 (policy 필요) |

## 권장 정책

### P1. session.info['tenant_id'] immutable
```python
# 안 되는 패턴
db.info['tenant_id'] = 1
# ... 작업 ...
db.info['tenant_id'] = 2  # ❌ 금지
# ... 작업 ...

# 권장
db1 = session_for_tenant(1)
# 작업
db1.close()
db2 = session_for_tenant(2)
# 작업
db2.close()
```

session factory 가 info 박은 후 setter 막거나, 변경 시 critical diag 발화.

### P2. session 종료 시점 명확
모든 session 사용은 try/finally 또는 with-statement 으로 close 보장. 현재 거의 모든 호출이 그러함.

### P3. async generator 취소 시 cleanup 보장
finally 블록에 db.close() — 현재도 정상. 옵션 C 후에도 동일.

### P4. SSE event_stream long-lived 검증
SSE 의 db 사용 패턴 정밀 확인 후 별도 산출물.

## Phase 별 변경 매핑

### Phase 1
- session factory 가 info immutable 하도록 설계 (`session.info['tenant_id'] = X` 만 허용, 재설정 금지)

### Phase 3
- 스케줄러 잡 변환 시 동시성 정책 (P1) 자동 보장 (각 잡이 새 session)

### Phase 4
- service 함수 시그니처 변경 시 P1 정책 코드로 강제 (예: tenant 인자 변경 감지 시 새 session 요구)

## 결론

**옵션 C 는 동시성 클래스의 ContextVar 누수를 차단**하고 다른 동시성 메커니즘 (락, semaphore) 에는 영향 없음. 새 위험 N1~N3 는 모두 운용 정책 P1~P4 로 차단 가능.

옵션 C 후 동시성 안전도 **현재보다 개선** (특히 잡 인터리브 누수가 차단됨).
