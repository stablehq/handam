# Phase 0 후속 #19: SSE event_stream 세션 lifecycle 정밀 분석

> **결론: long-lived DB session 사용 안 함. 옵션 C 안전.**

## 코드 분석 (`backend/app/api/events.py`)

### A. `_validate_token_and_tenant` (line 22-67)
**동작**: JWT 디코드 → User / UserTenantRole 검증 → 즉시 close

```python
def _validate_token_and_tenant(token: str, tenant_id: int) -> None:
    payload = decode_access_token(token)  # JWT 디코드 (DB 무관)
    username = payload.get("sub")
    
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(...).first()  # 검증 1
        ...
        if user.role != UserRole.SUPERADMIN:
            mapping = db.query(UserTenantRole).filter(...).first()  # 검증 2
            ...
    finally:
        db.close()  # ← 즉시 close
```

**lifecycle**: 함수 호출 ~ return. 수십 ms. **short-lived ✅**

### B. `event_stream` endpoint (line 70-114)
**동작**:
```python
@router.get("/stream")
async def event_stream(token: str, tenant_id: int):
    _validate_token_and_tenant(token, tenant_id)  # short-lived session
    
    q = subscribe(tenant_id)  # ← in-memory queue (event_bus._queues)
    
    async def generator():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(q, tenant_id)  # ← in-memory queue 해제
    
    return StreamingResponse(generator(), ...)
```

**중요 발견**:
- `event_stream` 자체는 **`SessionLocal()` 호출 없음**
- generator 안에서도 **DB 사용 없음**
- 모든 event 가 in-memory `event_bus._queues` 통해 전달됨
- long-lived 인 것은 **asyncio.Queue 점유 + StreamingResponse 연결**, DB session 아님

### C. event_bus 구조 (`services/event_bus.py`)
```python
_queues: Dict[int, Set[asyncio.Queue]] = {}  # in-memory, tenant_id keyed

def subscribe(tenant_id: int) -> asyncio.Queue: ...  # queue 생성
def unsubscribe(q, tenant_id) -> None: ...           # queue 해제
def publish(event_type, data, tenant_id) -> None: ...  # 다른 곳에서 호출 (DB 무관)
```

**평가**: in-memory 만. tenant_id 명시. DB session 0.

## SessionLocal() 호출 사이트 정정

**원래 산출물 #1 의 events.py:49** 가 long-lived 로 평가됐는데 — 잘못된 평가. 실제로는:
- **events.py:49** 는 `_validate_token_and_tenant` 안의 short-lived session ✅

**정정**:
| # | 파일:라인 | 카테고리 | lifecycle | 옵션 C |
|--|--|--|--|--|
| 6 | `api/events.py:49` | **token 검증 (short-lived)** | function call | `session_for_tenant(tid)` 또는 `session_unscoped()` (User/Tenant 는 비-tenant 모델) |

→ 산출물 #1 에서 "SSE long-lived" 표기는 부정확. 정정 필요.

## 옵션 C 후 변경

### `_validate_token_and_tenant` 옵션 C 화
```python
# 옵션 C 후
def _validate_token_and_tenant(token: str, tenant_id: int) -> None:
    payload = decode_access_token(token)
    username = payload.get("sub")
    
    # User / Tenant 는 TenantMixin 아님 → bypass session 사용 가능
    db = session_bypass()  # 또는 session_unscoped()
    try:
        user = db.query(User).filter(...).first()
        ...
        if user.role != UserRole.SUPERADMIN:
            mapping = db.query(UserTenantRole).filter(...).first()
    finally:
        db.close()
```

**왜 bypass?**: `User`, `UserTenantRole` 은 TenantMixin 아님 (산출물 #2 확인). 그러나 `Tenant` 도 TenantMixin 아님. 자동 필터 적용 안 됨. session.info['tenant_id'] 박힘 무관.

→ 정확히는 `SessionLocal()` 직접 호출과 동일 (`session_unscoped()`). 옵션 C 영향 0.

### `event_stream` generator 옵션 C 화
**변경 없음** — DB 사용 안 함.

## 위험 점수

| 항목 | 위험 |
|--|--|
| long-lived DB session | 🟢 **None** |
| connection pool 점유 | 🟢 **None** |
| detached object lazy load | 🟢 **None** (DB 객체 없음) |
| ContextVar 누수 | 🟢 **None** (token 검증만, 즉시 close) |
| event_bus tenant 격리 | 🟢 **명시 인자** |

## 부수 발견

### in-memory queue 의 multi-process 위험
`event_bus._queues` 는 process-local. 백엔드 인스턴스가 다중이면 한 인스턴스의 publish 가 다른 인스턴스의 SSE 구독자에 도달 안 함.

**현재 단일 인스턴스라 문제 없음**. 운영 확장 시 Redis Pub/Sub 같은 broker 필요. 옵션 C 와 무관.

### SSE connection pool 한계
`asyncio.Queue(maxsize=50)` per client. 백엔드 인스턴스의 메모리 한계. 옵션 C 무관.

## 결론

**SSE event_stream 은 옵션 C 마이그레이션에 위험 0**. long-lived DB session 사용 안 함, in-memory queue 만 사용. token 검증의 short-lived session 만 옵션 C 화 (간단).

산출물 #1 의 events.py:49 분류를 "long-lived" → "short-lived (token validation)" 으로 정정 필요.

**Phase 1 진입 결정 영향**: 🟢 **진입 가능**. SSE 별도 audit 추가 작업 0.
