# Phase 0 산출물 #6: 외부 통합 의존성 매트릭스

> 옵션 C 전환 시 외부 통합 컴포넌트가 tenant 정보를 받는 방식 + 영향도

## 통합 컴포넌트별 매트릭스

| 컴포넌트 | tenant 받는 방식 | ContextVar 의존 | 옵션 C 후 |
|--|--|--|--|
| **`event_bus.publish/subscribe`** | 인자 명시 (`tenant_id: int`) | ✅ 없음 | 변경 없음 — 이미 명시 패턴 |
| **`activity_logger.log_activity`** | `current_tenant_id.get()` (slug 조회) | ⚠️ 있음 | session 인자 받기 + `db.info['tenant_id']` |
| **`factory.get_*_for_tenant`** | tenant 객체 명시 인자 | ✅ 없음 | 변경 없음 — 이미 명시 패턴 |
| **`diag_logger.diag`** | `current_tenant_id.get()` (자동) | ⚠️ 있음 | session 받거나 명시 인자 (또는 fallback None 허용) |
| **`SMS provider (Aligo)`** | factory 가 tenant.aligo_sender / testmode 명시 | ✅ 없음 | 변경 없음 |
| **`Reservation provider (Naver)`** | factory 가 tenant.naver_business_id / cookie 명시 | ✅ 없음 | 변경 없음 |
| **SSE `event_stream` endpoint** | 헤더 X-Tenant-Id → `get_current_tenant_id` | (deps 거침) | 변경 없음 |
| **Webhook 핸들러** | (해당 없음 — 전부 인증된 API endpoint) | - | - |

## 컴포넌트별 상세 분석

### A. event_bus (`services/event_bus.py`) — 🟢 안전

**현재 코드**:
```python
def publish(event_type: str, data: dict, tenant_id: int) -> None:
    ...
def subscribe(tenant_id: int) -> asyncio.Queue:
    ...
```

**평가**: tenant_id 명시 인자. 글로벌 dict `_queues: Dict[int, Set[Queue]]` 사용. 격리 정상.

**옵션 C 후**: 변경 없음. session 과 무관.

**잠재 영향**: 호출자가 잘못된 tenant_id 넘기면 잘못된 채널로 발행. 기존도 같은 위험. 옵션 C 가 직접 영향 없음.

### B. activity_logger (`services/activity_logger.py`) — 🟠 변경 필요

**현재 코드**:
```python
def _get_tenant_slug(db: Session) -> str | None:
    tid = current_tenant_id.get()  # ← ContextVar
    if tid is None:
        return None
    tenant = db.get(Tenant, tid)
    return tenant.slug.upper() if tenant else None

def log_activity(db: Session, type: str, ...):
    slug = _get_tenant_slug(db)
    title = f"[{slug}] {title}"
    log = ActivityLog(...)  # tenant_id 는 before_flush 자동 주입
```

**평가**: `current_tenant_id.get()` 으로 slug 조회. before_flush 가 ActivityLog.tenant_id 자동 주입.

**옵션 C 후**:
```python
def _get_tenant_slug(db: Session) -> str | None:
    tid = db.info.get('tenant_id')
    if tid is None:
        return None
    tenant = db.get(Tenant, tid)
    return tenant.slug.upper() if tenant else None
```

호출자 변경 없음 (시그니처 동일). 단순 ContextVar → session.info 교체.

**잠재 영향**: 로그 활동 30+곳 호출자 영향 0. 안전.

### C. factory (`factory.py`) — 🟢 안전

**현재 코드**:
```python
def get_sms_provider_for_tenant(tenant=None) -> SMSProvider:
    sender = tenant.aligo_sender if tenant and tenant.aligo_sender else ''
    ...
```

**평가**: tenant 객체를 명시 인자로 받음. ContextVar 의존 0.

**옵션 C 후**: 변경 없음. 호출자가 session.info['tenant_id'] 로 tenant 객체 fetch 후 전달하는 패턴은 그대로.

### D. diag_logger (`diag_logger.py:146`) — 🟡 marginal 변경

**현재 코드**:
```python
def diag(name, level="verbose", **kwargs):
    from app.db.tenant_context import current_tenant_id
    kwargs.setdefault("tid", current_tenant_id.get())
    ...
```

**평가**: tenant_id 자동 보강. 호출자가 명시 안 해도 진단 로그에 tid 박힘.

