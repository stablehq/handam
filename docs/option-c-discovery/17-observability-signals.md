# Phase 0 산출물 #17: observability 강화 항목

> 옵션 C 마이그레이션 모니터링 전용 신호 + 기존 진단 강화

## 신규 진단 신호

### S1. tenant_context.mismatch (critical)
**발화 조건**: session.info['tenant_id'] 와 ContextVar.get() 의 값이 다름

**의미**: shim 의 fallback 분기에서 두 값이 충돌. 마이그레이션 중 silent 누수 의심.

**위치**: `db/tenant_context.py:_resolve_tenant_context`

```python
diag("tenant_context.mismatch", level="critical",
     session_tid=info_tid, ctx_tid=ctx_tid,
     stack_trace=traceback.format_stack(limit=5))
```

**기대 빈도**: Phase 1 후 0건. 발화 시 즉시 조사.

### S2. tenant_context.bypass_mismatch (warning)
**발화 조건**: session.info['bypass_tenant'] 와 ContextVar bypass_tenant_filter 다름

**의미**: shim fallback 충돌. 운영 작업 vs 스케줄러 작업 경계 흐려짐.

**위치**: 동일

```python
diag("tenant_context.bypass_mismatch", level="warning",
     session_bypass=info_bypass, ctx_bypass=ctx_bypass)
```

### S3. tenant_context.legacy_fallback (info)
**발화 조건**: session.info 가 비어 있어 ContextVar fallback 사용

**의미**: 옵션 C 미적용 코드 호출 위치 식별.

**위치**: `db/tenant_context.py:_resolve_tenant_context`

```python
diag("tenant_context.legacy_fallback", level="info",
     ctx_tid=ctx_tid, query_str=str(query)[:200])
```

**기대 빈도**: Phase 1~5 동안 점진 감소. Phase 6 진입 전 0건.

### S4. session_factory.created (verbose)
**발화 조건**: `session_for_tenant(tid)` 또는 `session_bypass()` 호출

**의미**: 신규 factory 사용 추적. Phase 진행률 측정.

**위치**: 새 `database.py:session_for_tenant`

```python
def session_for_tenant(tenant_id: int) -> Session:
    s = SessionLocal()
    s.info['tenant_id'] = tenant_id
    diag("session_factory.created", level="verbose",
         factory="session_for_tenant", tenant_id=tenant_id)
    return s
```

### S5. session_factory.usage_ratio (snapshot)
**측정**: 시간대별 신규 factory 사용 비율 vs legacy SessionLocal 사용 비율

**의미**: 마이그레이션 진행률 정량화

```python
# 매 시간 활동 로그에 기록
metric = {
    "new_factory_calls": ...,
    "legacy_sessionlocal_calls": ...,
    "ratio": new / (new + legacy),
}
log_activity(db, type="metric", title="session_factory_usage", detail=metric)
```

### S6. cross_tenant_leak.detected (critical)
**발화 조건**: chip / RoomAssignment / 기타 자식 row 의 tenant_id 가 부모와 다름

**의미**: 누수 발생 — 즉시 알람

**위치**: `db/tenant_context.py` 의 새 invariant 핸들러 (단계 1A)

```python
@event.listens_for(Session, "before_flush")
def detect_cross_tenant_leak(session, flush_context, instances):
    for obj in session.new:
        if hasattr(obj, 'tenant_id') and obj.tenant_id is not None:
            # FK 별 부모 tenant 검증
            ...
            if parent_tid != obj.tenant_id:
                diag("cross_tenant_leak.detected", level="critical",
                     model=type(obj).__name__,
                     child_tid=obj.tenant_id,
                     parent_model=...,
                     parent_tid=parent_tid)
```

### S7. session_lifecycle.long_lived (warning)
**발화 조건**: session 이 5분 이상 살아있음 (SSE 또는 lazy 잘못 사용 의심)

**의미**: connection pool 점유 또는 detached object 위험

**위치**: session factory 에 timestamp 기록 + 별도 watcher

```python
def session_for_tenant(tenant_id: int) -> Session:
    s = SessionLocal()
    s.info['tenant_id'] = tenant_id
    s.info['created_at'] = time.time()
    return s

# 주기적 watcher
def check_long_lived_sessions():
    # active sessions iterate
    for s in all_active_sessions:
        if time.time() - s.info['created_at'] > 300:
            diag("session_lifecycle.long_lived", level="warning",
                 tenant_id=s.info.get('tenant_id'),
                 age_seconds=...)
```

### S8. detached_instance.lazy_load (warning)
**발화 조건**: detached ORM 객체에 lazy attribute 접근 시도

**의미**: 코드 패턴 위험 — Phase 4 lazy-load audit 으로 식별 못한 사이트

