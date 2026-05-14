# 단계 #13 사전조사 — `naver_sync._update_reservation` 의 날짜 필드를 Mutator 로 위임

> 부모 계획: [mutator-migration-plan.md](./mutator-migration-plan.md) §E
> 분류: ⚫ 리팩토링 — 동작 동등성 보장
> 변경 규모: `app/services/naver_sync.py` ~30 라인 (가드 + catch-up 통합 → Mutator 호출)
> **범위 축소**: 분해 계획의 "전체 setattr → Mutator" 가 아니라 **check_in_date / check_out_date 만** 위임 (점진적). 다른 필드 (customer_name, phone, gender 등) 는 후속 PR.

---

## 1. 목적

`naver_sync._update_reservation` 의 check_in_date / check_out_date 처리를 Mutator 호출로 단일화. 단계 #4 (check_in 가드) + #5 (check_out OR 가드) + #9 (check_in catch-up) + #10 (check_out catch-up) 의 로직을 Mutator 가 흡수하지 않고, caller 가 catch-up 만 처리한 뒤 fields 에 넣어 Mutator.apply 가 pin 평가 + setattr.

## 2. 점진 접근 결정 — 왜 두 필드만

| 옵션 | 평가 |
|---|---|
| 전체 setattr (~20개 필드) 를 한 번에 Mutator 호출로 | silent regression 위험 ↑ — 각 setattr 의 미묘한 분기 (`is_split_managed`, `_create_reservation` 분기 등) 가 fields dict 화 과정에서 누락될 가능성 |
| **check_in_date / check_out_date 두 필드만 위임** (선택) | 본 마이그레이션의 핵심 (4개 버그) 와 직결된 필드만. 다른 setattr 는 그대로 — 동작 동등성 자명. 점진 확장 가능 |
| catch-up 로직을 Mutator 내부로 흡수 | 단계 #11 결정 위반 — catch-up 은 caller 에 남기기로 결정 |

→ **두 번째 옵션**. 본 마이그레이션의 silent regression 차단 원칙과 일치.

---

## 3. 변경 대상 코드

### 3-1. `app/services/naver_sync.py` L670~L685 (check_in_date 분기)

