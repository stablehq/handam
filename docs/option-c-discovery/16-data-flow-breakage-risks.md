# Phase 0 산출물 #16: 데이터 흐름 단절 위험 표

> session 종료 후 ORM 객체 / 캐시 / 다른 task 로 전달된 데이터의 단절 위험 식별.

## 위험 카테고리

### A. Session 종료 후 ORM 객체 lazy attribute 접근

**현재 동작**: `session.close()` 후 ORM 객체가 detach 됨. lazy attribute 접근 시 `DetachedInstanceError` 또는 새 session 필요.

**옵션 C 후**: 동일. 단, 새 session 이 필요할 때 `session_for_tenant(tid)` 가 필요 — tenant 정보는 어디서?

**위험 사이트**:
- API endpoint 응답 변환 시 (FastAPI ORM → Pydantic model)
- 백그라운드 task 가 ORM 객체 받은 후 lazy 접근
- SSE event_stream 안에서 detach 후 접근

**대응 패턴**:
1. **Eager load**: endpoint 안에서 `selectinload`/`joinedload` 강제
2. **DTO 변환**: ORM 객체 → dict 변환 후 전달
3. **ID 만 전달**: 백그라운드 task 에 ID 넘기고 task 안에서 다시 query

### B. 캐시된 ORM 객체

**검색 결과**:
- `lru_cache`: settings.py:104 (settings 객체 — DB 무관)
- in-memory dict cache: `event_bus._queues` (tenant_id keyed Queue, ORM 무관)
- naver user_info_cache (real/reservation.py:205, dict, ORM 무관)

**ORM 객체 캐시 0건**: 안전.

**옵션 C 후**: 변화 없음.

### C. 백그라운드 task 가 외부 데이터 받음

**위치**: `event_sms_hook.py:52`
```python
task = loop.create_task(_run_event_hook(ids: List[int], tenant_id: int))
```

**전달 데이터**: ID 리스트 + tenant_id. ORM 객체 없음. 안전.

**옵션 C 후**: task 안에서 새 session_for_tenant(tenant_id) 사용. 동일.

### D. 응답 변환 시 lazy load

**위험**: FastAPI 가 endpoint return 값을 Pydantic model 로 직렬화할 때 ORM 객체의 lazy attribute 접근 가능.

**위험 시나리오**:
```python
@router.get("/reservations")
async def list_reservations(db: Session = Depends(get_tenant_scoped_db)):
    reservations = db.query(Reservation).all()
    return reservations  # ← Pydantic model 변환 시 r.room_assignments 같은 lazy 접근?
```

`get_tenant_scoped_db` 가 yield 후 finally 에서 close 하지만 — return 후 직렬화는 yield 전에 끝남. 안전.

**검증 필요**: `response_model` 정의에 nested relationship 명시된 곳. 200+ endpoint 검사.

### E. SSE event_stream long-lived

**위치**: `api/events.py:73-99`

**위험**: SSE 가 분~시간 동안 연결 유지. 그 동안 db 사용 패턴 확인 필요.

**가능한 시나리오**:
1. SSE 가 publish 받은 데이터만 forward → db 무관 ✅ 안전
2. SSE 가 주기적으로 db.query → 매 query 마다 명시적 db 사용

**검증 필요**: events.py 본문 정밀 확인.

### F. detach + merge 패턴

**위치**: `settings.py:301-303`
```python
merged_tenant = db.merge(tenant)  # 다른 session 의 tenant 객체를 현 session 으로 병합
merged_tenant.custom_highlight_colors = json.dumps(valid_colors)
```

**평가**: 명시적 merge — 안전. 옵션 C 후 새 session 으로 merge 시 tenant 정보 자동 inherit (session.info 가 새 session).

**위험**: 🟢 안전.

### G. ID 만 capture (avoid detached) 패턴

**위치**: `schedule_manager.py:84` (주석: "Capture only schedule ID to avoid detached instance errors")

**평가**: 명시적으로 ORM 객체 detach 위험 회피 중. 안전.

**옵션 C 후**: 동일.

### H. detach 후 attribute 변경

