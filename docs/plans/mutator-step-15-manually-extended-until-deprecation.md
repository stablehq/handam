# 단계 #15 사전조사 — `manually_extended_until` deprecation

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §F
> 상태: **보류 — 별도 마일스톤 권장**
> 사유: frontend 가 본 필드를 사용 중 (`RoomAssignment.tsx:546`) — backend 단독 deprecation 시 silent regression

---

## 1. 발견 — frontend 영향

`grep -rn "manually_extended_until\|manuallyExtendedUntil" frontend/src`:

| 파일 | 라인 | 사용 |
|---|---|---|
| `frontend/src/pages/RoomAssignment/types.ts` | 53 | `manually_extended_until?: string \| null;` — 타입 선언 |
| `frontend/src/pages/RoomAssignment.tsx` | 546 | `firstRes?.manually_extended_until` 로 **"연박 취소" 버튼 표시 분기** |
| `frontend/src/services/api.ts` | 230 | 주석 (`reduce manually_extended_until by N days`) |

**핵심 케이스**: `RoomAssignment.tsx:546` 가 `manually_extended_until` 이 truthy 일 때만 `onCancelExtendStay` 콜백을 전달. backend 가 이 필드를 None 으로 응답 시작하면 → 사용자가 "연박 취소" 버튼을 영구히 못 봄.

---

## 2. 만약 진행한다면 — 필요한 작업 범위

본 단계가 본 마이그레이션의 범위에서 빠진 이유. 진행 시 필요한 모든 작업:

### 2-1. backend
- `naver_sync.py` 의 첫 if 절 (manually_extended_until 가드 조건) 제거 — `check_out_pinned` OR 절만 남김
- `naver_sync.py` catch-up `if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:` 분기 제거
- `reservations_stay.py` 의 `original.manually_extended_until = ...` 라인 3곳 제거 (단계 #8 에서 추가한 `check_out_pinned` 만 남김)
- `reservations.py` 의 `db_reservation.manually_extended_until = None` 라인 2곳 제거 (단계 #8 에서 추가한 `check_out_pinned = False` 만 남김)
- `naver_sync.py:773` 의 cancel clear 라인 제거 (단계 #8 의 `check_out_pinned = False` 만 남김)
- `reservations_shared.py:152` 의 `manually_extended_until: Optional[str] = None` schema 필드 제거 또는 `check_out_pinned` 로 alias
- `reservations_shared.py:249` 의 `_to_response` 인자 제거
- `db/models.py:93` 의 `manually_extended_until = Column(...)` 컬럼 정의 제거
- 신규 alembic 마이그레이션 (`021_drop_manually_extended_until.py`):
  - 데이터 백필: `UPDATE reservations SET check_out_pinned = TRUE WHERE manually_extended_until IS NOT NULL;` (단계 #8 의 1:1 매핑으로 이미 동기 상태일 가능성 ↑ 이지만 안전망)
  - `op.drop_column('reservations', 'manually_extended_until')`

### 2-2. frontend
- `RoomAssignment/types.ts:53` 에서 `manually_extended_until` 제거 + `check_out_pinned?: boolean` 추가
- `RoomAssignment.tsx:546` 의 분기 조건을 `firstRes?.check_out_pinned` 로 교체
- `api.ts:230` 주석 갱신

### 2-3. 데이터 백필 검증
- 운영 DB 에서 `manually_extended_until IS NOT NULL AND check_out_pinned = FALSE` 인 행이 있는지 사전 검사 (있으면 단계 #8 의 1:1 매핑이 깨진 케이스 — 별도 조사 필요)

### 2-4. 배포 순서 — 동시 배포 필요
- backend response 에서 manually_extended_until 제거 + frontend 가 check_out_pinned 사용 — **동일 배포에서**. 분리 배포 시 frontend 가 None 받아서 버튼 안 보임.

---

## 3. 보류 결정 사유

| 항목 | 평가 |
|---|---|
| Mutator 마이그레이션 (단계 #1~#14) 의 핵심 목표 | 4 개 버그 해결 + 단일 게이트웨이 — **이미 달성** |
| `manually_extended_until` 제거의 추가 가치 | 기술 부채 정리, 코드 중복 제거 |
| 추가 위험 | frontend silent regression, 운영 DB 데이터 백필 실수 가능성 |
| 동반 작업 규모 | backend + frontend + alembic + 배포 동기화 |
| 본 세션에서의 진행 가능성 | frontend 코드 + 운영 DB 백필 검증이 별도 PR 필요 → **별도 마일스톤** |

---

## 4. 본 시점의 상태 (단계 #14 머지 후)

`manually_extended_until` 과 `check_out_pinned` 가 **lifecycle 1:1 동기 상태**로 공존:
- extend_stay: 둘 다 set (단계 #8)
- reduce 완전 축소: 둘 다 clear (단계 #8)
- reduce 부분 축소: 둘 다 set (단계 #8)
- cancel: 둘 다 clear (단계 #8)
- naver_sync 가드: 둘 다 OR 로 체크 (단계 #5)
- naver_sync catch-up: 각각 별도로 clear (단계 #10, 기존)

→ 두 플래그가 항상 동기. 단계 #15 deprecation 시 데이터 백필이 안전.

---

## 5. 권장 다음 액션 (별도 마일스톤)

1. 운영 DB 에서 `SELECT COUNT(*) FROM reservations WHERE manually_extended_until IS NOT NULL AND check_out_pinned = FALSE;` → 0 확인
2. frontend `RoomAssignment.tsx:546` 변경 PR — `check_out_pinned` 사용
3. frontend 배포 + 검증 (manually_extended_until 도 still 받지만 더 이상 안 씀)
4. backend deprecation PR — 본 §2-1 작업 + alembic 마이그레이션
5. 동시 배포

---

## 6. 본 세션 작업 종료 시점

단계 #14 머지 완료 = **본 마이그레이션의 핵심 목표 달성**:
- ✅ 4 개 버그 시나리오 해결 (단계 #8 시점)
- ✅ Mutator 단일 게이트웨이 구조 (단계 #11~#14): check_in_date / check_out_date 모든 변경이 `ReservationMutator.apply_changes` 통과
- ✅ FIELD_PERMISSIONS 권한 매트릭스 도입
- ✅ pin 자동 세팅 (MANUAL) + catch-up (NAVER) 흡수
- 🔵 `manually_extended_until` deprecation 은 별도 마일스톤 (frontend 동반)