**Before** (단계 #9 머지 결과):

```python
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    incoming_check_in = res_data.get("date", existing.check_in_date)
    if not existing.check_in_pinned:
        existing.check_in_date = incoming_check_in
    elif incoming_check_in == existing.check_in_date:
        # Naver caught up to user-set value — clear pin
        existing.check_in_pinned = False
        diag(
            "naver_sync.check_in_pin_cleared",
            level="critical",
            reservation_id=existing.id,
            check_in_date=existing.check_in_date,
        )
    existing.check_in_time = res_data.get("time", existing.check_in_time)
```

**After**:

```python
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    incoming_check_in = res_data.get("date", existing.check_in_date)
    # check_in_pinned catch-up (Mutator 가 가드 평가 전 사전 해제)
    if existing.check_in_pinned and incoming_check_in == existing.check_in_date:
        existing.check_in_pinned = False
        diag(
            "naver_sync.check_in_pin_cleared",
            level="critical",
            reservation_id=existing.id,
            check_in_date=existing.check_in_date,
        )
    # Mutator: pinned=True 면 guarded → skip, False 면 setattr
    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(
        db, existing, ChangeSource.NAVER, {"check_in_date": incoming_check_in}
    )
    existing.check_in_time = res_data.get("time", existing.check_in_time)
```

**변경 내용**:
- if/elif 분기 (단계 #4 가드 + #9 catch-up) → Mutator.apply 호출로 교체
- catch-up 은 caller 가 사전 처리 (`pin=False` 로 풀어두면 Mutator 가 guarded 평가 통과)
- `check_in_time` 라인은 그대로 (FIELD_PERMISSIONS 미등록, allow-all 이지만 본 단계 범위 밖)

### 3-2. `app/services/naver_sync.py` L686~L730 (check_out_date 분기 — else 본문)

**Before** (단계 #10 머지 결과):

```python
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        if (
            existing.manually_extended_until
            and incoming_end < existing.check_out_date
            and incoming_end < existing.manually_extended_until
        ) or (
            existing.check_out_pinned
            and incoming_end < existing.check_out_date
        ):
            # User manually extended — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
                level="critical",
                reservation_id=existing.id,
                incoming_end=incoming_end,
                existing_end=existing.check_out_date,
                manually_extended_until=existing.manually_extended_until,
                naver_booking_id=existing.naver_booking_id,
            )
            # skip overwrite
        else:
            if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
                # Naver caught up — clear flag
                diag(
                    "naver_sync.user_extension_overridden",
                    level="critical",
                    reservation_id=existing.id,
                    incoming_end=incoming_end,
                    manually_extended_until=existing.manually_extended_until,
                )
                existing.manually_extended_until = None
            if existing.check_out_pinned and incoming_end >= existing.check_out_date:
                # Naver caught up to user-set value — clear pin
                existing.check_out_pinned = False
                diag(
                    "naver_sync.check_out_pin_cleared",
                    level="critical",
                    reservation_id=existing.id,
                    check_out_date=existing.check_out_date,
                    incoming_end=incoming_end,
                )
            existing.check_out_date = incoming_end
```

**After**:

```python
    incoming_end = res_data.get("end_date")
    if incoming_end is not None:
        if (
            existing.manually_extended_until
            and incoming_end < existing.check_out_date
            and incoming_end < existing.manually_extended_until
        ) or (
            existing.check_out_pinned
            and incoming_end < existing.check_out_date
        ):
            # User manually extended — preserve; naver hasn't caught up yet
            diag(
                "naver_sync.user_extension_preserved",
                level="critical",
                reservation_id=existing.id,
                incoming_end=incoming_end,
                existing_end=existing.check_out_date,
                manually_extended_until=existing.manually_extended_until,
                naver_booking_id=existing.naver_booking_id,
            )
            # skip overwrite
        else:
            if existing.manually_extended_until and incoming_end >= existing.manually_extended_until:
                # Naver caught up — clear flag
                diag(
                    "naver_sync.user_extension_overridden",
                    level="critical",
                    reservation_id=existing.id,
                    incoming_end=incoming_end,
                    manually_extended_until=existing.manually_extended_until,
                )
                existing.manually_extended_until = None
            if existing.check_out_pinned and incoming_end >= existing.check_out_date:
                # Naver caught up to user-set value — clear pin
                existing.check_out_pinned = False
                diag(
                    "naver_sync.check_out_pin_cleared",
                    level="critical",
                    reservation_id=existing.id,
                    check_out_date=existing.check_out_date,
                    incoming_end=incoming_end,
                )
            # Mutator: pinned=False (위에서 catch-up 처리됨) → guarded 통과 → setattr
            ReservationMutator.apply_changes(
                db, existing, ChangeSource.NAVER, {"check_out_date": incoming_end}
            )
```

**변경 내용**:
- 마지막 라인 `existing.check_out_date = incoming_end` 만 Mutator.apply 호출로 교체
- 첫 if 절 (보호 발동 — skip) 과 else 분기의 catch-up 로직은 그대로
- Mutator import 는 §3-1 에서 이미 함수 내에 있음 (재사용)

### 3-3. `manually_extended_until` 보호 분기는 그대로

`manually_extended_until` 의 보호 조건 (`incoming_end < check_out_date AND < manually_extended_until`) 은 Mutator 가 모르므로 caller 가 평가. 이 분기에 진입하면 fields 에 아예 안 넣음 → Mutator 호출 자체 안 함 → skip.

→ 기존 `manually_extended_until` 보호 동작 100% 보존.

---

## 4. 동작 동등성

### 4-1. check_in_date 분기 매트릭스

| pinned | incoming == existing | Before (#9) | After (#13) | 동등 |
|---|---|---|---|---|
| False | 무관 | setattr | catch-up 조건 False → Mutator.apply → guarded False → setattr | ✅ |
| True | False | skip | catch-up 조건 False → pin 유지 → Mutator.apply → guarded True → skip | ✅ |
| True | True | catch-up: pin=False (덮어쓰기 없음, 값 동일) | catch-up: pin=False (먼저) → Mutator.apply: guarded False → 값 비교 (동일) → setattr 안 함, applied={} | ✅ |

### 4-2. check_out_date 분기 매트릭스 (else 본문)

else 분기 진입 = `manually_extended_until` 가드 false AND (pinned=False 또는 `incoming >= existing.check_out_date`).

| manually_ext | pinned | catch-up 후 pinned | Mutator 결과 | Before 결과 | After 결과 | 동등 |
|---|---|---|---|---|---|---|
| 없음 | False | False | guarded False → setattr → applied | check_out_date=incoming_end | 동일 | ✅ |
| 있음, incoming≥me | False | False (manually_ext=None) | guarded False → setattr | manually_ext=None + setattr | 동일 | ✅ |
| 없음 | True, incoming≥check_out | False (catch-up) | guarded False → setattr | pin=False + setattr | 동일 | ✅ |
| 있음, incoming≥me | True, incoming≥check_out | False (둘 다 catch-up) | guarded False → setattr | manually_ext=None + pin=False + setattr | 동일 | ✅ |

### 4-3. 첫 if 절 (skip) 영향

`manually_extended_until` 보호 또는 `check_out_pinned and incoming < check_out_date` → skip 분기:
- Mutator.apply 호출 안 됨 (fields 에 안 넣음)
- diag 만 발생 (기존 동일)
- existing.check_out_date 변화 없음

→ 동작 100% 동등.

### 4-4. NAVER source 일 때 Mutator 의 pin 자동 세팅?

단계 #11 의 Mutator 코드:
```python
if source == ChangeSource.MANUAL:
    if "check_in_date" in applied: reservation.check_in_pinned = True
    ...
```

NAVER source 는 pin 자동 세팅 안 함. ✅ — naver_sync 가 의도치 않게 pin 을 set 하는 일 없음.

---

## 5. 영향받지 않음을 확인할 코드 경로

- `_update_reservation` 안의 다른 setattr 들 (customer_name, phone, visitor_name, visitor_phone, naver_biz_item_id, naver_room_type, party_size, biz_item_name, booking_count, booking_options, special_requests, total_price, status, gender, age_group, ...) — **변경 0, 그대로 setattr** (후속 PR 에서 확장)
- `_create_reservation` (신규 예약) — 변경 0
- status 트랜지션 진단 (`_prev_status != existing.status`) — 변경 0
- stay_group 자동 해제 (취소 시) — 변경 0
- room_assignment.shift_daily_records / reconcile_dates 후처리 — 변경 0
- invariant check (constraint_changed) — 변경 0
- 단계 #8 의 manually_extended_until + check_out_pinned 동시 클리어 (`naver_sync.py:747`) — 변경 0

---

## 6. 검증 체크리스트

- [ ] **syntax**: `venv/bin/python -m py_compile app/services/naver_sync.py` 에러 0
- [ ] **diff**: check_in 분기 if/elif → 단순 if + Mutator 호출 (~5 라인 차이), check_out else 분기의 setattr 라인 → Mutator 호출 (~3 라인 차이)
- [ ] **Mutator 호출 site 확장**: `grep -rn "ReservationMutator" app/` → reservations.py + naver_sync.py 두 곳
- [ ] **catch-up 시나리오 회귀** (단계 #9~#10 테스트와 동일):
  - check_in pinned=True, incoming==existing → pin=False, applied={}
  - check_in pinned=True, incoming!=existing → pin=True 유지, applied={}
  - check_in pinned=False → setattr
  - check_out manually_extended_until 보호 → skip (Mutator 호출 안 됨)
  - check_out catch-up → pin=False + setattr
- [ ] **기존 pytest 회귀**: pass/fail 개수 #12 시점과 동일

---

## 7. 본 단계 이후의 후속 의존성

- **#14** `reservations_stay.py extend/reduce` → check_out_date 만 Mutator 위임 (동일 점진 패턴)
- **후속 PR** (단계 외): naver_sync 의 나머지 setattr (~17개 필드) 를 fields dict 로 모아 Mutator.apply 한 번에 호출 — silent regression 검증 후 진행

---

## 8. 미결 검토 항목

- [ ] 본 단계 후 naver_sync 의 나머지 setattr 통합 — 별도 PR 시점 결정. 단순 setattr 는 Mutator 의 `permission="always"` 와 동일 결과이므로 일괄 가능.

---

## 9. 머지 후 다음 액션

`mutator-step-14-extend-reduce-via-mutator.md` 작성.
