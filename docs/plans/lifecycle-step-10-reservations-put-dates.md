# 단계 #10 사전조사 — `reservations.py PUT` 날짜 분기 → `on_dates_changed` 호출

> 부모 계획: [lifecycle-migration-plan.md](./lifecycle-migration-plan.md) §D
> 분류: ⚫ 리팩토링 + 🔵 부수 효과 (reconcile_all_chips 중복 호출 — idempotent)
> 변경 규모: `app/api/reservations.py` ~5 라인 치환

---

## 1. 목적

`update_reservation` 의 날짜 변경 분기 (L394~L397) 의 `shift_daily_records + reconcile_dates` 호출을 `on_dates_changed` 단일 호출로 통합.

본 단계는 D 블록 첫 caller 전환. 단계 #11 에서 chip_affecting 가드 정리 시 중복 reconcile_all_chips 제거.

---

## 2. 변경 대상 코드

### `app/api/reservations.py` L393~L397 (날짜 변경 분기 끝부분)

**Before**:

```python
            db_reservation.manually_extended_until = None
        db.flush()
        room_assignment.shift_daily_records(
            db, db_reservation, old_dates[0], old_dates[1]
        )
        room_assignment.reconcile_dates(db, db_reservation)
```

**After**:

```python
            db_reservation.manually_extended_until = None
        db.flush()
        from app.services.reservation_lifecycle import on_dates_changed
        on_dates_changed(db, db_reservation, old_dates[0], old_dates[1])
```

**변경 내용**:
- `shift_daily_records(...)` 호출 (3 줄) + `reconcile_dates(...)` 호출 (1 줄) → `on_dates_changed(...)` 호출 (1 줄) + import (1 줄)
- 총 -2 라인

### 2-1. 1:1 매핑

| Before (caller) | After (on_dates_changed 내부, 단계 #5 §2) |
|---|---|
| `shift_daily_records(db, db_reservation, old_dates[0], old_dates[1])` | 동일 호출 (lifecycle 1단계) |
| `reconcile_dates(db, db_reservation)` | 동일 호출 (lifecycle 2단계) |
| (없음) | **신규 추가: `reconcile_all_chips(db, db_reservation.id)`** (lifecycle 3단계) |

### 2-2. 신규로 추가되는 `reconcile_all_chips` 호출 — 중복 분석

caller 의 후속 처리 (L443~L450):
```python
_SURCHARGE_FIELDS = {"male_count", "female_count", "party_size"}
chip_affecting = (
    sms_fields_changed   # check_in_date, check_out_date 포함 — 날짜 변경 시 True
    or constraint_changed
    or bool(_SURCHARGE_FIELDS & set(update_data.keys()))
)
if chip_affecting:
    db.flush()
    reconcile_all_chips(db, reservation_id)
```

날짜 변경 시:
- `sms_fields_changed = True` (check_in_date, check_out_date 가 `_SMS_TAG_FIELDS` 에 포함)
- 따라서 `chip_affecting=True` → `reconcile_all_chips` 호출

After 의 흐름:
1. `on_dates_changed` 내부에서 `reconcile_all_chips(db, reservation.id)` 호출
2. 함수 끝 `if chip_affecting:` 분기에서 `reconcile_all_chips(db, reservation_id)` 또 호출

→ **중복 호출 2회**. 단 `reconcile_all_chips` 는 idempotent (현재 상태를 보고 칩 재구성, 두 번 호출 = 동일 결과). **silent regression 0**.

- 성능 영향: 미세 (2회 chip reconcile, 일반적 < 5 칩 — ms 단위)
- 단계 #11 사전조사에서 caller 의 chip_affecting 가드 조건 변경 (`date 변경은 lifecycle 이 처리` 명시 + 가드 조건 축소) 검토

---

## 3. 동작 동등성

### 3-1. 날짜 변경 시나리오

| 시나리오 | Before | After | 동등 |
|---|---|---|---|
| 날짜 변경 PUT | shift + reconcile_dates + reconcile_all_chips (chip_affecting 가드로) | on_dates_changed (= shift + reconcile_dates + reconcile_all_chips) + reconcile_all_chips (chip_affecting 가드로 중복) | ✅ DB 결과 동등 |
| 날짜 안 바뀐 PUT (인원만) | shift / reconcile_dates 호출 0 + reconcile_all_chips (chip_affecting 가드로) | 동일 — `if old_dates != new_dates:` False 라 on_dates_changed 호출 0 | ✅ |

### 3-2. SMS 칩 결과

| 칩 종류 | Before 호출 횟수 | After 호출 횟수 | 결과 |
|---|---|---|---|
| sync_sms_tags (기본) | 1 (reconcile_all_chips 안에서) | 2 (on_dates_changed + 함수 끝 가드) | 동일 (idempotent) |
| reconcile_surcharge | 1 | 2 | 동일 |
| reconcile_party3_mms | 1 | 2 | 동일 |
| reconcile_room_upgrade_promise | 1 | 2 | 동일 |
| reconcile_room_upgrade_review | 1 | 2 | 동일 |

→ 모든 칩이 두 번 재구성되지만 결과 동일.

---

## 4. 영향받지 않음

- L382~L392 `manually_extended_until consistency` 분기 — 변경 0
- L394 `db.flush()` — 변경 0
- L399~L432 invariant check 분기 (단계 #11 에서 처리)
- L443~L450 chip_affecting 분기 — 변경 0 (단계 #11 에서 정리)
- 다른 caller 모두 변경 0

---

## 5. 검증 체크리스트

- [ ] syntax OK
- [ ] diff: -2 라인 (shift_daily_records 3 줄 + reconcile_dates 1 줄 → on_dates_changed 1 줄 + import 1 줄)
- [ ] on_dates_changed 호출 site 1건 추가
- [ ] 기존 `room_assignment.shift_daily_records` / `reconcile_dates` 외부 호출 site grep — naver_sync 와 다른 곳에 여전히 있어야 (단계 #13 까지)
- [ ] 기존 pytest 회귀

---

## 6. 머지 후 다음 액션

`lifecycle-step-11-reservations-put-constraints.md` 작성 (#11).
