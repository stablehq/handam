# 단계 #20+#21 사전조사 — private 화 + 미사용 import 제거

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §E
> 분류: ⚫ 리팩토링 (동작 동등)
> 변경 규모: rename 2건 + import 제거 2건

---

## 1. 사전 검증 결과

| 함수 | 외부 호출 site | 처리 가능? |
|---|---|---|
| `shift_daily_records` | 0건 (lifecycle 내부만) | ✅ `_shift_daily_records` 로 rename |
| `reconcile_dates` | 0건 (lifecycle 내부만) | ✅ `_reconcile_dates` 로 rename |
| `reconcile_chips_for_reservation` | room_auto_assign.py:564, naver_sync.py:340, room_assignment.py:204 — **3건 잔존** | ❌ 함수 삭제 불가, **미사용 import 제거만** |

`reconcile_chips_for_reservation` 의 다른 caller 들은 본 lifecycle 마이그레이션 범위 밖 (자동 배정의 stale 칩 재정렬, naver_sync 의 다른 sync 흐름, room_assignment.sync_sms_tags 내부). 별도 마일스톤 필요.

## 2. 변경 대상

### 2-1. `_shift_daily_records` rename

`app/services/room_assignment.py`:
- `def shift_daily_records(...)` → `def _shift_daily_records(...)`

`app/services/reservation_lifecycle.py`:
- `from app.services.room_assignment import shift_daily_records, reconcile_dates` → `from app.services.room_assignment import _shift_daily_records, _reconcile_dates`
- 호출: `shift_daily_records(...)` → `_shift_daily_records(...)`

### 2-2. `_reconcile_dates` rename (#2-1과 동시)

`app/services/room_assignment.py`:
- `def reconcile_dates(...)` → `def _reconcile_dates(...)`

### 2-3. 미사용 import 제거

`app/api/reservations_stay.py:165, 313`: `from app.services.chip_reconciler import reconcile_chips_for_reservation` — 단계 #16/#17 후 미사용.

## 3. 동작 동등성

- rename 만 — 호출 결과 동일
- 미사용 import 제거 — 영향 0
- private 화 (`_` 접두) 는 단순 컨벤션 — Python 에서 강제 아님, 단지 의도 표현

## 4. 검증 체크리스트

- [ ] syntax OK (room_assignment.py, reservation_lifecycle.py, reservations_stay.py)
- [ ] `shift_daily_records` / `reconcile_dates` (non-`_` prefix) 호출 site 0건
- [ ] 단계 D 의 lifecycle 호출이 여전히 정상 작동 (rename 후 lifecycle 함수도 동작)

## 5. 머지 후 다음 액션

`lifecycle-step-22-ci-lint.md` 작성 (#22).