**옵션 C 후 옵션**:
- **옵션 1**: ContextVar 그대로 두고 (별도 유지) 옵션 C 의 session.info 와 별개로 운영. 호환 shim 시기엔 둘 다 channel.
- **옵션 2**: diag 가 호출자에게 session 인자 받기. 호출자 부담 큼.
- **옵션 3**: diag 호출 시 tid 명시 (대부분 호출자가 이미 명시).

→ **권장: 옵션 1**. diag 의 ContextVar 는 진단 한정이라 격리 무관. 옵션 C 마이그레이션 범위에서 제외.

### E. SMS / Reservation provider — 🟢 안전

factory 가 tenant 객체 받아 provider 인스턴스 생성. provider 자체는 tenant 의 API key / cookie 만 사용. ContextVar 의존 0.

**옵션 C 후**: 변경 없음.

### F. SSE event_stream (`api/events.py:73`) — 🟡 long-lived 검증 필요

**현재 코드** (추정):
```python
async def event_stream(...):
    db = SessionLocal()
    ...
    async def generator():
        ...
        yield f"data: {payload}\n\n"
```

SSE 는 분~시간 단위 long-lived. db 가 그 동안 살아있어야 함. 옵션 C 후엔 `session_for_tenant(tid)` 가 long-lived 동안 유지.

**잠재 위험**: connection pool 의 session 이 너무 오래 점유. pool_size=5 환경에서 SSE 5개 동시 접속 시 풀 고갈.

**검증 필요**: SSE 동작 패턴 정밀 확인 후 별도 산출물.

### G. Webhook — N/A

API 호출 검색 결과 webhook 라우트 없음. 모두 인증된 API endpoint (X-Tenant-Id 헤더 + JWT). FastAPI 의존성으로 tenant 격리 정상.

## ActivityLog 자동 주입 검증

```python
log = ActivityLog(
    activity_type=type,
    title=title,
    detail=...,
    ...,  # tenant_id 명시 안 함
)
db.add(log)
```

before_flush 가 `current_tenant_id.get()` 으로 tenant_id 자동 주입. 옵션 C 후엔 `db.info.get('tenant_id')` 으로.

**호환성**: tenant_context.py 의 `_set_tenant_on_new_objects` 핸들러를 session.info 우선으로 변경하면 자동 주입 동작 유지.

## 외부 라이브러리 의존성

| 라이브러리 | tenant 인지? | 옵션 C 영향 |
|--|--|--|
| FastAPI | 의존성 시스템 통해 tenant 받음 (deps.py) | 의존성 함수만 변경 |
| SQLAlchemy | session.info 표준 사용 가능 | 적용 가능 |
| APScheduler | tenant 무관 (라이브러리는 잡 실행만) | 옵션 C 가 ContextVar 격리 부재 우회 |
| starlette | tenant 무관 | 영향 없음 |
| Aligo SDK | API key 만 받음 | 영향 없음 |
| Naver API client | cookie / business_id 만 받음 | 영향 없음 |

## Phase 별 변경 매핑

### Phase 1 (호환 shim)
- `tenant_context.py` 의 before_flush/before_compile 핸들러를 session.info 우선 + ContextVar fallback 으로 변경

### Phase 4 (service layer)
- `activity_logger._get_tenant_slug` → session.info 읽기로 변경
- 호출자 30+ 곳 시그니처 변경 없음 (db 인자 그대로)

### Phase 6 (cleanup)
- `diag_logger.py:146` 의 ContextVar 의존은 유지 (별도 채널)
- SSE event_stream 의 long-lived session 은 별도 audit 후 결정

## 위험 신호 요약

### 🟢 [Safe] 대부분 외부 통합이 명시 인자 패턴
event_bus, factory, SMS/reservation provider 모두 tenant 명시 인자. 옵션 C 영향 0.

### 🟠 [High] activity_logger 변경 필요하지만 호출자 영향 0
시그니처 유지하면서 내부만 session.info 로 전환. 단순 변경.

### 🟡 [Medium] SSE long-lived session 별도 검증
event_stream 의 connection pool 점유 패턴 확인 필요. 옵션 C 가 직접 영향 주지 않지만 운영 안정성 검토.

### 🟢 [Safe] diag_logger ContextVar 별도 채널 유지
진단 전용이라 격리 무관. 옵션 C 적용 후에도 그대로.
