# Phase 0 산출물 #8: 호환 shim 설계 문서

> Phase 1~5 동안 ContextVar 와 Session 양쪽이 공존해야 함. 점진 도입을 위한 shim 설계.

## 핵심 원칙

1. **session.info 우선**: tenant 정보는 session.info 에서 먼저 읽음
2. **ContextVar fallback**: session.info 없으면 ContextVar 에서 읽음 (legacy 호환)
3. **불일치 감지**: 둘 다 있는데 값이 다르면 critical diag 로그 + session.info 우선
4. **Phase 6 cleanup**: 전체 마이그레이션 완료 후 ContextVar fallback 분기 제거

## 새 Session Factory

### `db/database.py` 추가

```python
from typing import Optional

def session_for_tenant(tenant_id: int) -> Session:
    """Tenant-scoped session.

    session.info['tenant_id'] = tenant_id 박힌 채로 반환.
    이후 모든 query/insert 가 자동으로 그 tenant 에 격리됨.
    """
    if tenant_id is None:
        raise ValueError("tenant_id must not be None")
    s = SessionLocal()
    s.info['tenant_id'] = tenant_id
    return s


def session_bypass() -> Session:
    """Cross-tenant 작업용 bypass session.

    session.info['bypass_tenant'] = True 박힌 채로 반환.
    auto-filter 가 우회됨. INIT/MIGRATION/SCHEDULER bootstrap 용.
    """
    s = SessionLocal()
    s.info['bypass_tenant'] = True
    return s


def session_unscoped() -> Session:
    """Tenant 가 None 인 일반 session (legacy `get_db` 호환용).

    주의: tenant 모델 query 시 RuntimeError 발생.
    """
    return SessionLocal()
```

## 수정된 before_compile / before_flush 핸들러

### `db/tenant_context.py` 변경 후

```python
# 기존 정의 (Phase 6 까지 유지)
current_tenant_id: ContextVar[Optional[int]] = ContextVar("current_tenant_id", default=None)
bypass_tenant_filter: ContextVar[bool] = ContextVar("bypass_tenant_filter", default=False)


def _resolve_tenant_context(session) -> tuple[Optional[int], bool]:
    """현재 세션의 tenant 컨텍스트 결정.

    우선순위:
    1. session.info['tenant_id'] / session.info['bypass_tenant']
    2. ContextVar fallback (legacy)

    불일치 발견 시 critical diag 로그.
    """
    info_tid = session.info.get('tenant_id')
    info_bypass = session.info.get('bypass_tenant', False)

    ctx_tid = current_tenant_id.get()
    ctx_bypass = bypass_tenant_filter.get()

    # 우선순위: session.info 가 있으면 그걸 사용
    if 'tenant_id' in session.info or 'bypass_tenant' in session.info:
        # 불일치 감지 — diag 로그
        if ctx_tid is not None and info_tid is not None and ctx_tid != info_tid:
            from app.diag_logger import diag
            diag("tenant_context.mismatch", level="critical",
                 session_tid=info_tid, ctx_tid=ctx_tid)
        if ctx_bypass != info_bypass:
            from app.diag_logger import diag
            diag("tenant_context.bypass_mismatch", level="warning",
                 session_bypass=info_bypass, ctx_bypass=ctx_bypass)
        return info_tid, info_bypass

    # session.info 없으면 ContextVar fallback (legacy 코드 호환)
    return ctx_tid, ctx_bypass


# before_flush — auto-inject tenant_id on INSERT
@event.listens_for(Session, "before_flush")
def _set_tenant_on_new_objects(session, flush_context, instances):
    tid, _ = _resolve_tenant_context(session)
    if tid is None:
        return
    for obj in session.new:
        if hasattr(obj, 'tenant_id') and obj.tenant_id is None:
            obj.tenant_id = tid


# before_compile — auto-filter
@event.listens_for(Query, "before_compile", retval=True)
def _apply_tenant_filter_on_select(query):
    if query._execution_options.get("_tenant_filtered", False):
        return query

    # session 추출 (Query 에서 session 으로)
    session = query.session

    tid, bypass = _resolve_tenant_context(session)

    if bypass:
        return query  # bypass 우선 — 모든 row 반환

    if tid is None:
        # Fail-closed
        for desc in query.column_descriptions:
            entity = desc.get("entity")
            if entity is not None and entity in TENANT_MODELS:
                raise RuntimeError(...)
        return query

    # tenant 필터 적용
    query = query.execution_options(_tenant_filtered=True)
    ...
    return query
```

## Feature Flag

```python
# config.py 추가
class Settings(BaseSettings):
    OPTION_C_PHASE: int = Field(default=0, description="0=disabled, 1=shim only, 2=API, 3=scheduler, 4=services, 5=cleanup, 6=remove ContextVar")
```