```python
# SQLAlchemy 의 자동 발화 — DetachedInstanceError 캐치
@event.listens_for(Session, "after_attach")
def warn_on_late_attach(session, instance):
    if instance was_detached_recently:
        diag("detached_instance.lazy_load", level="warning",
             model=type(instance).__name__)
```

## 기존 진단 강화

### E1. auto_assign.enter — 이미 추가됨 (commit c930a7c)
```python
diag("auto_assign.enter", level="verbose",
     bypass_active=bypass_tenant_filter.get(),
     tenant_ctx=current_tenant_id.get())
```

옵션 C 후 변경:
```python
diag("auto_assign.enter", level="verbose",
     session_tid=db.info.get('tenant_id'),
     session_bypass=db.info.get('bypass_tenant'),
     ctx_tid=current_tenant_id.get(),  # legacy 비교용
     ctx_bypass=bypass_tenant_filter.get())
```

### E2. schedule.execute.fetch_miss — 이미 있음
옵션 C 후엔 발화 빈도 0 기대. 발화 시 root cause 인 ContextVar 누수 잔존 의심.

### E3. sms.sent_recorded — 이미 있음
옵션 C 후 추가 필드:
```python
diag("sms.sent_recorded", level="verbose",
     ...,
     session_tid=db.info.get('tenant_id'))
```

## 모니터링 대시보드 항목

### Critical 알람 (즉시 통지)
| 신호 | 임계 | 액션 |
|--|--|--|
| `tenant_context.mismatch` | 1건 이상 | 즉시 조사 + 롤백 |
| `cross_tenant_leak.detected` | 1건 이상 | 즉시 알람 + 롤백 |
| `schedule.execute.fetch_miss` | 1건 이상 | 즉시 조사 |

### Warning (관찰)
| 신호 | 임계 | 액션 |
|--|--|--|
| `tenant_context.bypass_mismatch` | 시간당 5건+ | 다음 day 분석 |
| `tenant_context.legacy_fallback` | Phase 4 후 발화 | grep 으로 누락 코드 식별 |
| `session_lifecycle.long_lived` | 시간당 1건+ | SSE / lazy load 검토 |
| `detached_instance.lazy_load` | 시간당 1건+ | endpoint 식별 + eager load |

### Info (추적)
| 신호 | 의미 | 사용 |
|--|--|--|
| `session_factory.created` | 신규 factory 호출 | 마이그레이션 진행률 |
| `session_factory.usage_ratio` | 비율 메트릭 | 대시보드 시각화 |

## 추가 SQL 모니터링 쿼리

### 매일 자동 실행
```sql
-- cross-tenant 누수 검증 (0건 기대)
SELECT COUNT(*) AS pattern_a FROM reservation_sms_assignments rsa
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id != ts.tenant_id;

SELECT COUNT(*) AS pattern_b FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id;

-- 잡 발화 빈도 (baseline 비교)
SELECT type, title, COUNT(*) FROM activity_logs
WHERE created_at >= CURRENT_DATE
GROUP BY type, title;
```

결과를 daily report 로 운영자에게 전송.

## diag log 파싱 자동화

```bash
#!/bin/bash
# scripts/check_critical_diag.sh
# 매 시간 cron 으로 실행

LOG=backend/logs/refactor-diag.log
LAST_HOUR=$(date -d '1 hour ago' +"%Y-%m-%d %H")

# critical 신호 카운트
MISMATCH=$(grep "$LAST_HOUR" $LOG | grep "tenant_context.mismatch" | wc -l)
LEAK=$(grep "$LAST_HOUR" $LOG | grep "cross_tenant_leak.detected" | wc -l)
FETCH_MISS=$(grep "$LAST_HOUR" $LOG | grep "schedule.execute.fetch_miss" | wc -l)

if [ $MISMATCH -gt 0 ] || [ $LEAK -gt 0 ] || [ $FETCH_MISS -gt 0 ]; then
    # 운영자에게 즉시 알람 (Slack webhook 등)
    curl -X POST $SLACK_WEBHOOK ...
fi
```

## 모니터링 인프라 변경 (필요 시)

현재 diag log 가 파일 기반 (`refactor-diag.log`). Phase 5 까지 충분.

대규모 운영 환경이면:
- Sentry / Datadog 통합
- Prometheus metrics
- Grafana 대시보드

현재 규모 (2 tenant) 에선 file-based + 일일 SQL 검증으로 충분.

## 결론

**핵심 신호 8개** 추가 (S1~S8) + 기존 진단 강화. 운영 인프라 변경 없이 file-based 진단 강화로 마이그레이션 모니터링 충분.

각 Phase 진입 시 모니터링 대시보드의 임계 알람 활성 후 시작. 임계 위반 시 즉시 롤백.