**위험 시나리오**: detach 된 ORM 객체에 attribute 변경 후 새 session 으로 전달.

**검색 결과**: 그런 패턴 검색 안 됨 (need deeper analysis).

## API 응답 변환 정밀 audit (별도 후속 작업)

200+ endpoint 의 response_model + ORM relationship 사용 패턴 audit 가 별도 산출물 필요. 다음 우선순위:

### 우선순위 1: 가장 자주 호출되는 endpoint
```bash
# 운영 로그에서 호출 빈도 분석
grep "GET\|POST" backend/logs/access.log 2>/dev/null | sort | uniq -c | sort -rn
```

### 우선순위 2: response_model 에 nested 명시
```bash
grep -rn "response_model=.*Response" backend/app/api --include="*.py" | head -20
```

각 response_model 정의 확인 → relationship 자동 변환되는 필드 식별.

### 우선순위 3: 운영 로그에 DetachedInstanceError 발생 이력
```bash
grep -i "DetachedInstanceError\|detached instance" backend/logs/*.log 2>/dev/null
```

→ 0건이어야 안전.

## 옵션 C 후 위험 변화

| 시나리오 | 현재 위험도 | 옵션 C 후 위험도 |
|--|--|--|
| Detach 후 lazy load | 🟡 (눈에 안 띈 잠재 위험) | 🟡 (동일) |
| ORM 객체 캐싱 | 🟢 (없음) | 🟢 (없음) |
| 백그라운드 task 객체 전달 | 🟢 (ID 만 전달) | 🟢 |
| 응답 변환 시 lazy | 🟡 (audit 필요) | 🟡 |
| SSE long-lived | 🟡 (검증 필요) | 🟡 |
| Merge 패턴 | 🟢 | 🟢 |
| ID capture 패턴 | 🟢 | 🟢 |

## 옵션 C 가 추가하는 위험

### N1. detach 된 객체에 lazy 접근 시 새 session 필요
**현재**: ContextVar 가 살아있으면 새 session 자동 attach 가능.
**옵션 C 후**: 새 session 만들 때 명시 tenant_id 필요.

대응: detach 객체에 lazy 접근하는 코드는 audit 후 eager load 또는 DTO 로 변환.

### N2. session.info 가 task 간 inherit 안 됨
**현재**: ContextVar 는 task 자동 inherit.
**옵션 C 후**: session 객체를 task 에 명시 전달 또는 새 session 생성.

검색 결과 그런 패턴 0건. 위험 없음.

### N3. ORM 객체가 session 외부에서 transient 상태 변경 후 재attach
드물지만 가능. 옵션 C 후엔 명시 session.add() 필요.

## 권장 audit (Phase 0 후속)

### A1. 200+ endpoint 응답 변환 audit
```bash
# 자동화 가능한 부분
grep -rn "response_model=" backend/app/api --include="*.py" \
  | awk -F: '{print $1}' | sort -u | while read f; do
    echo "=== $f ==="
    grep -A 2 "response_model=" "$f"
done
```

각 endpoint 의 return 값과 response_model 비교.

### A2. SSE event_stream 정밀 분석
`backend/app/api/events.py` 전체 읽고 db 사용 패턴 다이어그램.

### A3. detach 발생 위험 동적 검증
운영 환경에 SQLAlchemy event listener 추가:
```python
@event.listens_for(Session, "after_attach")
def warn_on_detach(session, instance):
    # detach 발생 추적
    pass
```

운영 로그에서 DetachedInstanceError / 새 session 으로 자동 attach 발생 빈도 측정.

## 결론

**대부분 데이터 흐름은 옵션 C 후에도 안전**. 위험 사이트는:
1. 응답 변환 시 lazy (200+ endpoint 정밀 audit 필요)
2. SSE long-lived (별도 audit)

이 둘은 옵션 C 가 직접 만든 위험이 아니라 기존부터 잠재했던 위험. 옵션 C 가 새로 만드는 위험 N1~N3 는 모두 cover 가능.

**Phase 1 작업 시작 전**: audit A1, A2 추가 진행 권장. A3 는 운영 모니터링 강화 (Phase 5 observability 와 연계).