각 Phase 진입 시 환경변수 변경:
- `OPTION_C_PHASE=0`: 새 factory 정의 추가만, 기존 동작 유지
- `OPTION_C_PHASE=1`: shim 활성 (session.info 우선 핸들러)
- `OPTION_C_PHASE=2`: API layer 가 session_for_tenant 사용
- `OPTION_C_PHASE=3`: 스케줄러가 session_for_tenant 사용
- `OPTION_C_PHASE=4`: service 함수들 변환
- `OPTION_C_PHASE=5`: ContextVar 의존 제거 검증
- `OPTION_C_PHASE=6`: ContextVar 정의 자체 제거

## 점진 도입 시 동작 매트릭스

| 코드 위치 | Phase 0 | Phase 1 | Phase 2~3 | Phase 4 | Phase 5~6 |
|--|--|--|--|--|--|
| `get_tenant_scoped_db` (deps.py) | ContextVar set | ContextVar set | session_for_tenant | session_for_tenant | session_for_tenant |
| `_for_each_tenant` (jobs.py) | ContextVar set | ContextVar set | ContextVar set | session_for_tenant | session_for_tenant |
| `record_sms_sent` (sms_tracking.py) | ContextVar.get | session.info or ContextVar | session.info or ContextVar | session.info | session.info |
| `before_flush` 핸들러 | ContextVar.get | session.info → ContextVar fallback | 동일 | session.info 만 | session.info 만 |

## 호환성 검증 시나리오

### V1. Phase 1 적용 후 — 기존 동작 회귀 0
모든 호출이 ContextVar set/reset 그대로. session.info 안 박힘. shim 의 fallback 분기 100% 사용. **기존 동작 보존**.

### V2. Phase 2 적용 후 — API 만 신규 패턴
- API endpoint: session.info['tenant_id'] = X 박힘 → session.info 우선
- 스케줄러: ContextVar 만 사용 → fallback 분기
- 같은 reservation 에 대해 API 와 스케줄러가 다른 동작? 둘 다 같은 tid 받으면 안전.

### V3. Phase 3 후 — API + 스케줄러 둘 다 신규
모든 진입점에서 session.info 박힘. ContextVar 는 service 함수 일부만 의존.

### V4. Phase 4 후 — service 함수 변환 완료
ContextVar.get() 호출 0건. 모든 코드가 session.info 사용.

### V5. Phase 5 검증 — ContextVar set/reset 0건
grep 으로 ContextVar 사용 모두 제거 확인.

### V6. Phase 6 — ContextVar 정의 삭제
`current_tenant_id` / `bypass_tenant_filter` ContextVar 정의 자체 제거. fallback 분기 제거.

## 위험과 대응

### 🟡 [Medium] shim 의 fallback 분기가 silent 누수 마스킹
session.info 없으면 ContextVar 사용 → 옵션 C 가 격리 못함. Phase 5~6 전엔 ContextVar 누수 위험 잔존.

**대응**: Phase 5 시작 전 ContextVar 사용 grep 으로 0건 검증. shim 의 fallback 호출 시 critical diag 로그 추가 (호출되면 안 되는 시점).

### 🟠 [High] session.info 변경 가능성
`session.info['tenant_id'] = X` 가 코드 어디에서나 호출 가능. immutable 보장 어려움.

**대응**: session factory 가 박은 후엔 변경 금지 정책. 변경 시도 시 경고 (event listener 로 감지 가능).

### 🟢 [Safe] before_compile 에서 session 접근
SQLAlchemy 의 `Query.session` attribute 표준 패턴. 안전.

## Phase 1 구현 체크리스트

- [ ] `db/database.py` 에 `session_for_tenant` / `session_bypass` / `session_unscoped` 추가
- [ ] `db/tenant_context.py` 의 before_flush/before_compile 를 `_resolve_tenant_context` 사용
- [ ] `_resolve_tenant_context` 의 mismatch 감지 + diag 로그
- [ ] feature flag `OPTION_C_PHASE` 정의
- [ ] 단위 테스트: `test_session_factory.py` (session.info 박힘 검증)
- [ ] 통합 테스트: `test_session_compat_shim.py` (둘 다 set 시 우선순위 검증)
- [ ] CI 통과 확인
- [ ] 운영 배포 + 24시간 모니터링 — diag 의 mismatch 발화 0건 확인 후 다음 Phase

## Phase 6 cleanup 체크리스트

- [ ] grep `current_tenant_id` 사용 0건 (단, diag_logger.py:146 제외 — 별도 채널)
- [ ] grep `bypass_tenant_filter` 사용 0건
- [ ] `tenant_context.py` 의 ContextVar 정의 + fallback 분기 제거
- [ ] feature flag 제거
- [ ] 마이그레이션 문서 archive
