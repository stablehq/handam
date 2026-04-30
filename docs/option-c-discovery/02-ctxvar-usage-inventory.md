# Phase 0 산출물 #2: ContextVar 사용처 분류 인벤토리

> 옵션 C 전환 시 모든 ContextVar 호출이 (a) session 인자/info, (b) 함수 인자 명시, (c) 제거 — 셋 중 하나로 변환.

## current_tenant_id 사용 (50건)

### 카테고리 A: set/reset 페어 (마이그레이션 시 session 생성 + close 로 대체)

| 파일:라인 | 컨텍스트 | tenant 값 출처 | 옵션 C 후 |
|--|--|--|--|
| `api/deps.py:109/120` | `get_tenant_scoped_db` | 헤더 X-Tenant-Id | `session_for_tenant(tid)` |
| `scheduler/schedule_manager.py:152/164` | `execute_job` Phase 2 | `schedule.tenant_id` | `session_for_tenant(schedule.tenant_id)` |
| `scheduler/jobs.py:34/50` | `_for_each_tenant` 루프 | 루프 변수 | `session_for_tenant(tenant.id)` |
| `scheduler/jobs.py:86/104` | `sync_naver_reservations_job` 루프 | 루프 변수 | `session_for_tenant(tenant.id)` |
| `scheduler/jobs.py:232/292` | `reconcile_today_reservations_job` 루프 | 루프 변수 | `session_for_tenant(tenant.id)` |
| `scheduler/jobs.py:323/357` | `sync_unstable_reservations_job` 루프 | 루프 변수 | `session_for_tenant(tenant.id)` |
| `services/event_sms_hook.py:83/166` | `_run_event_hook` 백그라운드 | 인자 `tenant_id` | `session_for_tenant(tenant_id)` |

### 카테고리 B: get() 읽기 (마이그레이션 시 session.info 또는 인자 추가)

#### B-1. API endpoint 안 (4 파일, 9곳)
| 파일:라인 | 함수 | 옵션 C 후 |
|--|--|--|
| `api/templates.py:142` | `list_templates` 등 | `tid = db.info['tenant_id']` |
| `api/reservations.py:627` | delete reservation | 동일 |
| `api/reservations.py:1269` | cancel extend stay | 동일 |
| `api/reservations.py:1330` | extend stay assign | 동일 |
| `api/reservations.py:1394` | extend_stay_assign_room | 동일 |
| `api/rooms.py:310` | room CRUD | 동일 |
| `api/rooms.py:380` | reorder | 동일 |
| `api/rooms.py:413` | building 관리 | 동일 |
| `api/rooms.py:444` | toggle is_active | 동일 |

#### B-2. service 안 (8 파일, 15곳)
| 파일:라인 | 함수 | 옵션 C 후 |
|--|--|--|
| `services/consecutive_stay.py:60, 231` | detect_and_link / 기타 | 인자 추가 또는 `session.info` |
| `services/activity_logger.py:11` | log_activity | 인자 추가 (`tenant_id` 명시) |
| `services/naver_sync.py:320, 709` | chip reconcile / 기타 | session.info |
| `services/surcharge.py:185` | surcharge | session.info 또는 인자 |
| `services/room_auto_assign.py:47, 87, 158, 193` | 다수 | session.info |
| `services/party3_mms.py:103, 182` | MMS | 인자 추가 |
| `services/room_assignment.py:515, 665, 712, 810, 883` | 5곳 | session.info 또는 인자 |
| `templates/variables.py:285` | tenant_id 결정 | 인자 추가 |

#### B-3. scheduler 안 (1곳)
| 파일:라인 | 옵션 C 후 |
|--|--|
| `scheduler/template_scheduler.py:290` | `tenant_id=schedule.tenant_id` 직접 사용 (이미 schedule 객체 가짐) |

#### B-4. diag/log 만 사용 (1곳)
| 파일:라인 | 옵션 C 후 |
|--|--|
| `diag_logger.py:146` | session 안의 tid 가 있으면 사용, 없으면 None — diag 만의 fallback |

### 카테고리 C: 정의/이벤트 핸들러
| 파일:라인 | 역할 | 옵션 C 후 |
|--|--|--|
| `db/tenant_context.py:12` | ContextVar 정의 | Phase 6 에서 제거 |
| `db/tenant_context.py:23` | before_flush 핸들러 (auto-inject) | session.info 우선, ContextVar fallback (Phase 6 후 ContextVar 분기 제거) |
| `db/tenant_context.py:63` | before_compile 핸들러 (auto-filter) | 동일 |

