# 단계 #15 frontend 마이그레이션 — 전수조사 및 분해

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §F
> 전제: 본 세션 단계 #1~#14 머지 완료 — `check_out_pinned` 가 `manually_extended_until` 과 lifecycle 1:1 동기
> 본 문서: 전수조사 결과 + 단계 분해 (FE/BE 사전조사 문서 작성을 위한 마스터)

---

## 1. 전수조사 결과

### 1-1. frontend 의 `manually_extended_until` 사용 — 3곳

| # | 파일 | 라인 | 종류 | 실질 영향 |
|---|---|---|---|---|
| 1 | `frontend/src/pages/RoomAssignment/types.ts` | 53 | 타입 선언 (`manually_extended_until?: string \| null`) | TypeScript 컴파일 (런타임 0) |
| 2 | `frontend/src/pages/RoomAssignment.tsx` | 546 | UI 분기 (`!!firstRes?.manually_extended_until`) — "연박 취소" 버튼 표시 조건 | 🔴 핵심 |
| 3 | `frontend/src/services/api.ts` | 230 | 주석 (`/** New model: reduce manually_extended_until by N days (default 1). */`) | 런타임 0 |

### 1-2. frontend 의 `check_in_pinned` / `check_out_pinned` 사용

```
grep -rn "check_in_pinned\|check_out_pinned" frontend/src → 0건
```

→ frontend 가 새 필드를 모름. 마이그레이션의 핵심 조건.

### 1-3. backend `ReservationResponse` 의 현재 필드