## bypass_tenant_filter 사용 (28건)

### 카테고리 A: set(True)/reset 페어 (마이그레이션 시 `session_bypass()` 로 대체)

| 파일:라인 | 컨텍스트 | 옵션 C 후 |
|--|--|--|
| `db/database.py:57/413` | `init_db` | `session_bypass()` |
| `scheduler/jobs.py:25/29` | `_for_each_tenant` 부트스트랩 | `session_bypass()` for tenants 조회 |
| `scheduler/jobs.py:75/83` | `sync_naver_reservations_job` 부트스트랩 | 동일 |
| `scheduler/jobs.py:116/131` | `load_template_schedules` startup | 동일 |
| `scheduler/jobs.py:221/229` | `reconcile_today_reservations_job` | 동일 |
| `scheduler/jobs.py:305/313` | `sync_unstable_reservations_job` | 동일 |
| `scheduler/schedule_manager.py:92/149` | `execute_job` Phase 1 (schedule 메타 fetch) | `session_bypass()` |
| `services/sms_tracking.py:20/28` | `_resolve_reservation_tenant` | **삭제** — session.info 에 이미 tenant 있음 |

### 카테고리 B: get() 읽기 (진단용)
| 파일:라인 | 옵션 C 후 |
|--|--|
| `scheduler/schedule_manager.py:104` | diag log "bypass_active" — `db.info.get('bypass_tenant', False)` 로 |
| `services/room_auto_assign.py:46` | 동일 |
| `db/tenant_context.py:60` | before_compile fallback — Phase 6 후 제거 |

### 카테고리 C: 정의
| 파일:라인 | 옵션 C 후 |
|--|--|
| `db/tenant_context.py:15` | ContextVar 정의 | Phase 6 에서 제거 |

## 호출 체인 (변경 전파 시 영향 큰 함수)

### `log_activity` (activity_logger.py)
- 호출자: 30+ 곳 (모든 활동 로그)
- ContextVar 의존: tenant_id 자동 주입
- 옵션 C 변경: 인자 `tenant_id: int` 추가 → 모든 호출자 시그니처 변경 필요. **대안**: session 인자만 추가하고 내부에서 `session.info['tenant_id']` 읽기 — 호출자 변경 최소

### `event_bus.publish` (event_bus.py — 별도 audit 필요)
- 호출자: SSE 발행처 다수
- 옵션 C 변경: tenant_id 인자 명시 또는 session.info 읽기

### `consecutive_stay.detect_and_link_consecutive_stays`
- ContextVar 읽기 2곳 (60, 231)
- 옵션 C 변경: 이미 `tenant_id` 인자 받는 패턴 일부 있음 — 통일

## 위험 신호

### 🟠 [High] consecutive_stay.py:60 — 인자 fallback 패턴
```python
tid = tenant_id or current_tenant_id.get()
```
이미 인자 우선 + ContextVar fallback. 옵션 C 후 ContextVar 제거 시 인자 필수로. 모든 호출자 검사 필요.

### 🟠 [High] templates/variables.py:285 — 자동 fallback 없음
ContextVar 만 의존. 호출자가 tenant_id 안 받음. 옵션 C 후 시그니처 변경 필수.

### 🟡 [Medium] diag_logger.py:146 — 진단 전용
가장 marginal 한 케이스. tenant_id 가 None 일 때도 diag 가 동작해야 함. fallback `None` 안전.

### 🟢 [Low] template_scheduler.py:290 — 이미 schedule.tenant_id 가짐
`schedule.tenant_id` 직접 사용으로 변경 단순.

## 마이그레이션 순서 (Phase 4 작업 순서)

1. **Phase 4-1**: ContextVar 정의 + before_flush/before_compile 핸들러를 session.info 우선 + ContextVar fallback 으로 변경 (호환 shim)
2. **Phase 4-2**: 카테고리 B 의 service / API endpoint 9곳 (B-1) → `session.info['tenant_id']` 읽기
3. **Phase 4-3**: 카테고리 B 의 service 15곳 (B-2) → 인자 추가 또는 session.info
4. **Phase 4-4**: 카테고리 A 의 set/reset 페어 → session factory 호출로 대체
5. **Phase 4-5**: bypass.set(True) 페어 → `session_bypass()` 로 대체
6. **Phase 6**: ContextVar 정의 + fallback 분기 제거