`app/api/reservations_shared.py:116~163` (Pydantic BaseModel):
- `manually_extended_until: Optional[str] = None` (L152) — **노출됨**
- `check_in_pinned`, `check_out_pinned` — **미노출** (단계 #2~#3 에서 컬럼만 추가, schema 미수정)

### 1-4. backend `_to_response()` 의 매핑

`app/api/reservations_shared.py:249`:
```python
manually_extended_until=res.manually_extended_until,
```

→ ORM 객체의 `manually_extended_until` 을 response 필드로 전달. `check_in_pinned`/`check_out_pinned` 전달 없음.

### 1-5. `Reservation` 타입의 다른 사용처 (영향 없음 확인)

`from RoomAssignment/types` import 14개 모듈 중 `manually_extended_until` 참조 — `RoomAssignment.tsx:546` 1건만. 다른 hooks (`useGuestMove`, `useReservationsData`, `useColumnResize`, etc.) 와 컴포넌트 (`CompactGuestCell`, `SmsCell`) 는 다른 필드만 사용.

검증 명령:
```bash
for f in $(grep -rln "from.*types'" frontend/src); do
  grep -q "manually_extended_until" "$f" && echo "$f"
done
# 결과: types.ts + RoomAssignment.tsx 2건만 (이미 확인된 사용처)
```

### 1-6. extend-stay 관련 API 호출 흐름 (영향 없음 — 단순 endpoint 호출)

`frontend/src/services/api.ts:226~234`:
- `extendStay` — POST /reservations/{id}/extend-stay
- `cancelExtendStay` — DELETE /reservations/{id}/extend-stay
- `reduceExtension` — POST /reservations/{id}/reduce-extension
- `assignExtendStayRoom` — POST /reservations/{id}/extend-stay/assign-room

→ 모두 endpoint 호출. payload/response 에 `manually_extended_until` 직접 참조 없음. 본 마이그레이션 범위 밖.

---

## 2. 라인 단위 의미 검증

### 2-1. `RoomAssignment.tsx:546` 의 정확한 동작

```typescript
onCancelExtendStay: (targetIds.length === 1 && !!firstRes?.manually_extended_until) ? () => {
    const resId = targetIds[0];
    setContextMenu(null);
    window.__diagAction = 'ctx_menu:cancel_extend_stay';
    cancelExtendStayMutation.mutate(resId);
} : undefined,
```

**의미**:
- `firstRes?.manually_extended_until` 이 truthy (non-null, non-empty string) 일 때만 콜백 전달
- `undefined` 면 컨텍스트 메뉴의 "연박 취소" 항목 비활성/숨김 (consumer 가 `undefined` 체크하여 처리)

**`check_out_pinned` 로 교체 시 의미 변화**:
- Before: `firstRes?.manually_extended_until` truthy → 사용자가 연박 연장한 케이스만 (extend_stay 가 set, reduce 완전축소 시 clear)
- After: `firstRes?.check_out_pinned` truthy → 사용자가 check_out 을 manual 로 변경한 모든 케이스 (extend, reservations.py PUT 으로 check_out 변경, dateCrossMutation 등)

**의미 차이 분석**:

| 시나리오 | manually_extended_until | check_out_pinned |
|---|---|---|
| 연박 연장 (extend_stay) | True | True (단계 #8) |
| 수동 PUT 으로 check_out 변경 (extend 아님) | False | True (단계 #7) |
| dateCrossMutation (날짜 가로지르는 드래그) | False | True (단계 #7 자동) |
| 자동 연박 (네이버 동기화 후) | False | False |

→ **의미 확장**: `check_out_pinned` 가 truthy 인 케이스가 `manually_extended_until` 보다 많음. "연박 취소" 버튼이 더 많이 표시됨.

**위험 분석**:
- 사용자가 단순 PUT 으로 check_out 변경 → check_out_pinned=True → "연박 취소" 버튼 노출 → 사용자가 클릭 시 `cancelExtendStay` 호출 → backend `DELETE /reservations/{id}/extend-stay` 처리
- backend 의 cancel-extend-stay 엔드포인트가 무엇을 하는지 확인 필요 — 진짜 "연박 취소" (1박으로 축소) 인가, 아니면 manually_extended_until 만 해제하는가?

검증 필요:
```bash
grep -A 20 "cancel_extend_stay\|cancel-extend-stay" backend/app/api/reservations_stay.py
```

만약 cancel-extend-stay 가 check_out_date 를 줄이는 동작이면 — 사용자가 단순 PUT 으로 check_out 만 변경한 케이스에서 클릭 시 의도와 다른 동작 (check_out 이 더 줄어듬). **silent regression 위험**.

**완화 옵션**:
- A. `check_out_pinned` 대신 `manually_extended_until` 의 의미를 frontend 가 유지하려면 — 별도 컬럼 추가 (`is_manually_extended`) 필요
- B. **현재 의미를 그대로 살리려면 manually_extended_until 컬럼 유지** — #15 deprecation 자체를 안 하는 게 안전
- C. backend cancel-extend-stay 엔드포인트의 동작을 확인 후, 의미 차이가 허용되는지 결정

### 2-2. cancel-extend-stay backend 동작 확인 필요

본 문서 작성 시점에서 미확인. 검증 명령:
```bash
grep -nA 30 "cancel-extend-stay\|cancel_extend_stay\|@router.delete.*extend-stay" backend/app/api/reservations_stay.py
```

만약 단순히 `manually_extended_until=None` 만 클리어하면 안전. check_out_date 를 만지면 위험.

---

## 3. backend 사전 작업 (FE 마이그레이션 전제)

### 3-1. `ReservationResponse` 에 새 필드 추가

```python
# app/api/reservations_shared.py L116~ ReservationResponse 클래스
class ReservationResponse(BaseModel):
    # ... 기존 필드
    manually_extended_until: Optional[str] = None  # 기존
    check_in_pinned: bool = False    # ← 추가 (단계 #15a)
    check_out_pinned: bool = False   # ← 추가 (단계 #15a)
    # ...
```

### 3-2. `_to_response()` 인자 추가

```python
# app/api/reservations_shared.py L249 부근
return ReservationResponse(
    # ... 기존 필드
    manually_extended_until=res.manually_extended_until,
    check_in_pinned=bool(res.check_in_pinned),    # ← 추가
    check_out_pinned=bool(res.check_out_pinned),  # ← 추가
    # ...
)
```

**동작 변화**: 응답에 2 필드 추가. 기존 frontend 가 안 봐도 무관 (Pydantic 가 알 수 없는 키 무시). silent regression 0.

---

## 4. 단계 분해

본 #15 의 frontend + backend 마이그레이션을 4 단계로 분해. 각 단계는 별도 PR + 사전조사 + 검증.

### 단계 #15a — backend response 에 pin 노출 + frontend types 확장

| 작업 | 파일 | 위험도 |
|---|---|---|
| `ReservationResponse` 에 `check_in_pinned`, `check_out_pinned` 필드 추가 | `app/api/reservations_shared.py` | ⚪ 무위험 (필드만 추가) |
| `_to_response()` 에 두 인자 전달 추가 | 동일 | ⚪ |
| frontend `types.ts` 에 두 필드 추가 (optional) | `frontend/src/pages/RoomAssignment/types.ts` | ⚪ |

→ 본 단계 머지 후 frontend 가 두 필드를 받을 수 있는 상태 (사용은 안 함).

### 단계 #15b — backend cancel-extend-stay 의미 확인 + frontend UI 분기 교체

| 작업 | 파일 | 위험도 |
|---|---|---|
| `cancel_extend_stay` 엔드포인트 동작 검증 (의미 차이 분석) | 사전조사 (코드 변경 0) | — |
| 의미 차이 결정 후 frontend `RoomAssignment.tsx:546` 의 조건을 `check_out_pinned` 로 교체 | `frontend/src/pages/RoomAssignment.tsx` | 🔵 의도된 변화 (의미 확장) |
| 또는: 의미 차이 허용 안 되면 **새 컬럼 `is_manually_extended` 추가** (별도 마이그레이션) | — | 별도 마일스톤 |

→ 본 단계가 위험도가 가장 높음. 사전 검증 필수.

### 단계 #15c — backend manually_extended_until 코드 제거

| 작업 | 파일 | 위험도 |
|---|---|---|
| `naver_sync.py` 첫 if 절 (manually_extended_until 가드) 제거 → OR 절의 check_out_pinned 만 남김 | `app/services/naver_sync.py` | ⚪ 동작 동등 (단계 #5/#8 의 1:1 매핑) |
| `naver_sync.py` catch-up 분기 (`incoming_end >= existing.manually_extended_until`) 제거 | 동일 | ⚪ check_out_pinned catch-up 이 대체 |
| `extend_stay` / `_do_reduce_extension` 의 `manually_extended_until` set/clear 라인 3곳 제거 | `app/api/reservations_stay.py` | ⚪ |
| `reservations.py` 의 manually_extended_until clear 라인 2곳 제거 | `app/api/reservations.py` | ⚪ |
| `naver_sync.py` cancel clear 1곳 제거 | `app/services/naver_sync.py` | ⚪ |
| `_to_response()` 에서 `manually_extended_until` 인자 제거 | `app/api/reservations_shared.py` | 🔴 frontend types.ts 가 받지만 None — UI 분기 영향 (단계 #15b 머지 후라야 안전) |
| `ReservationResponse` 에서 `manually_extended_until` 필드 제거 | 동일 | 동일 |
| frontend `types.ts` 에서 manually_extended_until 제거 | `frontend/src/pages/RoomAssignment/types.ts` | ⚪ TypeScript 만 |
| `api.ts:230` 주석 갱신 | `frontend/src/services/api.ts` | ⚪ |

### 단계 #15d — DB 컬럼 drop (alembic + 데이터 백필)

| 작업 | 파일 | 위험도 |
|---|---|---|
| 데이터 백필 검증 SQL: `SELECT COUNT(*) FROM reservations WHERE manually_extended_until IS NOT NULL AND check_out_pinned = FALSE;` → 0 확인 | 운영 환경 | ⚪ 확인만 |
| alembic `021_drop_manually_extended_until.py` 신규 — backfill + drop_column | `alembic/versions/021_*` | ⚪ 컬럼 drop 후 롤백 불가 (downgrade 도 backfill 못함) — irreversible 표시 필요 |
| `db/models.py` 의 `manually_extended_until = Column(...)` 라인 제거 | `app/db/models.py` | ⚪ |

---

## 5. 의존성 그래프

```
#15a (response + types 확장)
   ↓
#15b (frontend UI 교체)  ← 의미 검증 필요 (cancel-extend-stay 의미)
   ↓
#15c (backend code 제거 + response 에서 manually_extended_until 제거 + frontend types 정리)
   ↓
#15d (DB 컬럼 drop + 백필 검증)
```

→ 각 단계가 직전 단계에 의존. 동시 머지 위험.

---

## 6. 위험도 매트릭스

| 단계 | 위험도 | 사유 | 완화 |
|---|---|---|---|
| #15a | ⚪ | 필드만 추가, 사용 0건 | 즉시 진행 가능 |
| #15b | 🔴 | UI 분기의 의미 확장 — silent regression 가능성 | cancel-extend-stay 동작 검증 + 의미 확장 허용 결정 |
| #15c | 🟡 | code 정리 동작 동등 but response 제거 단계는 frontend 가 #15b 완료해야 안전 | #15b 머지 후 진행 |
| #15d | 🟡 | DB 컬럼 drop irreversible | 운영 DB 백필 검증 SQL 사전 실행 |

---

## 7. 본 세션 진행 제안

**옵션 A (보수적, 권장)**: #15a 만 진행 — 무위험.
- backend response 에 pin 노출
- frontend types 에 추가
- 다음 세션에 #15b 의 의미 검증 후 진행 결정

**옵션 B**: #15a + #15b 까지. cancel-extend-stay 동작을 본 세션에서 검증한 뒤 의미 확장 허용 결정.

**옵션 C**: #15a + #15b + #15c. backend 코드 정리까지. DB drop 은 별도.

**옵션 D**: 전체 #15a~#15d. 운영 DB 백필 검증 SQL 결과 확보 필요.

사용자 검수 사항:
1. `cancel-extend-stay` 의 의미 — "연박 취소" 가 check_out_date 도 변경하는가?
2. UI 의 "연박 취소" 버튼을 모든 `check_out_pinned=True` 케이스에 노출해도 무방한가?
3. 운영 DB 의 `manually_extended_until IS NOT NULL AND check_out_pinned = FALSE` 행 존재 여부 (단계 #15d 전)

---

## 8. 다음 액션

본 전수조사 문서 검토 → 진행 옵션 선택 → `mutator-step-15a-*.md` 사전조사 작성 → 코드 변경.
